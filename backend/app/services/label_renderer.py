"""Compose a 1-bit PIL Image from a TemplateSchema + LabelData.

The renderer is stateless — one instance can serve concurrent requests.
It does not know the printer or the queue; it only produces the bitmap.
The printer-backend plug-in (Phase 2 hardware tasks) converts the bitmap
to raster bytes for the specific Brother model.

Coordinate system: top-left origin, pixels at 300 DPI (brother_ql native).
The print area is constrained by Brother's per-tape geometry tables —
see `TAPE_HEIGHT_PX` for the supported widths.
"""

from __future__ import annotations

from typing import Final

import qrcode
import qrcode.constants
from PIL import Image, ImageDraw, ImageFont

from app.schemas.label_data import LabelData
from app.schemas.template import LayoutElement, TemplateSchema

# Tape-mm to printable-area pixel-height at 300 DPI (brother_ql native).
# Source: Brother Raster Command Reference v1.02. Extend as new tape widths
# are supported by the printer-model plugins.
TAPE_HEIGHT_PX: Final[dict[int, int]] = {
    12: 106,
    18: 165,
    24: 256,
    62: 696,  # endless QL tape
}

# Default label width in pixels — wide enough for typical asset/product labels.
# Real width is set later by the print job based on actual rendered content;
# this is just the canvas the renderer paints on.
DEFAULT_LABEL_WIDTH_PX: Final[int] = 600


class LabelRenderer:
    """Render a (LabelData, TemplateSchema) pair into a 1-bit PIL Image."""

    def render(self, data: LabelData, template: TemplateSchema) -> Image.Image:
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

        return img

    def _draw_qr(self, img: Image.Image, element: LayoutElement, data: LabelData) -> None:
        # Validation in LayoutElement.model_validator guarantees these are not None for type="qr".
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
        assert element.field is not None
        assert element.font_size is not None

        text = self._resolve_field(data, element.field)
        font = self._load_font(element.font_size)
        draw.text((element.x, element.y), text, fill=0, font=font)

    @staticmethod
    def _resolve_field(data: LabelData, field: str) -> str:
        """Read `field` off `data`, coercing tuples/lists to a single ' | '-joined string."""
        value = getattr(data, field, "")
        if isinstance(value, (list, tuple)):
            return " | ".join(str(v) for v in value)
        return str(value)

    @staticmethod
    def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        """Load DejaVuSans at `size`px, fall back to PIL's bitmap default if unavailable."""
        try:
            return ImageFont.truetype("DejaVuSans.ttf", size)
        except OSError:
            return ImageFont.load_default()
