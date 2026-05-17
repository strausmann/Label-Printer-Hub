"""Protocol contract for printer-model plugins.

Each printer-model family (PT-Series, QL-Series, future series) lives in its
own module under app.printer_models.<series>, implements this Protocol, and
registers itself in app.printer_models.registry.ModelRegistry.

The Protocol is `@runtime_checkable` so plugin authors and guard utilities
can validate candidates with isinstance() if desired; the registry itself
does not enforce this at registration.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from PIL import Image

from app.models.tape import TapeSpec
from app.services.status_block import StatusBlock


@runtime_checkable
class PrinterModel(Protocol):
    """Per-model-family driver contract."""

    model_id: str  # canonical, e.g. "PT-P750W"
    pjl_signatures: list[str]  # PJL MDL substrings this plugin handles
    snmp_model_oid_value_substr: str  # substring of the SNMP OID 2435.2.3.9.1.1.7.0 value
    dpi: tuple[int, int]  # (width_dpi, height_dpi)
    print_head_pins: int  # physical pin count

    async def query_status(
        self,
        host: str,
        port: int = 9100,
        timeout_s: float = 5.0,
    ) -> StatusBlock:
        """Send ESC i S to the printer, read the 32-byte reply, return parsed status."""

    def width_to_pixels(self, tape_spec: TapeSpec) -> int:
        """Return the number of pixels along the print-head axis for the given tape."""

    def build_print_job(
        self,
        image: Image.Image,
        tape_spec: TapeSpec,
        auto_cut: bool = True,
        high_resolution: bool = False,
    ) -> bytes:
        """Encode an image into the Brother raster byte-stream for this model."""

    def describe_tape(self, width_mm: int) -> TapeDescription:
        """Return a human-readable description for a tape of *width_mm* mm.

        Must never raise — return a safe fallback label (e.g. ``"<N>mm"``)
        when the width is unknown or unsupported by this model family.

        Model-specific tape-class logic (PT-Series TZe laminated, QL-Series
        DK continuous, …) belongs here rather than in the generic
        ``TapeChangeProducer`` (Finding F6).
        """


# TapeDescription lives in a standalone module to avoid circular imports.
# We import it here so the Protocol annotation is resolvable by type-checkers.
from app.services.producers.tape_description import TapeDescription as TapeDescription  # noqa: E402
