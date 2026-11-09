"""A stand-in for the slice of ``PrinterRuntime`` the status endpoint reads."""

from __future__ import annotations

from uuid import UUID


class FakeRuntime:
    """``is_polled`` is true for the given printer ids only."""

    def __init__(self, polled: set[UUID] | None = None) -> None:
        self.polled = polled or set()

    def is_polled(self, printer_id: UUID) -> bool:
        return printer_id in self.polled
