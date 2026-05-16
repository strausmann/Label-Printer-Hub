"""Detects tape swaps between consecutive SNMP probe results.

Not a separate loop — called by StatusProbeProducer after each successful
probe so tape-change events are zero-latency relative to the probe that
produced them.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.printer_backends.snmp_helper import PreflightStatus
from app.services.event_bus import BusEvent, EventBus
from app.services.tape_registry import TapeRegistry

_log = logging.getLogger(__name__)


class TapeChangeProducer:
    """Publish ``printer.tape_changed`` when loaded_tape_mm changes."""

    def __init__(self, bus: EventBus, tape_registry: TapeRegistry) -> None:
        self._bus = bus
        self._tape_registry = tape_registry

    def on_probe_result(
        self,
        printer_id: str,
        old: PreflightStatus | None,
        new: PreflightStatus,
    ) -> None:
        """Compare old and new tape widths; publish if they differ."""
        old_mm = old.loaded_tape_mm if old is not None else None
        new_mm = new.loaded_tape_mm
        if old_mm == new_mm:
            return

        channel = f"printer:{printer_id}:tape"
        tape_label: str | None = None
        if new_mm is not None:
            try:
                from app.services.status_block import MediaType

                spec = self._tape_registry.lookup_pt(new_mm, MediaType.LAMINATED)
                tape_label = f"{spec.width_mm}mm"
            except Exception:
                tape_label = f"{new_mm}mm"

        self._bus.publish(
            channel,
            BusEvent(
                channel=channel,
                event_id=self._bus.next_event_id(channel),
                event_type="printer.tape_changed",
                timestamp=datetime.now(UTC),
                data={"from_mm": old_mm, "to_mm": new_mm, "tape_label": tape_label},
            ),
        )
