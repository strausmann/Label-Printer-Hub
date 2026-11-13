"""Cell renderer: draws one label into one sheet cell (spec 12.1 and 12.3).

The renderer is a small protocol, separate from the tape ``LayoutEngine``, so that the sheet
code never depends on how a cell is drawn (the hook for #178). ``DEFAULT_CELL_RENDERER`` is the
single place a better implementation is swapped in.

Rules every implementation follows (spec 12.3):

* same content types and required fields as the tape engine (``REQUIRED_FIELDS``), one
  ``ContentTypeDataMismatchError`` for missing fields;
* QR module size a whole number of device pixels, a quiet zone of four modules inside the box;
* text shrinks down to a minimum cap height of 1.6 mm (OC-27), then is shortened with an
  ellipsis and flagged ``truncated``;
* nothing is drawn outside the box.

Deviation from the spec's implementation hint ("reuses the existing QR generation"): the tape
builder ``LayoutEngine._build_qr_image`` renders with ``border=0`` and a ``NEAREST`` resize, so
modules are not whole device pixels and there is no quiet zone. ``build_qr`` here follows the
rules of 12.3 instead; the tape path is untouched.

Stable names for Task 7's pre-check before anything is reserved: ``REQUIRED_FIELDS`` (re-exported
from ``app.services.layout_engine``), ``map_content_type`` and ``build_qr``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Final, Protocol

import qrcode
import qrcode.constants
import qrcode.exceptions
from PIL import Image, ImageDraw, ImageFont

from app.page_render.pdf import resolve_font_path
from app.printer_backends.exceptions import ContentTypeDataMismatchError
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.services.layout_engine import REQUIRED_FIELDS
from app.sheets.geometry import Geometry, cell_origin
from app.sheets.text import sanitise_text

__all__ = [
    "DEFAULT_CELL_RENDERER",
    "MAX_QR_CHARS",
    "MIN_CAP_HEIGHT_MM",
    "PREVIEW_QR_MASK",
    "REQUIRED_FIELDS",
    "BoxHmm",
    "CellImage",
    "CellRenderer",
    "QrDoesNotFitError",
    "RasterCellRenderer",
    "box_fits_a_line",
    "build_qr",
    "build_qr_preview",
    "cap_height_px",
    "check_required",
    "content_box",
    "load_cell_font",
    "map_content_type",
    "min_font_px",
    "qr_edge_px",
    "qr_fits",
    "qr_version",
]

MIN_CAP_HEIGHT_MM: Final = 1.6
"""Smallest text cap height (OC-27); below it text is shortened instead of shrunk."""

_BASE_INSET_HMM: Final = 100  # 1.0 mm
_UNKNOWN_RADIUS_INSET_HMM: Final = 160  # unknown radius counts as 2.0 mm: 1.0 + 0.3 * 2.0
_RADIUS_FACTOR: Final = 0.3
_QUIET_MODULES: Final = 4
_ELLIPSIS: Final = "…"
_MAX_TEXT_CHARS: Final = 2000  # input is cut before any measuring (hostile 10 000-char titles)

_MAPPED_WITHOUT_QR: Final[dict[ContentType, ContentType]] = {
    ContentType.QR_ONLY: ContentType.TEXT_ONE_LINE,
    ContentType.QR_ONE_LINE: ContentType.TEXT_ONE_LINE,
    ContentType.QR_TWO_LINES: ContentType.TEXT_TWO_LINES,
    ContentType.QR_THREE_LINES: ContentType.TEXT_TWO_LINES,
    ContentType.QR_WITH_LISTING: ContentType.TEXT_TWO_LINES,
}

# Font sizes (em, in px) as fractions of the box height; the cap height is about 0.73 em.
_FRACTIONS: Final[dict[ContentType, tuple[float, ...]]] = {
    ContentType.QR_ONLY: (),
    ContentType.QR_ONE_LINE: (0.50,),
    ContentType.TEXT_ONE_LINE: (0.55,),
    ContentType.QR_TWO_LINES: (0.38, 0.27),
    ContentType.TEXT_TWO_LINES: (0.40, 0.28),
    ContentType.QR_THREE_LINES: (0.30, 0.22, 0.17),
    ContentType.QR_WITH_LISTING: (0.26,),
}
_LISTING_ITEM_FRACTION: Final = 0.17
_LINE_GAP_EM: Final = 0.30  # space between lines, in em
_DESCENT_EM: Final = 0.25  # room under the baseline for descenders


class QrDoesNotFitError(ContentTypeDataMismatchError):
    """The QR payload is present but too large for the box (module < 1 px, or no QR holds it).

    Still a ``ContentTypeDataMismatchError`` with ``missing_fields=("qr_payload",)`` so the 422
    envelope and existing callers are unchanged, but the message does not ask to populate it.
    """

    def __init__(self, *, content_type: str) -> None:
        super().__init__(content_type=content_type, missing_fields=("qr_payload",))
        self.args = (
            f"ContentType '{content_type}': qr_payload is too long to fit a QR code into the "
            f"cell (it does not fit with modules of at least one device pixel) - shorten it "
            f"or use a larger label type.",
        )


@dataclass(frozen=True)
class BoxHmm:
    """Content box on the page, in hundredths of a millimetre."""

    x: int
    y: int
    w: int
    h: int


def content_box(g: Geometry, n: int) -> BoxHmm:
    """Content box of cell ``n`` (OC-25).

    Rectangles are inset by ``1.0 mm + 0.3 x corner_radius`` per side (unknown radius counts as
    2.0 mm, inset 1.6 mm); round cells use the square inscribed in the circle, inset by 1.0 mm,
    centred in the cell.
    """
    ox, oy = cell_origin(g, n)
    if g.shape == "round":
        side = max(0, round(g.label_w / math.sqrt(2)) - 2 * _BASE_INSET_HMM)
        return BoxHmm(ox + (g.label_w - side) // 2, oy + (g.label_h - side) // 2, side, side)
    inset = (
        _UNKNOWN_RADIUS_INSET_HMM
        if g.corner_radius is None
        else _BASE_INSET_HMM + round(_RADIUS_FACTOR * g.corner_radius)
    )
    # A label no larger than twice its inset has no room inside: an empty box, never a negative
    # one (``box_fits_a_line`` then refuses it).
    return BoxHmm(
        ox + inset, oy + inset, max(0, g.label_w - 2 * inset), max(0, g.label_h - 2 * inset)
    )


def box_fits_a_line(box: BoxHmm) -> bool:
    """Whether a content box can hold anything: both sides reach the minimum cap height.

    Below that not even one line of text is legible, and a QR would be smaller than a letter.
    ``check_item_fits`` refuses such an item before anything is reserved, and the renderer
    refuses to draw into one.
    """
    minimum = round(MIN_CAP_HEIGHT_MM * 100)
    return box.w >= minimum and box.h >= minimum


def map_content_type(ct: ContentType, allow_qr: bool) -> tuple[ContentType, bool]:
    """Content type to draw on a type with ``allow_qr``, and whether it was mapped (spec 12.5)."""
    if allow_qr:
        return ct, False
    mapped = _MAPPED_WITHOUT_QR.get(ct, ct)
    return mapped, mapped is not ct


MAX_QR_CHARS: Final = 4296  # the most any QR symbol holds; a longer payload can never fit


def qr_version(payload: str) -> int | None:
    """The QR version ``make(fit=True)`` would pick for ``payload`` (error correction M), or
    ``None`` if no symbol holds it. A payload longer than ``MAX_QR_CHARS`` is answered here and
    never reaches the cache, so every cache key is at most that long."""
    if len(payload) > MAX_QR_CHARS:
        return None
    return _qr_version_cached(payload)


@lru_cache(maxsize=512)
def _qr_version_cached(payload: str) -> int | None:
    """Cached; the size search is the first of the two encodings a symbol costs, and the
    preview asks it twice (can it be drawn, then draw it). It is ``best_fit`` alone, which is
    what ``make(fit=True)`` starts with, so the version is exactly the library's."""
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0)
    try:
        qr.add_data(payload)
        return int(qr.best_fit())
    except (qrcode.exceptions.DataOverflowError, ValueError):
        return None


