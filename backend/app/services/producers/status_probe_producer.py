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

Critical invariant — probe iteration order (bot-review Finding F3):

1. ``tape_change_producer.on_probe_result(printer_id, old=self._last, new=status)``
   is called FIRST so the tape producer sees the correct 'from' tape state
   (self._last still holds the previous value at this point).

2. ``_has_changed(status, new_online)`` runs NEXT.  It compares the new probe
   result against the CURRENT ``self._last`` (still the previous value) to
   detect any meaningful difference.  This is intentional: the change-check
   REQUIRES the old _last to compute a diff.

3. ``self._last`` and ``self._last_online`` are updated UNCONDITIONALLY AFTER
   both steps above.  Updating before step 1 or 2 would break tape detection
   (tape producer would see old==new) or change detection (diff is always zero).

This unconditional update prevents two bugs regardless of whether status
changed:

- Tape-loop: if _last is only updated when status changes, a tape-only change
  causes _has_changed() → False → _last not updated → next probe sees same
  'from' tape → fires tape_changed again (infinite loop).

- Online sentinel false-negative: if the previous real status was
  hr='other' + no errors AND the offline sentinel is also hr='other' + no
  errors, _has_changed() → False → offline event never published.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from uuid import UUID

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

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    async def _upsert_cache(self, snmp_result: PreflightStatus) -> None:
        """Persist a successful SNMP probe result into printer_status_cache."""
        from app.db.engine import async_session
        from app.models.printer_status_cache import PrinterStatusCache

        printer_uuid = (
            UUID(self._printer_id) if isinstance(self._printer_id, str) else self._printer_id
        )
        parsed = {
            "online": True,
            "loaded_tape_mm": snmp_result.loaded_tape_mm,
            "hr_printer_status": snmp_result.hr_printer_status,
            "error_flags": list(snmp_result.error_flags),
        }
        now = datetime.now(UTC)
        async with async_session() as s:
            row = await s.get(PrinterStatusCache, printer_uuid)
            if row is not None:
                row.parsed = parsed
                row.raw_block = None
                row.captured_at = now
            else:
                s.add(
                    PrinterStatusCache(
                        printer_id=printer_uuid,
                        parsed=parsed,
                        raw_block=None,
                        captured_at=now,
                    )
                )
            await s.commit()

    async def _mark_offline(self, exc: Exception) -> None:
        """Persist a failed probe; preserves any previous parsed snapshot."""
        from app.db.engine import async_session
        from app.models.printer_status_cache import PrinterStatusCache

        printer_uuid = (
            UUID(self._printer_id) if isinstance(self._printer_id, str) else self._printer_id
        )
        now = datetime.now(UTC)
        async with async_session() as s:
            row = await s.get(PrinterStatusCache, printer_uuid)
            parsed: dict[str, object] = (
                dict(row.parsed) if (row is not None and row.parsed) else {}
            )
            parsed["online"] = False
            parsed["last_error"] = str(exc)
            if row is not None:
                row.parsed = parsed
                row.captured_at = now
            else:
                s.add(
                    PrinterStatusCache(
                        printer_id=printer_uuid,
                        parsed=parsed,
                        captured_at=now,
                    )
                )
            await s.commit()

    # ------------------------------------------------------------------
    # Single probe iteration (extracted for testability)
    # ------------------------------------------------------------------

    async def _probe_once(self) -> None:
        """Run one SNMP probe cycle: query, write cache, publish on change."""
        try:
            status = await query_preflight(
                self._host,
                community=self._community,
                timeout_s=5.0,
            )
            new_online = True

            # Write to cache first (always)
            await self._upsert_cache(status)

            # Notify tape producer BEFORE updating _last so it receives
            # the correct 'previous' tape state (old=self._last, new=status).
            if self._tape_producer is not None:
                self._tape_producer.on_probe_result(self._printer_id, self._last, status)

            changed = self._has_changed(status, new_online)

            # Update _last AFTER both tape-notification and change-check so
            # that (a) the tape producer above received the correct 'from'
            # tape, (b) _has_changed compared against the real previous
            # value.  Unconditional update prevents stale-_last bugs on
            # the next iteration (see module docstring invariant).
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
        except Exception as exc:
            _log.exception(
                "StatusProbeProducer: SNMP probe failed for printer=%s",
                self._printer_id,
            )

            # Write offline state to cache (preserves prior data)
            await self._mark_offline(exc)

            offline = PreflightStatus(
                hr_printer_status="other",
                loaded_tape_mm=None,
                error_flags=[],
            )
            new_online = False
            changed = self._has_changed(offline, new_online)

            # Update _last unconditionally AFTER change-check (same reasoning as
            # success branch — see module docstring invariant).
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

    async def _loop(self) -> None:
        while True:
            await self._probe_once()
            await asyncio.sleep(self._interval_s)
