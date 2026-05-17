"""Detects tape swaps between consecutive SNMP probe results.

Not a separate loop — called by StatusProbeProducer after each successful
probe so tape-change events are zero-latency relative to the probe that
produced them.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Protocol

from app.printer_backends.snmp_helper import PreflightStatus
from app.services.event_bus import BusEvent, EventBus
from app.services.producers.tape_description import TapeDescription
from app.services.tape_registry import TapeRegistry

_log = logging.getLogger(__name__)

# Re-export so existing ``from tape_change_producer import TapeDescription``
# callers don't break.
__all__ = ["DescribesTape", "TapeChangeProducer", "TapeDescription"]


class DescribesTape(Protocol):
    """Structural sub-protocol for the tape-description capability.

    Any object that implements ``describe_tape`` satisfies this protocol.
    ``PrinterModel`` implementors should add ``describe_tape`` so that
    ``TapeChangeProducer`` can delegate without knowing the tape-class
    specifics (Finding F6).
    """

    def describe_tape(self, width_mm: int) -> TapeDescription:
        """Return a human-readable description for a tape of *width_mm* mm.

        Must never raise — return a safe fallback label (e.g. ``"<N>mm"``)
        when the width is unknown.
        """
        ...


class TapeChangeProducer:
    """Publish ``printer.tape_changed`` when loaded_tape_mm changes.

    When a *model* is supplied it delegates tape-class lookup to
    ``model.describe_tape(width_mm)``.  This keeps model-specific logic
    (PT-Series TZe laminated, QL-Series DK continuous, …) inside the
    model module, making ``TapeChangeProducer`` genuinely series-neutral.

    When no *model* is given the producer falls back to the legacy
    ``tape_registry.lookup_pt`` call for backward compatibility.
    """

    def __init__(
        self,
        bus: EventBus,
        tape_registry: TapeRegistry,
        model: DescribesTape | None = None,
    ) -> None:
        self._bus = bus
        self._tape_registry = tape_registry
        self._model = model

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
            if self._model is not None:
                # Preferred path: delegate to the model's tape-class knowledge
                tape_label = self._model.describe_tape(new_mm).label
            else:
                # Legacy fallback: PT-Series hard-coded lookup via registry
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