PREVIEW_QR_MASK: Final = 0
"""The mask the preview passes to ``build_qr`` and ``build_qr_preview`` instead of searching the
best of eight (a picture does not need the best mask, and the search is most of the cost of a
QR). A job passes none, so what is printed keeps the best mask. 266-08: passed explicitly, no
process-wide state."""


def _qr_matrix(payload: str, mask: int | None) -> list[list[bool]] | None:
    """The module matrix of the symbol, quiet zone included; ``None`` if no QR holds it.
    ``mask``: the mask pattern to use, ``None`` searches the best one."""
    version = qr_version(payload)
    if version is None:
        return None
    qr = qrcode.QRCode(
        version=version,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        border=_QUIET_MODULES,
        mask_pattern=mask,
    )
    try:
        qr.add_data(payload)
        qr.make(fit=False)  # the version is known: no second size search
    except (qrcode.exceptions.DataOverflowError, ValueError):
        return None
    return list(qr.get_matrix())


def _matrix_image(matrix: list[list[bool]]) -> Image.Image:
    """One pixel per module, mode ``"L"``. The library draws every module with its own
    rectangle call (thousands per symbol); the matrix is the same information."""
    side = len(matrix)
    flat = bytes(0 if dark else 255 for row in matrix for dark in row)
    return Image.frombytes("L", (side, side), flat)


