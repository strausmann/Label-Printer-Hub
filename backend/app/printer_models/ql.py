"""Phase 1i Sub-Task G: QL-Series Printer-Model.

Naming follows pt.py (ADR 0004 — m2-Fix: ql.py, not ql_series.py).

Tape data sourced from:
  brother_ql.devicedependent.label_type_specs — endless (continuous) DK labels.
  Brother QL-800/810W/820NWB Raster Command Reference v1.01.

Only endless (CONTINUOUS_LENGTH_TAPE) DK labels are registered here;
die-cut labels can be added in a future phase with their own MediaType entry.
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


# QL-Series DK continuous (endless) tape specs.
# dots_printable from brother_ql.devicedependent.label_type_specs (v0.9.x).
# bytes_per_raster: ceil(dots_printable / 8), rounded to the next byte.
# QL-Series does not use a fixed bytes_per_raster like PT; the value here is
# informational and used only for TapeSpec storage; the brother_ql library
# handles the actual raster encoding.
QL_DK_ENDLESS_TAPES: tuple[TapeSpec, ...] = (
    TapeSpec(
        width_mm=12,
        media_type=MediaType.CONTINUOUS_LENGTH_TAPE,
        print_area_pins=106,
        print_area_dots=106,
        bytes_per_raster=14,  # ceil(106/8) = 14
        min_length_mm=0,
        max_length_mm=30480,
        cutter_min_length_mm=0,
    ),
    TapeSpec(
        width_mm=29,
        media_type=MediaType.CONTINUOUS_LENGTH_TAPE,
        print_area_pins=306,
        print_area_dots=306,
        bytes_per_raster=39,  # ceil(306/8) = 39
        min_length_mm=0,
        max_length_mm=30480,
        cutter_min_length_mm=0,
    ),
    TapeSpec(
        width_mm=38,
        media_type=MediaType.CONTINUOUS_LENGTH_TAPE,
        print_area_pins=413,
        print_area_dots=413,
        bytes_per_raster=52,  # ceil(413/8) = 52
        min_length_mm=0,
        max_length_mm=30480,
        cutter_min_length_mm=0,
    ),
    TapeSpec(
        width_mm=50,
        media_type=MediaType.CONTINUOUS_LENGTH_TAPE,
        print_area_pins=554,
        print_area_dots=554,
        bytes_per_raster=70,  # ceil(554/8) = 70
        min_length_mm=0,
        max_length_mm=30480,
        cutter_min_length_mm=0,
    ),
    TapeSpec(
        width_mm=54,
        media_type=MediaType.CONTINUOUS_LENGTH_TAPE,
        print_area_pins=590,
        print_area_dots=590,
        bytes_per_raster=74,  # ceil(590/8) = 74
        min_length_mm=0,
        max_length_mm=30480,
        cutter_min_length_mm=0,
    ),
    TapeSpec(
        width_mm=62,
        media_type=MediaType.CONTINUOUS_LENGTH_TAPE,
        print_area_pins=696,
        print_area_dots=696,
        bytes_per_raster=87,  # ceil(696/8) = 87
        min_length_mm=0,
        max_length_mm=30480,
        cutter_min_length_mm=0,
    ),
)


_ql_log = logging.getLogger(__name__)


class QL820NWBDriver:
    """Driver for the Brother QL-820NWB. Bound to one PrinterBackend at construction.

    Implements PrinterModel structurally (duck-typed) and provides
    make_queue_printer() for the lifespan printer queue.

    QL-820NWB specs:
      - 300 DPI (horizontal and vertical)
      - 696 print-head pins (62mm tape — maximum)
      - two_color capable (black + red on DK-2251), but red=False in Phase 1i
    """

    model_id = "QL-820NWB"
    pjl_signatures: ClassVar[list[str]] = ["QL-820NWB"]
    snmp_model_oid_value_substr = "QL-820NWB"
    dpi = (300, 300)
    print_head_pins = 696  # maximum for 62mm tape

    def __init__(self, backend: PrinterBackend) -> None:
        self._backend = backend

    async def query_status(
        self,
        host: str,
        port: int = 9100,  # noqa: ARG002
        timeout_s: float = 5.0,  # noqa: ARG002
    ) -> StatusBlock:
        """Delegates to backend.query_status().

        If ``host`` is given and does not match the bound backend host, raise
        loudly so callers notice misconfigured driver/backend pairs (mirrors
        PTP750WDriver behaviour).
        """
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
        """Encoding is owned by BrotherQLBackend via the brother_ql library.

        build_print_job() raises loudly so unintended callers fail fast —
        the production path goes through backend.print_image() (mirrors
        PTP750WDriver pattern).
        """
        raise NotImplementedError(
            "QL820NWBDriver delegates encoding to backend.print_image() via "
            "the brother_ql library. build_print_job() has no caller in Phase 1i."
        )

    def describe_tape(self, width_mm: int) -> TapeDescription:
        """Return a human-readable description for a QL DK endless tape.

        Falls back to ``"<N>mm DK"`` for unknown widths so the method never
        raises (mirrors PTP750WDriver.describe_tape Finding F6 fix).
        """
        for spec in QL_DK_ENDLESS_TAPES:
            if spec.width_mm == width_mm:
                return TapeDescription(label=f"{width_mm}mm DK")
        return TapeDescription(label=f"{width_mm}mm DK")

    def make_queue_printer(
        self,
        tape_registry: TapeRegistry,
        *,
        default_media_type: MediaType = MediaType.CONTINUOUS_LENGTH_TAPE,
        printer_id: UUID | None = None,
    ) -> _QLQueuePrinter:
        pid = printer_id if printer_id is not None else uuid4()
        return _QLQueuePrinter(
            driver=self,
            backend=self._backend,
            tape_registry=tape_registry,
            default_media_type=default_media_type,
            printer_id=pid,
        )


class _QLQueuePrinter:
    """Private _PrinterLike adapter — produced by QL820NWBDriver.make_queue_printer."""

    def __init__(
        self,
        *,
        driver: QL820NWBDriver,
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
        tape_spec = self._tape_registry.lookup_ql(tape_mm, media_type)
        await self._backend.print_image(
            image,
            tape_spec,
            auto_cut=bool(options.pop("auto_cut", True)),
            high_resolution=bool(options.pop("high_resolution", False)),
        )


# Module-level registration so any import path triggers it.
# cast: QL820NWBDriver satisfies PrinterModel structurally at runtime.
ModelRegistry.register(cast("type[PrinterModel]", QL820NWBDriver))
