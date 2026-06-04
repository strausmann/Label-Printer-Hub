"""PrinterBackend Protocol — transport contract used by drivers.

Two-method surface (print_image + query_status). A raw `send_bytes` escape
hatch was deliberately removed during design: there is no concrete caller
in First-Print, and opening a second TCP/9100 session in parallel with
ptouch would hit Brother's single-session limit (Resource Busy). The
hook can be added back additively if a future caller needs it.

Phase 1k.2: print_images() added for batch printing via ptouch.print_multi
on PT-Series. Other backends delegate to default_print_images_loop helper.
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

    async def print_images(
        self,
        images: list[Image.Image],
        tape_spec: TapeSpec,
        *,
        auto_cut: bool = True,
        high_resolution: bool = False,
        half_cut: bool = True,
    ) -> None:
        """Batch-print N images — atomic-or-best-effort je nach Backend-Impl.

        Semantik haengt vom konkreten Backend ab:
        - PTouchBackend via ptouch.print_multi: ATOMIC — auf Hardware-Ebene ein
          einziger Print-Call. Bei Exception sind ggf. 0 oder ALLE Labels gedruckt,
          niemals partial.
        - Default-Loop (BrotherQLBackend, MockBackend) via
          default_print_images_loop: BEST-EFFORT per item. Wenn item N
          fehlschlaegt, koennen items 0..N-1 bereits physisch gedruckt sein.
          Job-State-Handling muss damit umgehen (siehe Task 8 _process_batch).
        (Copilot-Review C5 PR #106: vorher 'atomic semantics: success or all-fail'
        war falsch fuer den default loop.)

        Phase 1k.2: Default-Loop ueber print_image() lebt in
        ``app.printer_backends.batch_helper.default_print_images_loop``.
        PTouchBackend ueberschreibt fuer ptouch.print_multi() (echtes
        batch-fertig mit 5mm Half-Cut zwischen Labels statt 22.5mm Pre-Roll).
        BrotherQLBackend und MockBackend delegieren explizit an den
        default_print_images_loop helper.

        Args:
            images: PIL Images in print order. len(images) >= 1.
            tape_spec: Shared TapeSpec — alle Items teilen das geladene Tape.
            auto_cut: True = Drucker schneidet am Ende des Batches.
            high_resolution: PT-Series HiRes-Mode.
            half_cut: True = 5mm taktile Separation zwischen Items (PT-Series).
                Letztes Item bekommt immer Voll-Cut (half_cut=False intern).
        """

    async def query_status(self) -> StatusBlock:
        """Send ESC i S, parse the 32-byte reply, return a StatusBlock."""