def build_qr(payload: str, edge_px: int, *, mask: int | None = None) -> Image.Image | None:
    """QR in an ``edge_px`` square, mode ``"1"``; ``None`` if it cannot fit.

    ``mask`` fixes the mask pattern (the preview's ``PREVIEW_QR_MASK``); ``None``, what a job
    prints, searches the best of eight.

    Modules are a whole number of pixels (``edge_px // (n + 8)``, never resampled) and the four
    module quiet zone lies inside the square; the symbol is centred. A module below one pixel,
    or a payload larger than any QR symbol holds, returns ``None``.
    """
    matrix = _qr_matrix(payload, mask)
    if matrix is None:
        return None
    side = len(matrix)  # modules plus the quiet zone on both sides
    box_size = edge_px // side
    if box_size < 1:
        return None
    symbol = (
        _matrix_image(matrix)
        .resize((side * box_size, side * box_size), Image.Resampling.NEAREST)
        .convert("1")
    )
    canvas = Image.new("1", (edge_px, edge_px), 1)
    canvas.paste(symbol, ((edge_px - symbol.width) // 2, (edge_px - symbol.height) // 2))
    return canvas


def build_qr_preview(
    payload: str,
    box_w_mm: float,
    box_h_mm: float,
    job_dpi: int,
    preview_dpi: int,
    *,
    mask: int | None,
) -> Image.Image | None:
    """The QR as the job prints it, drawn at ``preview_dpi`` (the one function of the margin QR
    and the cell QRs, so the preview cannot drift from the job again).

    The job's symbol is whole-pixel modules at ``job_dpi`` inside the box's square; its size in
    mm follows by arithmetic from the version and the dpi. Here the module matrix is scaled
    (nearest neighbour) to that size at ``preview_dpi`` and centred in the preview's square, which
    is ``qr_edge_px`` at ``preview_dpi``. ``None`` if the job cannot draw it at all. ``mask`` as
    in ``build_qr``.
    """
    matrix = _qr_matrix(payload, mask)
    if matrix is None:
        return None
    side = len(matrix)
    job_box = qr_edge_px(box_w_mm, box_h_mm, job_dpi) // side
    if job_box < 1:
        return None
    edge = qr_edge_px(box_w_mm, box_h_mm, preview_dpi)
    size = min(edge, max(1, round(job_box * side * preview_dpi / job_dpi)))
    symbol = _matrix_image(matrix).resize((size, size), Image.Resampling.NEAREST).convert("1")
    canvas = Image.new("1", (edge, edge), 1)
    canvas.paste(symbol, ((edge - size) // 2, (edge - size) // 2))
    return canvas


def _box_px(box_w_mm: float, box_h_mm: float, dpi: int) -> tuple[int, int]:
    return max(1, round(box_w_mm / 25.4 * dpi)), max(1, round(box_h_mm / 25.4 * dpi))


def qr_edge_px(box_w_mm: float, box_h_mm: float, dpi: int) -> int:
    """Edge of the QR square in a box: the shorter side of the rendered image, in pixels."""
    return min(_box_px(box_w_mm, box_h_mm, dpi))


def qr_fits(payload: str, box_w_mm: float, box_h_mm: float, dpi: int) -> bool:
    """Whether the renderer can draw ``payload`` as a QR in this box.

    The renderer calls the same ``qr_edge_px`` and ``build_qr``, so Task 7's pre-check before
    reserving cells cannot drift from what the runner later does.
    """
    return build_qr(payload, qr_edge_px(box_w_mm, box_h_mm, dpi)) is not None


@lru_cache(maxsize=256)
def load_cell_font(size_px: int) -> ImageFont.FreeTypeFont:
    """The bundled PDF font at ``size_px`` (never a machine-dependent fallback), cached."""
    return ImageFont.truetype(str(resolve_font_path()), size_px)


def cap_height_px(font: ImageFont.FreeTypeFont) -> int:
    """Height of a capital letter in ``font``, in pixels."""
    _, top, _, bottom = font.getbbox("H")
    return int(bottom - top)


@lru_cache(maxsize=16)
def min_font_px(dpi: int) -> int:
    """Smallest font size whose cap height reaches ``MIN_CAP_HEIGHT_MM`` at ``dpi``."""
    target = math.ceil(MIN_CAP_HEIGHT_MM / 25.4 * dpi)
    size = 1
    while cap_height_px(load_cell_font(size)) < target:
        size += 1
    return size


@dataclass
class CellImage:
    image: Image.Image
    truncated: bool


class CellRenderer(Protocol):
    def render(
        self,
        *,
        box_w_mm: float,
        box_h_mm: float,
        dpi: int,
        content_type: ContentType,
        data: LabelData,
        qr_mask: int | None = None,
    ) -> CellImage:
        """Draw ``data`` as ``content_type`` into a 1-bit image of exactly the box at ``dpi``;
        ``qr_mask`` as ``build_qr``'s ``mask``."""
        ...


def _clean(value: str | None) -> str:
    text = (value or "")[:_MAX_TEXT_CHARS]
    return sanitise_text(text, max_len=_MAX_TEXT_CHARS)


def check_required(content_type: ContentType, data: LabelData) -> None:
    def empty(name: str) -> bool:
        value = getattr(data, name)
        if value is None or len(value) == 0:
            return True
        # Text that is only whitespace or control characters draws nothing: also missing.
        if name in ("primary_id", "title"):
            return not _clean(value)
        return False

    missing = tuple(name for name in REQUIRED_FIELDS[content_type] if empty(name))
    if missing:
        raise ContentTypeDataMismatchError(content_type=str(content_type), missing_fields=missing)


def _fit_line(text: str, start_px: int, min_px: int, max_w: int) -> tuple[str, int, bool]:
    """Shrink one pixel at a time to ``min_px``, then shorten with an ellipsis.

    Returns the text to draw, the font size used and whether the text was shortened.
    """
    size = max(start_px, min_px)
    while size > min_px and load_cell_font(size).getlength(text) > max_w:
        size -= 1
    font = load_cell_font(size)
    if font.getlength(text) <= max_w:
        return text, size, False
    lo, hi = 0, len(text)  # longest prefix that fits together with the ellipsis
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font.getlength(text[:mid].rstrip() + _ELLIPSIS) <= max_w:
            lo = mid
        else:
            hi = mid - 1
    shortened = text[:lo].rstrip() + _ELLIPSIS
    return (shortened if font.getlength(shortened) <= max_w else ""), size, True


class RasterCellRenderer:
    """Raster renderer: QR edge = box height, text column to its right, sizes as fractions."""

    def render(
        self,
        *,
        box_w_mm: float,
        box_h_mm: float,
        dpi: int,
        content_type: ContentType,
        data: LabelData,
        qr_mask: int | None = None,
    ) -> CellImage:
        check_required(content_type, data)
        if box_w_mm <= 0 or box_h_mm <= 0:  # defensive: the caller refuses these first
            raise ContentTypeDataMismatchError(
                content_type=str(content_type), missing_fields=("label_size",)
            )
        width, height = _box_px(box_w_mm, box_h_mm, dpi)
        canvas = Image.new("1", (width, height), 1)
        text_x = 0
        if content_type.value.startswith("qr_"):
            edge = qr_edge_px(box_w_mm, box_h_mm, dpi)
            qr = build_qr(data.qr_payload or "", edge, mask=qr_mask)
            if qr is None:
                raise QrDoesNotFitError(content_type=str(content_type))
            canvas.paste(qr, (0, 0))
            text_x = edge + max(2, height // 20)
        truncated = False
        max_w = width - text_x
        if _FRACTIONS[content_type] and max_w > 0:
            truncated = self._draw_text(canvas, content_type, data, text_x, max_w, dpi)
        return CellImage(canvas, truncated)

    def _lines(
        self, content_type: ContentType, data: LabelData, height: int
    ) -> tuple[list[tuple[str, int]], int]:
        """Lines to draw as (text, start size); second value: items left out of a listing."""
        starts = [max(1, round(f * height)) for f in _FRACTIONS[content_type]]
        primary = _clean(data.primary_id)
        match content_type:
            case ContentType.QR_ONE_LINE | ContentType.TEXT_ONE_LINE:
                return [(primary, starts[0])], 0
            case ContentType.QR_TWO_LINES | ContentType.TEXT_TWO_LINES:
                return [(primary, starts[0]), (_clean(data.title), starts[1])], 0
            case ContentType.QR_THREE_LINES:
                return [
                    (primary, starts[0]),
                    (_clean(data.title), starts[1]),
                    (_clean(data.secondary[0]), starts[2]),
                ], 0
            case _:  # QR_WITH_LISTING
                item_px = max(1, round(_LISTING_ITEM_FRACTION * height))
                per_line = item_px * (1 + _LINE_GAP_EM)
                room = height - starts[0] * (1 + _LINE_GAP_EM)
                fit = max(1, int(room // per_line))
                # Only the rows that are drawn are cleaned: cleaning all of up to 100 rows of
                # 512 characters cost more than drawing the cell (R10-5).
                omitted = 0
                if len(data.items) > fit:
                    omitted = len(data.items) - (fit - 1)
                    shown = [_clean(i.item) for i in data.items[: fit - 1]]
                else:
                    shown = [_clean(i.item) for i in data.items]
                lines = [(primary, starts[0])] + [(t, item_px) for t in shown]
                if omitted:
                    lines.append((f"+{omitted}", item_px))
                return lines, omitted

    def _draw_text(
        self,
        canvas: Image.Image,
        content_type: ContentType,
        data: LabelData,
        x: int,
        max_w: int,
        dpi: int,
    ) -> bool:
        height = canvas.height
        lines, omitted = self._lines(content_type, data, height)
        floor = min_font_px(dpi)
        # Scale the start sizes down together if the stacked block would not fit the height.
        block = sum(s * (1 + _LINE_GAP_EM + _DESCENT_EM) for _, s in lines)
        scale = min(1.0, height / block) if block else 1.0
        fitted: list[tuple[str, int]] = []
        truncated = omitted > 0
        for text, start in lines:
            shown, size, cut = _fit_line(text, round(start * scale), floor, max_w)
            fitted.append((shown, size))
            truncated = truncated or cut

        def pitch(size: int) -> int:
            return cap_height_px(load_cell_font(size)) + round(size * (_LINE_GAP_EM + _DESCENT_EM))

        def block_height(items: list[tuple[str, int]]) -> int:
            # the last line needs room for its descenders only, not for a following line
            return sum(pitch(s) for _, s in items[:-1]) + (
                cap_height_px(load_cell_font(items[-1][1])) + round(items[-1][1] * _DESCENT_EM)
            )

        # At the minimum cap height the lines may still not fit: drop trailing lines and flag
        # it, never clip at the image border.
        while len(fitted) > 1 and block_height(fitted) > height:
            fitted.pop()
            truncated = True
        if block_height(fitted) > height:  # not even one line fits
            return True
        total = block_height(fitted)
        y = max(0, (height - total) // 2)
        draw = ImageDraw.Draw(canvas)
        for text, size in fitted:
            font = load_cell_font(size)
            cap = cap_height_px(font)
            if text:
                draw.text((x, y + cap), text, font=font, fill=0, anchor="ls")
            y += pitch(size)
        return truncated


DEFAULT_CELL_RENDERER: CellRenderer = RasterCellRenderer()
"""The single place #178 swaps in a better renderer."""
