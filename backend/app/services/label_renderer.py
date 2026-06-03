"""Compose a 1-bit PIL Image from a TemplateSchema + LabelData.

The renderer is stateless — one instance can serve concurrent requests.
It does not know the printer or the queue; it only produces the bitmap.
The printer-backend plug-in (Phase 2 hardware tasks) converts the bitmap
to raster bytes for the specific Brother model.

Coordinate system: top-left origin, pixels at ptouch native 180 DPI.
The print area is constrained by the physical print_pins of the
PT-P750W per tape width — see `TAPE_HEIGHT_PX` for the supported widths.

A-Diagnose (2026-06-02): previous values (12:106, 18:165, 24:256) were
derived from a brother_ql / 300 DPI geometry and caused 1.5x–2x canvas
overflow. ptouch._prepare_image() crops to print_pins on paste, silently
clipping QR and text elements at the top. Fixed to match ptouch PIN_CONFIGS
print_pins values at 180 DPI. QL 62mm Endless tape is unaffected.
"""

from __future__ import annotations

import functools
from typing import Final

import qrcode
import qrcode.constants
from PIL import Image, ImageChops, ImageDraw, ImageFont

from app.schemas.label_data import LabelData
from app.schemas.template import LayoutElement, TemplateSchema

# Tape-mm to printable-area pixel-height — matched to ptouch PT-P750W
# PIN_CONFIGS.print_pins values at native 180 DPI.
# Source: ptouch-py PIN_CONFIGS (Tape12mm=70, Tape18mm=112, Tape24mm=128).
# QL 62mm Endless tape uses brother_ql geometry and is unchanged.
TAPE_HEIGHT_PX: Final[dict[int, int]] = {
    12: 70,   # PT-P750W Tape12mm print_pins (was 106 — 1.51x overflow)
    18: 112,  # PT-P750W Tape18mm print_pins (was 165 — 1.47x overflow)
    24: 128,  # PT-P750W Tape24mm print_pins (was 256 — 2.00x overflow)
    62: 696,  # endless QL tape — unchanged
}

# Default label width in pixels — 600 px at 300 DPI ≈ 50.8mm, suitable for
# typical asset/product label lengths. The actual width the printer receives
# is determined by the print job; this is just the canvas the renderer
# paints on.
DEFAULT_LABEL_WIDTH_PX: Final[int] = 600

# Margin around the inked content when trimming whitespace on the length
# axis. 6 px ≈ 1mm at 180 DPI / 0.5mm at 300 DPI — minimal padding so
# QR scan and the printer cutter both work.
_TRIM_MARGIN_PX: Final[int] = 6


@functools.lru_cache(maxsize=32)
def _load_font_cached(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load DejaVuSans at `size`px (cached), fall back to PIL's bitmap default if unavailable.

    The cache is bounded at 32 entries — far more than any realistic template uses.
    Repeated calls with the same size return the same font instance without disk I/O.
    """
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


class LabelRenderer:
    """Render a (TemplateSchema, LabelData) pair into a 1-bit PIL Image."""

    def render(self, template: TemplateSchema, data: LabelData) -> Image.Image:
        """Return a 1-bit image sized for the template's tape width.

        Raises:
            ValueError: if `template.tape_mm` is not in TAPE_HEIGHT_PX.
        """
        height = TAPE_HEIGHT_PX.get(template.tape_mm)
        if height is None:
            raise ValueError(
                f"Unsupported tape_mm: {template.tape_mm}. "
                f"Supported widths: {sorted(TAPE_HEIGHT_PX)}"
            )

        img = Image.new("1", (DEFAULT_LABEL_WIDTH_PX, height), color=1)
        draw = ImageDraw.Draw(img)

        for element in template.elements:
            if element.type == "qr":
                self._draw_qr(img, element, data)
            else:  # element.type == "text"
                self._draw_text(draw, element, data)

        # Crop to the inked area on the length axis only — the height (tape
        # axis) is pin-locked by the printer geometry and must not change.
        # `img.getbbox()` would return the bbox of non-zero pixels, but mode "1"
        # uses 1 for white (the background) and 0 for ink, so we invert first.
        ink_bbox = ImageChops.invert(img.convert("L")).getbbox()
        if ink_bbox is not None:
            left, _, right, _ = ink_bbox
            new_left = max(0, left - _TRIM_MARGIN_PX)
            new_right = min(img.width, right + _TRIM_MARGIN_PX)
            img = img.crop((new_left, 0, new_right, height))

        return img

    def _draw_qr(self, img: Image.Image, element: LayoutElement, data: LabelData) -> None:
        # LayoutElement.model_validator guarantees these are non-None for type="qr".
        # The asserts document the invariant for readers and mypy; they are NOT
        # runtime guards (python -O strips them).
        assert element.data_field is not None
        assert element.size is not None

        payload = self._resolve_field(data, element.data_field)
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=4,
            border=1,
        )
        qr.add_data(payload)
        qr.make(fit=True)
        qr_pil: Image.Image = qr.make_image(fill_color="black", back_color="white").convert("1")
        qr_pil = qr_pil.resize((element.size, element.size))
        img.paste(qr_pil, (element.x, element.y))

    def _draw_text(
        self,
        draw: ImageDraw.ImageDraw,
        element: LayoutElement,
        data: LabelData,
    ) -> None:
        # LayoutElement.model_validator guarantees these are non-None for type="text".
        # The asserts document the invariant for readers and mypy; they are NOT
        # runtime guards (python -O strips them).
        assert element.field is not None
        assert element.font_size is not None

        text = self._resolve_field(data, element.field)
        font = _load_font_cached(element.font_size)
        draw.text((element.x, element.y), text, fill=0, font=font)

    @staticmethod
    def _resolve_field(data: LabelData, field: str) -> str:
        """Read `field` off `data`, coercing tuples/lists to a single ' | '-joined string."""
        value = getattr(data, field, "")
        if isinstance(value, (list, tuple)):
            # Separator " | " chosen for single-line tape labels. If a future phase
            # adds multi-line text fields, this should become a per-element
            # `separator` attribute on LayoutElement.
            return " | ".join(str(v) for v in value)
        return str(value)
