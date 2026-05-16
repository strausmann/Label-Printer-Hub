"""Polls SNMP every N seconds; publishes printer.status on state change.

Debounce (change-only publish): the producer stores the last published
PreflightStatus. If the new status is identical (same hr_printer_status and
same error_flags set), no event is published. On the first probe, always
publish (initialises the client view).

The TapeChangeProducer is a collaborator: after each successful probe,
``tape_change_producer.on_probe_result`` is called with the old and new
PreflightStatus so tape-change events are derived from the same probe data
without a second polling loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime

from app.printer_backends.snmp_helper import PreflightStatus, query_preflight
from app.services.event_bus import BusEvent, EventBus
from app.services.producers.tape_change_producer import TapeChangeProducer

_log = logging.getLogger(__name__)


class StatusProbeProducer:
    """Background SNMP probe loop; publishes printer.status on change."""

    def __init__(
        self,
        bus: EventBus,
        printer_id: str,
        host: str,
        *,
        interval_s: float = 30.0,
        community: str = "public",
        tape_change_producer: TapeChangeProducer | None = None,
    ) -> None:
        self._bus = bus
        self._printer_id = printer_id
        self._host = host
        self._interval_s = interval_s
        self._community = community
        self._tape_producer = tape_change_producer
        self._last: PreflightStatus | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the background probe task."""
        self._task = asyncio.create_task(self._loop(), name=f"status-probe-{self._printer_id}")

    async def stop(self) -> None:
        """Cancel the background probe task and await its exit."""
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    def _has_changed(self, new: PreflightStatus) -> bool:
        if self._last is None:
            return True
        return new.hr_printer_status != self._last.hr_printer_status or set(new.error_flags) != set(
            self._last.error_flags
        )

    async def _loop(self) -> None:
        while True:
            try:
                status = await query_preflight(
                    self._host,
                    community=self._community,
                    timeout_s=5.0,
                )
                # Tape-change detection runs before the status change check so
                # tape events are always emitted even if status is unchanged.
                if self._tape_producer is not None:
                    self._tape_producer.on_probe_result(self._printer_id, self._last, status)
                if self._has_changed(status):
                    self._last = status
                    channel = f"printer:{self._printer_id}:state"
                    self._bus.publish(
                        channel,
                        BusEvent(
                            channel=channel,
                            event_id=self._bus.next_event_id(channel),
                            event_type="printer.status",
                            timestamp=datetime.now(UTC),
                            data={
                                "hr_printer_status": status.hr_printer_status,
                                "error_flags": list(status.error_flags),
                                "online": True,
                            },
                        ),
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                _log.exception(
                    "StatusProbeProducer: SNMP probe failed for printer=%s",
                    self._printer_id,
                )
                offline = PreflightStatus(
                    hr_printer_status="other",
                    loaded_tape_mm=None,
                    error_flags=[],
                )
                if self._has_changed(offline):
                    self._last = offline
                    channel = f"printer:{self._printer_id}:state"
                    self._bus.publish(
                        channel,
                        BusEvent(
                            channel=channel,
                            event_id=self._bus.next_event_id(channel),
                            event_type="printer.status",
                            timestamp=datetime.now(UTC),
                            data={
                                "hr_printer_status": "other",
                                "error_flags": [],
                                "online": False,
                            },
                        ),
                    )
            await asyncio.sleep(self._interval_s)
