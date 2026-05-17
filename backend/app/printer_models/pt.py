"""Tape data for Brother PT-Series printers (180 DPI, 128-pin head).

Source: Brother Raster Command Reference (PT-E550W / PT-P710BT / PT-P750W) v1.02.
The numbers here come straight from the manufacturer's printable-area tables.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar, cast
from uuid import UUID, uuid4

from PIL import Image

from app.models.tape import TapeSpec
from app.printer_backends.base import PrinterBackend
from app.printer_models.base import PrinterModel
from app.printer_models.registry import ModelRegistry
from app.services.producers.tape_description import TapeDescription
from app.services.status_block import MediaType, StatusBlock

if TYPE_CHECKING:
    from app.services.tape_registry import TapeRegistry

# TZe laminated tapes. The non-laminated TZe-N* variants share the same
# print-area geometry — only the material differs — so we reuse this list
# for MediaType.NON_LAMINATED in the registry.
PT_TZE_TAPES: tuple[TapeSpec, ...] = (
    TapeSpec(
        width_mm=4,
        media_type=MediaType.LAMINATED,
        print_area_pins=24,
        print_area_dots=24,
        bytes_per_raster=16,
        min_length_mm=4.4,
        max_length_mm=1000,
        cutter_min_length_mm=24.5,
    ),
    TapeSpec(
        width_mm=6,
        media_type=MediaType.LAMINATED,
        print_area_pins=32,
        print_area_dots=32,
        bytes_per_raster=16,
        min_length_mm=4.4,
        max_length_mm=1000,
        cutter_min_length_mm=24.5,
    ),
    TapeSpec(
        width_mm=9,
        media_type=MediaType.LAMINATED,
        print_area_pins=50,
        print_area_dots=50,
        bytes_per_raster=16,
        min_length_mm=4.4,
        max_length_mm=1000,
        cutter_min_length_mm=24.5,
    ),
    TapeSpec(
        width_mm=12,
        media_type=MediaType.LAMINATED,
        print_area_pins=70,
        print_area_dots=70,
        bytes_per_raster=16,
        min_length_mm=4.4,
        max_length_mm=1000,
        cutter_min_length_mm=24.5,
    ),
    TapeSpec(
        width_mm=18,
        media_type=MediaType.LAMINATED,
        print_area_pins=112,
        print_area_dots=112,
        bytes_per_raster=16,
        min_length_mm=4.4,
        max_length_mm=1000,
        cutter_min_length_mm=24.5,
    ),
    TapeSpec(
        width_mm=24,
        media_type=MediaType.LAMINATED,
        print_area_pins=128,
        print_area_dots=128,
        bytes_per_raster=16,
        min_length_mm=4.4,
        max_length_mm=1000,
        cutter_min_length_mm=24.5,
    ),
)

# Heat-shrink tubing 2:1 (status-block media-type byte = 0x11).
# Widths are nominal — actual tape is slightly narrower (e.g. 12mm HS = ~11.7mm).
# Pin counts are the Brother-published values.
PT_HS_2_1_TAPES: tuple[TapeSpec, ...] = (
    TapeSpec(
        width_mm=6,
        media_type=MediaType.HEAT_SHRINK_2_1,
        print_area_pins=28,
        print_area_dots=28,
        bytes_per_raster=16,
        min_length_mm=4.4,
        max_length_mm=500,
        cutter_min_length_mm=24.5,
    ),
    TapeSpec(
        width_mm=9,
        media_type=MediaType.HEAT_SHRINK_2_1,
        print_area_pins=48,
        print_area_dots=48,
        bytes_per_raster=16,
        min_length_mm=4.4,
        max_length_mm=500,
        cutter_min_length_mm=24.5,
    ),
    TapeSpec(
        width_mm=12,
        media_type=MediaType.HEAT_SHRINK_2_1,
        print_area_pins=66,
        print_area_dots=66,
        bytes_per_raster=16,
        min_length_mm=4.4,
        max_length_mm=500,
        cutter_min_length_mm=24.5,
    ),
    TapeSpec(
        width_mm=18,
        media_type=MediaType.HEAT_SHRINK_2_1,
        print_area_pins=106,
        print_area_dots=106,
        bytes_per_raster=16,
        min_length_mm=4.4,
        max_length_mm=500,
        cutter_min_length_mm=24.5,
    ),
    TapeSpec(
        width_mm=24,
        media_type=MediaType.HEAT_SHRINK_2_1,
        print_area_pins=128,
        print_area_dots=128,
        bytes_per_raster=16,
        min_length_mm=4.4,
        max_length_mm=500,
        cutter_min_length_mm=24.5,
    ),
)


# === First-Print: PT-P750W driver + queue-printer bridge ===

_pt_log = logging.getLogger(__name__)


class PTP750WDriver:
    """Driver for the Brother PT-P750W. Bound to one PrinterBackend at construction.

    Implements PrinterModel and provides make_queue_printer() for the queue.
    """

    model_id = "PT-P750W"
    pjl_signatures: ClassVar[list[str]] = ["PT-P750W"]
    snmp_model_oid_value_substr = "PT-P750W"
    dpi = (180, 180)
    print_head_pins = 128

    def __init__(self, backend: PrinterBackend) -> None:
        self._backend = backend

    async def query_status(
        self,
        host: str,
        port: int = 9100,  # noqa: ARG002
        timeout_s: float = 5.0,  # noqa: ARG002
    ) -> StatusBlock:
        # Protocol requires `host` positionally. The driver is bound to a
        # backend that already knows its host. Empty string = "use bound
        # backend's host"; a non-matching non-empty host raises loudly.
        if host and host != self._backend.host:
            raise ValueError(
                f"Driver bound to backend.host={self._backend.host!r}; "
                f"got host={host!r}. Construct a new driver/backend pair instead."
            )
        return await self._backend.query_status()

    def width_to_pixels(self, tape_spec: TapeSpec) -> int:
        return int(tape_spec.print_area_pins)

    def build_print_job(
        self,
        image: Image.Image,
        tape_spec: TapeSpec,
        auto_cut: bool = True,
        high_resolution: bool = False,
    ) -> bytes:
        """Encoding is owned by the backend (ptouch handles raster build).

        First-Print happy path goes through backend.print_image() and does
        NOT call this method. Raise loudly so unintended callers fail fast.
        """
        raise NotImplementedError(
            "PTP750WDriver delegates encoding to backend.print_image(). "
            "build_print_job() will be implemented when a real caller "
            "(raw-export, debugging, non-library backend) appears."
        )

    def describe_tape(self, width_mm: int) -> TapeDescription:
        """Return a human-readable description for a PT-Series tape of *width_mm* mm.

        Checks PT_TZE_TAPES (laminated TZe) first, then PT_HS_2_1_TAPES
        (heat-shrink 2:1).  Falls back to ``"<N>mm"`` for unknown widths so
        the method never raises (Finding F6).
        """
        for spec in PT_TZE_TAPES:
            if spec.width_mm == width_mm:
                return TapeDescription(label=f"{width_mm}mm TZe")
        for spec in PT_HS_2_1_TAPES:
            if spec.width_mm == width_mm:
                return TapeDescription(label=f"{width_mm}mm HS")
        # Unknown width — safe fallback
        return TapeDescription(label=f"{width_mm}mm")

    def make_queue_printer(
        self,
        tape_registry: TapeRegistry,
        *,
        default_media_type: MediaType = MediaType.LAMINATED,
        printer_id: UUID | None = None,
    ) -> _PTPQueuePrinter:
        pid = printer_id if printer_id is not None else uuid4()
        return _PTPQueuePrinter(
            driver=self,
            backend=self._backend,
            tape_registry=tape_registry,
            default_media_type=default_media_type,
            printer_id=pid,
        )


class _PTPQueuePrinter:
    """Private _PrinterLike adapter — produced by PTP750WDriver.make_queue_printer."""

    def __init__(
        self,
        *,
        driver: PTP750WDriver,
        backend: PrinterBackend,
        tape_registry: TapeRegistry,
        default_media_type: MediaType,
        printer_id: UUID,
    ) -> None:
        self._driver = driver
        self._backend = backend
        self._tape_registry = tape_registry
        self._default_media_type = default_media_type
        self.id: UUID = printer_id

    async def print_image(self, image: Image.Image, *, tape_mm: int, **options: Any) -> None:
        media_type = options.pop("media_type", self._default_media_type)
        tape_spec = self._tape_registry.lookup_pt(tape_mm, media_type)
        await self._backend.print_image(
            image,
            tape_spec,
            auto_cut=bool(options.pop("auto_cut", True)),
            high_resolution=bool(options.pop("high_resolution", False)),
        )


# Module-level registration so any import path triggers it.
# cast: PTP750WDriver satisfies PrinterModel structurally at runtime;
# mypy cannot verify Protocol conformance for class-level attributes.
ModelRegistry.register(cast("type[PrinterModel]", PTP750WDriver))
