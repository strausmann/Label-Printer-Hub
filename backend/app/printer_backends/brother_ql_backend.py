"""Phase 1i Sub-Task G: BrotherQLBackend.

C1-Fix: brother_ql v0.9.4 API (convert + helpers.send).
C8-Fix: model bleibt "QL-820NWB" (library kennt kein "c"-Suffix).
M6-Fix: red=False für Monochrome auf two_color=True Library-Modellen.
R3-Zusatz: helpers.send ist synchron mit blocking=True -> asyncio.to_thread wrapping.
"""

from __future__ import annotations

import asyncio
import logging

# Must run before brother_ql is used: restores Image.ANTIALIAS (removed in Pillow 10),
# which brother_ql 0.9.x calls in its resize branch. See _pillow_compat and issue #254.
from app.printer_backends import _pillow_compat  # noqa: F401  # isort: skip
from brother_ql.backends.helpers import (
    send as _helpers_send,
)
from brother_ql.conversion import convert
from brother_ql.labels import ALL_LABELS
from brother_ql.raster import BrotherQLRaster
from PIL import Image

from app.models.tape import TapeSpec
from app.printer_backends.batch_helper import default_print_images_loop
from app.printer_backends.exceptions import (
    PrinterCoverOpenError,
    PrinterOfflineError,
    PrintFailedError,
    TapeEmptyError,
)
from app.printer_backends.snmp_helper import (
    PreflightStatus,
    SnmpQueryError,
    query_preflight,
)
from app.schemas.label_layout import LabelOrientation
from app.services.status_block import StatusBlock

_logger = logging.getLogger(__name__)

# Mapping from tape width (mm) to brother_ql label identifier string.
# Only endless (continuous-length) DK labels are listed here; die-cut
# label support can be added in a future phase.
_TAPE_MM_TO_QL_LABEL: dict[int, str] = {
    12: "12",
    29: "29",
    38: "38",
    50: "50",
    54: "54",
    62: "62",
}


