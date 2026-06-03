"""PrinterBackend Protocol — transport contract used by drivers.

Two-method surface (print_image + query_status). A raw `send_bytes` escape
hatch was deliberately removed during design: there is no concrete caller
in First-Print, and opening a second TCP/9100 session in parallel with
ptouch would hit Brother's single-session limit (Resource Busy). The
hook can be added back additively if a future caller needs it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from PIL import Image

from app.models.tape import TapeSpec
from app.services.status_block import StatusBlock


@runtime_checkable
class PrinterBackend(Protocol):
    """Transport + encoding contract for a single bound printer."""

    backend_id: str
    host: str
    # Phase 1i C-Fix: PT-Series=True, QL-Series=False
    half_cut_supported: bool

    async def print_image(
        self,
        image: Image.Image,
        tape_spec: TapeSpec,
        *,
        auto_cut: bool = True,
        high_resolution: bool = False,
        half_cut: bool = False,
        last_page: bool = True,
    ) -> None:
        """Encode and send `image`. Raises a PrinterError subtype on failure.

        Phase 1i C-Fix:
        - half_cut: True bedeutet "tape + liner halb getrennt" (taktile Separation,
          nur PT-Series). Bei half_cut_supported=False vom Backend ignoriert.
        - last_page: True = letztes Item einer Batch (Voll-Cut), False = es folgt
          mindestens ein weiteres Item (kein Cut zwischen).
        """

    async def query_status(self) -> StatusBlock:
        """Send ESC i S, parse the 32-byte reply, return a StatusBlock."""
