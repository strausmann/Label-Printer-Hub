# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""A stand-in for the slice of ``PrinterRuntime`` the status and tape endpoints read."""

from __future__ import annotations

from uuid import UUID

from app.services.producers.tape_description import TapeDescription


class FakeRuntime:
    """``is_polled`` is true for the given printer ids only.

    ``labels`` maps a tape width to the label the attached model driver would give; other
    widths fall back to the generic ``"{N}mm"`` like the real runtime.
    """

    def __init__(
        self, polled: set[UUID] | None = None, labels: dict[int, str] | None = None
    ) -> None:
        self.polled = polled or set()
        self.labels = labels or {}

    def is_polled(self, printer_id: UUID) -> bool:
        return printer_id in self.polled

    def describe_tape_for(self, printer_id: UUID, width_mm: int) -> TapeDescription:
        return TapeDescription(label=self.labels.get(width_mm, f"{width_mm}mm"))