def _fit_to_printable_width(
    image: Image.Image,
    ql_label: str,
    *,
    dpi_600: bool,
    orientation: LabelOrientation | None = None,
) -> Image.Image:
    """Prepare *image* so ``brother_ql.convert`` never has to resize it (issues #254, #258).

    ``convert`` wants, for endless labels, an image whose *width* equals the label's
    ``dots_printable[0]`` (rows span the tape; the image grows along the feed direction).

    1. Orientation (#258): the renderer says how the image is laid out.
       - ``across``: the image is already in convert's orientation (rows span the tape) and
         is never rotated.
       - ``along``: the image is a landscape band (PT convention: height = band across the
         tape, width = label length) and is always rotated 90 degrees clockwise, so the left
         edge (start of text) becomes row 0 and is printed first.
       - no flag (an image from a caller that predates #258): the 1.4.1 size heuristic stays
         as a safety net. An image whose height does not exceed the printable width is taken
         as a band and rotated; one whose width already equals the printable width is taken
         as ready-made. The heuristic is ambiguous for images narrower than the tape (a
         500x300 across image on 62 mm would be rotated by mistake), hence the flag.
    2. An image narrower than the printable width is centred on white padding, never
       stretched.
    3. With ``dpi_600`` convert halves the width again before checking it, so the 300 dpi
       source is doubled on both axes (same physical size, printed at 600 dpi).

    Anything still wider than the printable width is left alone: convert's own resize
    fallback handles (and logs) it.
    """
    matches = [x for x in ALL_LABELS if x.identifier == ql_label]
    if not matches:
        return image
    printable = int(matches[0].dots_printable[0])

    if image.mode not in ("1", "L", "RGB", "RGBA"):
        image = image.convert("RGB")
    if orientation is None:
        rotate = image.height <= printable and image.width != printable
    else:
        rotate = orientation is LabelOrientation.ALONG
    if rotate:
        image = image.transpose(Image.Transpose.ROTATE_270)
    if image.width < printable:
        padded = Image.new(image.mode, (printable, image.height), (255,) * len(image.mode))
        padded.paste(image, ((printable - image.width) // 2, 0))
        image = padded
    if dpi_600:
        image = image.resize((image.width * 2, image.height * 2), Image.Resampling.NEAREST)
    return image


class BrotherQLBackend:
    """PrinterBackend backed by the brother_ql library (v0.9.x).

    Wraps the synchronous ``brother_ql.backends.helpers.send`` in
    ``asyncio.to_thread`` so the async caller is not blocked.
    """

    backend_id = "brother_ql"
    half_cut_supported: bool = False

    def __init__(self, host: str, *, port: int = 9100, model_id: str = "QL-820NWB") -> None:
        if not host:
            raise ValueError("BrotherQLBackend requires a non-empty host")
        self.host = host
        self._port = port
        self._model_id = model_id
        self._identifier = f"tcp://{host}:{port}"

    async def print_image(
        self,
        image: Image.Image,
        tape_spec: TapeSpec,
        *,
        auto_cut: bool = True,
        high_resolution: bool = False,
        half_cut: bool = False,
        last_page: bool = True,  # noqa: ARG002
        orientation: LabelOrientation | None = None,
    ) -> None:
        """Convert *image* to QL raster data and send to the printer.

        ``half_cut`` is silently ignored with a WARNING — QL-Series hardware
        does not support half-cut (PT-Series only).
        ``high_resolution`` is passed through as ``dpi_600`` to ``convert``.
        ``last_page`` is accepted for protocol compatibility but has no effect
        on the QL wire format (cut is controlled by the ``cut`` kwarg in
        ``convert``).
        ``orientation`` (#258) decides the rotation: ``along`` rotates, ``across`` never
        does, ``None`` falls back to the 1.4.1 size heuristic.
        """
        if half_cut:
            _logger.warning(
                "BrotherQLBackend(host=%s): half_cut=True requested but QL-Series "
                "does not support half-cut — ignoring (using full-cut only).",
                self.host,
            )

        try:
            ql_label = _TAPE_MM_TO_QL_LABEL[tape_spec.width_mm]
        except KeyError as exc:
            raise PrintFailedError(
                f"No QL label mapping for {tape_spec.width_mm}mm — "
                f"supported widths: {sorted(_TAPE_MM_TO_QL_LABEL)}"
            ) from exc

        # Build raster instructions. convert() populates qlr.data.
        # M6-Fix: red=False for monochrome; two_color capable models (QL-820NWB)
        # accept this without error — they only require red=False not to raise.
        qlr = BrotherQLRaster(self._model_id)
        image = _fit_to_printable_width(
            image, ql_label, dpi_600=high_resolution, orientation=orientation
        )
        convert(
            qlr,
            [image],
            ql_label,
            cut=auto_cut,
            red=False,
            dpi_600=high_resolution,
        )

        # _helpers_send is synchronous and performs blocking I/O.
        # Wrap in to_thread to avoid blocking the event loop.
        await asyncio.to_thread(
            _helpers_send,
            qlr.data,
            self._identifier,
            blocking=True,
        )

    async def print_images(
        self,
        images: list[Image.Image],
        tape_spec: TapeSpec,
        *,
        auto_cut: bool = True,
        high_resolution: bool = False,
        half_cut: bool = True,  # noqa: ARG002
        orientation: LabelOrientation | None = None,
    ) -> None:
        """Batch-print N images via per-item Loop.

        brother_ql Lib hat kein print_multi-Equivalent — QL ist Endless-Tape,
        kein Half-Cut-Konzept zwischen Labels (jedes Label wird vom Druckkopf
        ausgegeben und manuell abgeschnitten). Delegiert an
        default_print_images_loop mit half_cut=False (QL ignoriert das Argument).
        ``orientation`` (#258) applies to every image of the batch.
        """
        # QL-Series: half_cut existiert nicht. Backend-Capability-Flag erzwingt False.
        await default_print_images_loop(
            self,
            images,
            tape_spec,
            auto_cut=auto_cut,
            high_resolution=high_resolution,
            half_cut=False,
            orientation=orientation,
        )

    async def preflight_check(
        self,
        *,
        community: str = "public",
        timeout_s: float = 3.0,
    ) -> PreflightStatus:
        """SNMP-based preflight: hrPrinterStatus + error bitmap + loaded tape.

        QL-820NWB nutzt dieselbe Printer MIB wie PT-Series — query_preflight()
        funktioniert identisch auf beiden Gerätereihen.

        Raises:
            PrinterOfflineError: SNMP query failed (host unreachable or timeout)
            TapeEmptyError: hrPrinterDetectedErrorState has noPaper bit
            PrinterCoverOpenError: hrPrinterDetectedErrorState has doorOpen bit

        Does NOT raise TapeMismatchError — caller compares loaded_tape_mm.
        """
        try:
            preflight = await query_preflight(
                self.host,
                community=community,
                timeout_s=timeout_s,
            )
        except SnmpQueryError as exc:
            # Issue #105: query_preflight() kann bereits "preflight SNMP failed: …"
            # im SnmpQueryError enthalten — doppeltes Prefixen vermeiden.
            msg = str(exc)
            if not msg.startswith("preflight SNMP failed:"):
                msg = f"preflight SNMP failed: {msg}"
            raise PrinterOfflineError(msg) from exc

        if "noPaper" in preflight.error_flags:
            raise TapeEmptyError()
        if "doorOpen" in preflight.error_flags:
            raise PrinterCoverOpenError()
        return preflight

    async def query_status(self) -> StatusBlock:
        """QL-Series uses SNMP-Probe via StatusProbeProducer, no synchronous path.

        Full implementation deferred to Phase 1j (SNMP status for QL-Series).
        """
        raise NotImplementedError(
            "BrotherQLBackend.query_status: QL-Series uses SNMP-Probe via "
            "StatusProbeProducer, no synchronous status path in Phase 1i."
        )
