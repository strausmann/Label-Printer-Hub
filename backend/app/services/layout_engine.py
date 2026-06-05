"""LayoutEngine — semantic layout rendering driven by ContentType + TapeGeometry.

Replaces the v1 LabelRenderer. Each render() call resolves:
  1. tape_mm -> TapeGeometry (via TAPE_GEOMETRY dict)
  2. content_type-required fields -> validated against LabelData
  3. Dispatched to a per-ContentType _render_*() method
  4. Returns a PIL Image whose height matches geometry.printable_px

The _render_*() methods are implemented in subsequent tasks (7-13).
"""

from __future__ import annotations

from typing import ClassVar

import qrcode
import qrcode.constants
from PIL import Image, ImageDraw, ImageFont

from app.printer_backends.exceptions import (
    ContentTypeDataMismatchError,
    UnsupportedTapeError,
)
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.schemas.tape_geometry import TAPE_GEOMETRY, TapeGeometry


class LayoutEngine:
    """Tape-independent semantic label renderer.

    Stateless — safe to instantiate once and reuse across requests.
    """

    _REQUIRED_FIELDS: ClassVar[dict[ContentType, tuple[str, ...]]] = {
        ContentType.QR_ONLY: ("qr_payload",),
        ContentType.QR_ONE_LINE: ("qr_payload", "primary_id"),
        ContentType.QR_TWO_LINES: ("qr_payload", "primary_id", "title"),
        ContentType.QR_THREE_LINES: ("qr_payload", "primary_id", "title", "secondary"),
        ContentType.TEXT_ONE_LINE: ("primary_id",),
        ContentType.TEXT_TWO_LINES: ("primary_id", "title"),
        ContentType.QR_WITH_LISTING: ("qr_payload", "primary_id", "items"),
    }
    """ContentType -> ordered tuple of LabelData field names that must be set.

    Used by _validate_data to produce ContentTypeDataMismatchError with a
    complete missing-fields list (one 422 instead of multiple round-trips).
    """

    def render(
        self,
        tape_mm: int,
        content_type: ContentType,
        data: LabelData,
    ) -> Image.Image:
        """Render a label for the given tape width + content type + data.

        Raises:
            UnsupportedTapeError (409): tape_mm not in TAPE_GEOMETRY.
            ContentTypeDataMismatchError (422): data missing required fields.
        """
        geometry = self._lookup_geometry(tape_mm)
        self._validate_data(content_type, data)

        match content_type:
            case ContentType.QR_ONLY:
                return self._render_qr_only(geometry, data)
            case ContentType.QR_ONE_LINE:
                return self._render_qr_one_line(geometry, data)
            case ContentType.QR_TWO_LINES:
                return self._render_qr_two_lines(geometry, data)
            case ContentType.QR_THREE_LINES:
                return self._render_qr_three_lines(geometry, data)
            case ContentType.TEXT_ONE_LINE:
                return self._render_text_one_line(geometry, data)
            case ContentType.TEXT_TWO_LINES:
                return self._render_text_two_lines(geometry, data)
            case ContentType.QR_WITH_LISTING:
                return self._render_qr_with_listing(geometry, data)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _lookup_geometry(self, tape_mm: int) -> TapeGeometry:
        geom = TAPE_GEOMETRY.get(tape_mm)
        if geom is None:
            raise UnsupportedTapeError(tape_mm=tape_mm)
        return geom

    def _validate_data(self, content_type: ContentType, data: LabelData) -> None:
        required = self._REQUIRED_FIELDS[content_type]
        missing: list[str] = []
        for field_name in required:
            value = getattr(data, field_name)
            # Empty string, empty tuple, or None counts as missing.
            if value is None or (hasattr(value, "__len__") and len(value) == 0):
                missing.append(field_name)
        if missing:
            raise ContentTypeDataMismatchError(
                content_type=str(content_type),
                missing_fields=tuple(missing),
            )

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_qr_image(payload: str, size_px: int) -> Image.Image:
        """Render a QR code as a square 1-bit PIL Image at the requested size."""
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=0,
        )
        qr.add_data(payload)
        qr.make(fit=True)
        rendered: Image.Image = qr.make_image(fill_color="black", back_color="white").convert("1")
        return rendered.resize((size_px, size_px), Image.Resampling.NEAREST)

    @staticmethod
    def _blank_canvas(width: int, height: int) -> Image.Image:
        """Return a white 1-bit PIL Image of the given size."""
        return Image.new("1", (width, height), color=1)

    @staticmethod
    def _load_font(size_px: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
        """Load DejaVuSans TrueType font at the requested pixel size.

        DejaVuSans.ttf is installed via fonts-dejavu-core in the Dockerfile.
        On dev machines without the system font, falls back to the default
        bitmap font.
        """
        try:
            return ImageFont.truetype("DejaVuSans.ttf", size_px)
        except OSError:
            return ImageFont.load_default()

    @staticmethod
    def _measure_text(
        text: str,
        font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
    ) -> tuple[int, int]:
        """Return (width, height) bounding box of `text` rendered with `font`."""
        bbox = ImageDraw.Draw(Image.new("1", (1, 1), color=1)).textbbox((0, 0), text, font=font)
        return (int(bbox[2] - bbox[0]), int(bbox[3] - bbox[1]))

    # ------------------------------------------------------------------
    # _render_* methods — implemented in Tasks 7-13
    # ------------------------------------------------------------------

    def _render_qr_only(
        self,
        geometry: TapeGeometry,
        data: LabelData,
    ) -> Image.Image:
        """QR fills the full printable height, left-padded by qr_padding_px.

        Width = qr_max_px + 2 * qr_padding_px = printable_px (square label).
        """
        qr_img = self._build_qr_image(
            payload=data.qr_payload or "",
            size_px=geometry.qr_max_px,
        )
        canvas_width = geometry.printable_px
        canvas = self._blank_canvas(canvas_width, geometry.printable_px)
        canvas.paste(qr_img, (geometry.qr_padding_px, geometry.qr_padding_px))
        return canvas

    def _render_qr_one_line(
        self,
        geometry: TapeGeometry,
        data: LabelData,
    ) -> Image.Image:
        """QR left + 1 text line (primary_id, font_xl, vertically centered)."""
        qr_img = self._build_qr_image(
            payload=data.qr_payload or "",
            size_px=geometry.qr_max_px,
        )
        font = self._load_font(geometry.font_xl)
        text = data.primary_id or ""
        text_w, text_h = self._measure_text(text, font)

        canvas_width = geometry.text_start_x + text_w + geometry.qr_padding_px
        canvas = self._blank_canvas(canvas_width, geometry.printable_px)
        canvas.paste(qr_img, (geometry.qr_padding_px, geometry.qr_padding_px))
        text_y = max(0, (geometry.printable_px - text_h) // 2)
        ImageDraw.Draw(canvas).text((geometry.text_start_x, text_y), text, font=font, fill=0)
        return canvas

    def _render_qr_two_lines(
        self,
        geometry: TapeGeometry,
        data: LabelData,
    ) -> Image.Image:
        """QR left + 2 text lines (primary_id XL on top, title L below).

        Phase 1i V4-Winner baseline for 12mm:
          - primary_id at y=2 (font_xl=22)
          - title at y=42 (font_l=18)
          - text_start_x=72
        Generalises to other tape widths via geometry constants.
        """
        qr_img = self._build_qr_image(
            payload=data.qr_payload or "",
            size_px=geometry.qr_max_px,
        )
        font_primary = self._load_font(geometry.font_xl)
        font_title = self._load_font(geometry.font_l)

        primary_text = data.primary_id or ""
        title_text = data.title or ""
        primary_w, _ = self._measure_text(primary_text, font_primary)
        title_w, _ = self._measure_text(title_text, font_title)
        max_text_w = max(primary_w, title_w)

        canvas_width = geometry.text_start_x + max_text_w + geometry.qr_padding_px
        canvas = self._blank_canvas(canvas_width, geometry.printable_px)
        canvas.paste(qr_img, (geometry.qr_padding_px, geometry.qr_padding_px))

        draw = ImageDraw.Draw(canvas)
        draw.text(
            (geometry.text_start_x, geometry.qr_padding_px),
            primary_text,
            font=font_primary,
            fill=0,
        )
        title_y = geometry.qr_padding_px + geometry.font_xl + geometry.line_spacing_px
        draw.text(
            (geometry.text_start_x, title_y),
            title_text,
            font=font_title,
            fill=0,
        )
        return canvas

    def _render_qr_three_lines(
        self,
        geometry: TapeGeometry,
        data: LabelData,
    ) -> Image.Image:
        """QR left + 3 text lines: primary_id XL, title L, secondary[0] S."""
        qr_img = self._build_qr_image(
            payload=data.qr_payload or "",
            size_px=geometry.qr_max_px,
        )
        font_primary = self._load_font(geometry.font_xl)
        font_title = self._load_font(geometry.font_l)
        font_secondary = self._load_font(geometry.font_s)

        primary_text = data.primary_id or ""
        title_text = data.title or ""
        secondary_text = data.secondary[0] if data.secondary else ""

        primary_w, _ = self._measure_text(primary_text, font_primary)
        title_w, _ = self._measure_text(title_text, font_title)
        sec_w, _ = self._measure_text(secondary_text, font_secondary)
        max_text_w = max(primary_w, title_w, sec_w)

        canvas_width = geometry.text_start_x + max_text_w + geometry.qr_padding_px
        canvas = self._blank_canvas(canvas_width, geometry.printable_px)
        canvas.paste(qr_img, (geometry.qr_padding_px, geometry.qr_padding_px))

        draw = ImageDraw.Draw(canvas)
        y = geometry.qr_padding_px
        draw.text(
            (geometry.text_start_x, y),
            primary_text,
            font=font_primary,
            fill=0,
        )
        y += geometry.font_xl + geometry.line_spacing_px
        draw.text(
            (geometry.text_start_x, y),
            title_text,
            font=font_title,
            fill=0,
        )
        y += geometry.font_l + geometry.line_spacing_px
        draw.text(
            (geometry.text_start_x, y),
            secondary_text,
            font=font_secondary,
            fill=0,
        )
        return canvas

    def _render_text_one_line(
        self,
        geometry: TapeGeometry,
        data: LabelData,
    ) -> Image.Image:
        """Full-width text (primary_id, font_xl, vertically centered)."""
        font = self._load_font(geometry.font_xl)
        text = data.primary_id or ""
        text_w, text_h = self._measure_text(text, font)

        canvas_width = geometry.qr_padding_px + text_w + geometry.qr_padding_px
        canvas = self._blank_canvas(canvas_width, geometry.printable_px)
        text_y = max(0, (geometry.printable_px - text_h) // 2)
        ImageDraw.Draw(canvas).text(
            (geometry.qr_padding_px, text_y),
            text,
            font=font,
            fill=0,
        )
        return canvas

    def _render_text_two_lines(
        self,
        geometry: TapeGeometry,
        data: LabelData,
    ) -> Image.Image:
        """2 text lines (primary_id XL + title L), no QR."""
        font_primary = self._load_font(geometry.font_xl)
        font_title = self._load_font(geometry.font_l)
        primary_text = data.primary_id or ""
        title_text = data.title or ""
        primary_w, _ = self._measure_text(primary_text, font_primary)
        title_w, _ = self._measure_text(title_text, font_title)
        max_text_w = max(primary_w, title_w)

        canvas_width = geometry.qr_padding_px + max_text_w + geometry.qr_padding_px
        canvas = self._blank_canvas(canvas_width, geometry.printable_px)

        draw = ImageDraw.Draw(canvas)
        y = geometry.qr_padding_px
        draw.text(
            (geometry.qr_padding_px, y),
            primary_text,
            font=font_primary,
            fill=0,
        )
        y += geometry.font_xl + geometry.line_spacing_px
        draw.text(
            (geometry.qr_padding_px, y),
            title_text,
            font=font_title,
            fill=0,
        )
        return canvas

    def _render_qr_with_listing(
        self,
        geometry: TapeGeometry,
        data: LabelData,
    ) -> Image.Image:
        """QR left + N item lines (font_m). Overflow shows '+N more'."""
        qr_img = self._build_qr_image(
            payload=data.qr_payload or "",
            size_px=geometry.qr_max_px,
        )
        font_item = self._load_font(geometry.font_m)
        items = list(data.items)

        available_h = geometry.printable_px - 2 * geometry.qr_padding_px
        line_h = geometry.font_m + geometry.line_spacing_px
        max_lines = max(1, available_h // line_h)

        overflow_text: str | None
        if len(items) > max_lines:
            visible_count = max_lines - 1
            overflow_text = f"+{len(items) - visible_count} more"
            visible = items[:visible_count]
        else:
            visible = items
            overflow_text = None

        widths = [self._measure_text(it.item, font_item)[0] for it in visible]
        if overflow_text:
            widths.append(self._measure_text(overflow_text, font_item)[0])
        max_text_w = max(widths) if widths else 0

        canvas_width = geometry.text_start_x + max_text_w + geometry.qr_padding_px
        canvas = self._blank_canvas(canvas_width, geometry.printable_px)
        canvas.paste(qr_img, (geometry.qr_padding_px, geometry.qr_padding_px))

        draw = ImageDraw.Draw(canvas)
        y = geometry.qr_padding_px
        for it in visible:
            draw.text(
                (geometry.text_start_x, y),
                it.item,
                font=font_item,
                fill=0,
            )
            y += line_h
        if overflow_text:
            draw.text(
                (geometry.text_start_x, y),
                overflow_text,
                font=font_item,
                fill=0,
            )
        return canvas
