"""Protocol contract for printer-model plugins.

Each printer-model family (PT-Series, QL-Series, future series) lives in its
own module under app.printer_models.<series>, implements this Protocol, and
registers itself in app.printer_models.registry.ModelRegistry.

The Protocol is `runtime_checkable` so the registry can `isinstance()`-verify
candidates before adding them.
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
