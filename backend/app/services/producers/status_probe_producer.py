"""Polls SNMP every N seconds; publishes printer.status on state change.

Debounce (change-only publish): the producer stores the last published
PreflightStatus AND the last online flag.  A change is detected when ANY of
the following differ from the previous probe:

- hr_printer_status
- error_flags set
- online flag (True = SNMP success, False = exception)

On the first probe, always publish (initialises the client view).

The TapeChangeProducer is a collaborator: after each successful probe,
``tape_change_producer.on_probe_result`` is called with the old and new
PreflightStatus so tape-change events are derived from the same probe data
without a second polling loop.

Critical invariant: ``self._last`` is updated after EVERY probe (success
or offline), unconditionally and BEFORE the change check.  This prevents
two bugs:

1. Tape-loop (Finding #4): if _last is only updated when status changes,
   a tape-only change causes _has_changed() → False → _last not updated →
   next probe sees same 'from' tape → fires tape_changed again (infinite loop).

2. Online sentinel false-negative (Finding #5): if the previous real status
   was hr='other' + no errors AND the offline sentinel is also hr='other' +
   no errors, _has_changed() → False → offline event never published.
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
        # Track online state separately so that online→offline transitions
        # are detected even when hr_printer_status is unchanged (Finding #5).
        self._last_online: bool | None = None
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

    def _has_changed(self, new: PreflightStatus, new_online: bool) -> bool:
        """Return True if anything meaningful changed since the last probe."""
        if self._last is None or self._last_online is None:
            return True
        return (
            new.hr_printer_status != self._last.hr_printer_status
            or set(new.error_flags) != set(self._last.error_flags)
            or new_online != self._last_online
        )

    async def _loop(self) -> None:
        while True:
            try:
                status = await query_preflight(
                    self._host,
                    community=self._community,
                    timeout_s=5.0,
                )
                new_online = True

                # Notify tape producer BEFORE updating _last so it receives
                # the correct 'previous' tape state (old=self._last, new=status).
                if self._tape_producer is not None:
                    self._tape_producer.on_probe_result(self._printer_id, self._last, status)

                changed = self._has_changed(status, new_online)

                # Always update _last BEFORE any early continue so that:
                # - tape producer sees the correct 'from' tape on the next probe
                # - online→offline transitions are not swallowed by stale _last
                self._last = status
                self._last_online = new_online

                if changed:
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
                new_online = False
                changed = self._has_changed(offline, new_online)

                # Update _last unconditionally (same reasoning as success branch).
                self._last = offline
                self._last_online = new_online

                if changed:
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
