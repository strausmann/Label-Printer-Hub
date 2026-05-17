"""TapeDescription — shared data transfer object for tape-label metadata.

Lives in its own module to avoid circular imports between
``app.printer_models.base`` (Protocol) and
``app.services.producers.tape_change_producer`` (consumer).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TapeDescription:
    """Human-readable description of a loaded tape.

    Returned by :meth:`PrinterModel.describe_tape` so model-specific
    tape-class knowledge stays inside the printer-model module rather than
    in the generic producer (Finding F6).
    """

    label: str
    """Short display string, e.g. "12mm TZe", "62mm DK", "9mm HS"."""
