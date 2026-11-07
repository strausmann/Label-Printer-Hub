"""The ``sheet_page`` payload and its renderers (spec 10.2, 11.4, 12.4 and 13).

The margin ID sits in one of four bands (top, bottom, right or left of the grid); the planner
chooses the band and the payload stores it, the renderers only draw it (OC-50).

``SheetPageDetail`` is stored in ``PagePayload.detail``. It carries everything the page needs:
the geometry of the sheet's pinned type version (never re-read), the cells with their mapped
content type and label data, the ID cell and the margin ID. ``render_sheet_page`` is a pure
function of the payload: it reads no database and no clock, so the same payload always gives the
same bytes.

Field names other code reads from stored jobs: ``sheet_id`` (compared as a string) and
``margin_id`` (truthy when the page carries the margin ID) are read by
``reservation.margin_id_in_flight``. Task 8 asserts the ID cell on ``id_cell.content_type`` and
``id_cell.label_data.qr_payload``, because a PDF cannot tell a QR image from text.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal
from uuid import UUID

from PIL import Image, ImageDraw
from pydantic import BaseModel, ConfigDict, model_validator

from app.page_render.pdf import PageImage, PageText, text_width_mm, write_pdf
from app.page_render.transform import PT_PER_MM
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.services.page_jobs import PagePayload, snapshot_to_deviation
from app.sheets.cell_render import (
    DEFAULT_CELL_RENDERER,
    BoxHmm,
    CellImage,
    CellRenderer,
    build_qr,
    content_box,
    load_cell_font,
    qr_edge_px,
)
from app.sheets.geometry import Geometry, cell_count, remaining_margins
from app.sheets.planner import (
    MARGIN_TEXT_GAP_HMM,
    SAFETY_HMM,
    MarginBand,
    MarginCorner,
    MarginPlacement,
    margin_qr_allowed,
)

__all__ = [
    "PREVIEW_DPI",
    "MarginIdPayload",
    "SheetCellPayload",
    "SheetPageDetail",
    "margin_id_payload",
    "render_preview_png",
    "render_sheet_page",
]

PREVIEW_DPI: Final = 150
_MAX_PT: Final = 11.0
_MIN_PT: Final = 6.0
_CAP_EM: Final = 0.72  # cap height as a fraction of the font size


class SheetCellPayload(BaseModel):
    """One label on the page: the cell, the content type to draw (already mapped) and its data."""

    model_config = ConfigDict(extra="forbid")

    cell: int
    content_type: ContentType
    label_data: dict[str, Any]
    mapped: bool


class MarginIdPayload(BaseModel):
    """The sheet ID in a margin band; ``qr_payload`` is set only if the QR fits (OC-16).

    ``usable_hmm`` is the usable size of the band (at most 20 mm). A payload stored without
    ``band`` and ``corner`` is a top-band payload and renders exactly as before (OC-50)."""

    model_config = ConfigDict(extra="forbid")

    text: str
    qr_payload: str | None = None
    usable_hmm: int
    band: MarginBand = "top"
    corner: MarginCorner = "top_left"
    qr_allowed: bool | None = None
    """The one decision, taken at the job's render dpi when the payload is built (T4-2).
    ``None`` only in payloads stored before the flag existed: the rule is then evaluated at
    render dpi."""

    def draws_qr(self, render_dpi: int) -> bool:
        """Whether the margin carries a QR; the stored flag wins, the rule is the fallback."""
        if not self.qr_payload:
            return False
        if self.qr_allowed is not None:
            return self.qr_allowed
        return margin_qr_allowed(self.usable_hmm, self.qr_payload, render_dpi)


def margin_id_payload(
    text: str, qr_payload: str | None, placement: MarginPlacement
) -> MarginIdPayload:
    """Builds the margin ID from the planner's decision; the QR rule is not evaluated again.

    ``qr_payload`` is ``margin.scan_payload(code)``, the string the planner decided on.
    """
    allowed = placement.qr and bool(qr_payload)
    return MarginIdPayload(
        text=text,
        qr_payload=qr_payload if allowed else None,
        usable_hmm=placement.depth_hmm,
        band=placement.band,
        corner=placement.corner,
        qr_allowed=allowed,
    )


class SheetPageDetail(BaseModel):
    """``PagePayload.detail`` of a ``sheet_page`` job.

    Unknown keys are ignored so a job stored by a later version still renders; cell numbers
    are checked against the pinned geometry when the payload is built.
    """

    model_config = ConfigDict(extra="ignore")

    sheet_id: UUID
    sheet_code: str | None
    type_key: str
    type_version_id: UUID
    geometry: dict[str, Any]
    allow_qr: bool
    cells: list[SheetCellPayload]
    id_cell: SheetCellPayload | None = None
    margin_id: MarginIdPayload | None = None
    job_summary: dict[str, Any]

    @model_validator(mode="after")
    def _cells_valid(self) -> SheetPageDetail:
        total = cell_count(Geometry(**self.geometry))
        numbers = [c.cell for c in self.cells] + ([self.id_cell.cell] if self.id_cell else [])
        if len(set(numbers)) != len(numbers):
            raise ValueError("cell numbers must be unique on a page")
        if any(not 1 <= n <= total for n in numbers):
            raise ValueError(f"cell numbers must lie in 1..{total} of the pinned geometry")
        return self


@dataclass(frozen=True)
class _MarginLayout:
    qr: BoxHmm | None
    text: str
    text_x: int
    baseline_y: int
    size_pt: float
    rotation: Literal[0, 90] = 0


def _fit_margin_text(text: str, size_pt: float, room_mm: float) -> tuple[str, float]:
    """Shrink to ``_MIN_PT``, then shorten with an ellipsis; never draw past the grid."""
    size = size_pt
    while size > _MIN_PT and text_width_mm(text, size) > room_mm:
        size -= 0.5
    size = max(size, _MIN_PT)
    if text_width_mm(text, size) <= room_mm:
        return text, size
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if text_width_mm(text[:mid].rstrip() + "…", size) <= room_mm:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + "…", size


def _margin_layout(g: Geometry, margin: MarginIdPayload, *, with_qr: bool) -> _MarginLayout:
    """Where the margin ID goes, by the stored band (spec 10.2).

    The band starts ``SAFETY_HMM`` outside the grid and is ``usable_hmm`` deep. A QR is a square
    of that size at the grid's start of the band; the text follows it after a gap (or starts at
    the grid edge without a QR), centred across the band. Top and bottom text runs along the
    page; right and left text is turned a quarter turn clockwise and runs down the page.
    """
    d = margin.usable_hmm
    right, bottom = remaining_margins(g)
    grid_right = g.page_w - right
    grid_bottom = g.page_h - bottom
    lead = d + MARGIN_TEXT_GAP_HMM if with_qr else 0
    start = min(_MAX_PT, max(7.0, d / 100 * 1.4))
    if margin.band in ("top", "bottom"):
        top = g.margin_top - SAFETY_HMM - d if margin.band == "top" else grid_bottom + SAFETY_HMM
        qr = BoxHmm(g.margin_left, top, d, d) if with_qr else None
        text_x = g.margin_left + lead
        text, size = _fit_margin_text(margin.text, start, (grid_right - text_x) / 100)
        em_hmm = size / PT_PER_MM * 100
        return _MarginLayout(qr, text, text_x, round(top + d / 2 + _CAP_EM * em_hmm / 2), size)
    edge = grid_right + SAFETY_HMM if margin.band == "right" else g.margin_left - SAFETY_HMM - d
    qr = BoxHmm(edge, g.margin_top, d, d) if with_qr else None
    text_y = g.margin_top + lead
    text, size = _fit_margin_text(margin.text, start, (grid_bottom - text_y) / 100)
    em_hmm = size / PT_PER_MM * 100
    # Turned clockwise, the glyphs rise to the right of the baseline: the baseline is the
    # centre line minus half the cap height.
    return _MarginLayout(qr, text, round(edge + d / 2 - _CAP_EM * em_hmm / 2), text_y, size, 90)


def render_sheet_page(
    payload: PagePayload,
    renderer: CellRenderer = DEFAULT_CELL_RENDERER,
    *,
    compress: bool = True,
) -> bytes:
    """The PDF of a ``sheet_page`` payload (spec 12.4).

    Geometry comes only from the payload. Cells are drawn at their content boxes at
    ``payload.render_dpi``, the margin ID (if present) in its stored band, and the printer/tray
    correction is applied once to the whole page.
    """
    d = SheetPageDetail.model_validate(payload.detail)
    g = Geometry(**d.geometry)
    images: list[PageImage] = []
    texts: list[PageText] = []
    cells = [*d.cells, *([d.id_cell] if d.id_cell is not None else [])]
    for c in cells:
        box = content_box(g, c.cell)
        cell_image = renderer.render(
            box_w_mm=box.w / 100,
            box_h_mm=box.h / 100,
            dpi=payload.render_dpi,
            content_type=c.content_type,
            data=LabelData(**c.label_data),
        )
        images.append(PageImage(box.x, box.y, box.w, box.h, cell_image.image))
    if d.margin_id is not None:
        m = d.margin_id
        qr_image: Image.Image | None = None
        if m.qr_payload and m.draws_qr(payload.render_dpi):
            edge_mm = m.usable_hmm / 100
            qr_image = build_qr(m.qr_payload, qr_edge_px(edge_mm, edge_mm, payload.render_dpi))
        lay = _margin_layout(g, m, with_qr=qr_image is not None)
        if qr_image is not None and lay.qr is not None:
            images.append(PageImage(lay.qr.x, lay.qr.y, lay.qr.w, lay.qr.h, qr_image))
        texts.append(PageText(lay.text_x, lay.baseline_y, lay.size_pt, lay.text, lay.rotation))
    return write_pdf(
        payload.media,
        images=images,
        texts=texts,
        correction=snapshot_to_deviation(payload.calibration),
        compress=compress,
        title=payload.job_name,
    )


def _preview_qr(payload: str, usable_hmm: int) -> Image.Image:
    """The margin QR at preview size. It is a picture of what the job prints, so it is drawn
    even where the symbol is too fine for a 150 dpi raster: rendered larger, then reduced."""
    edge = qr_edge_px(usable_hmm / 100, usable_hmm / 100, PREVIEW_DPI)
    qr = build_qr(payload, edge)
    if qr is not None:
        return qr
    big = build_qr(payload, edge * 8)
    assert big is not None  # the job could draw it, so a symbol of this payload exists
    return big.convert("L").resize((edge, edge), Image.Resampling.BOX).convert("1")


def _paste_turned_text(
    page: Image.Image, lay: _MarginLayout, font: Any, origin: tuple[int, int]
) -> None:
    """Draw ``lay.text`` into its own image and paste it turned a quarter turn clockwise, so
    that the text origin (its baseline start) lands on ``origin``."""
    width = round(font.getlength(lay.text)) + 2
    height = round(font.size * 1.5)
    base = round(font.size * 1.1)  # the baseline row inside the strip
    strip = Image.new("1", (width, height), 1)
    ImageDraw.Draw(strip).text((0, base), lay.text, font=font, fill=0, anchor="ls")
    turned = strip.transpose(Image.Transpose.ROTATE_270)  # clockwise
    # After the turn, strip (x, y) lands at (height - 1 - y, x): the baseline row becomes the
    # column ``height - 1 - base`` and the text start the row 0.
    page.paste(turned, (origin[0] - (height - 1 - base), origin[1]))


def render_preview_png(
    geometry: Geometry,
    cells: Sequence[tuple[int, CellImage]],
    margin: MarginIdPayload | None,
    *,
    render_dpi: int = 600,
) -> bytes:
    """1-bit PNG of the page at 150 dpi (spec 12): only the new content, at nominal positions.

    The page size comes from ``geometry``. The preview is never calibrated. ``cells`` carry
    images rendered at ``PREVIEW_DPI`` for their content boxes. ``render_dpi`` is the job's
    resolution (600 if unknown, OC-26); it matters only for a margin ID stored without its QR
    flag, where the rule is evaluated at that dpi, never at the preview's.
    """
    k = PREVIEW_DPI / 2540

    def px(v: float) -> int:
        return round(v * k)

    page = Image.new("1", (px(geometry.page_w), px(geometry.page_h)), 1)
    for n, cell in cells:
        box = content_box(geometry, n)
        page.paste(cell.image, (px(box.x), px(box.y)))
    if margin is not None:
        # The decision is the job's (stored flag); the preview only draws it.
        qr = (
            _preview_qr(margin.qr_payload, margin.usable_hmm)
            if margin.qr_payload and margin.draws_qr(render_dpi)
            else None
        )
        lay = _margin_layout(geometry, margin, with_qr=qr is not None)
        if qr is not None and lay.qr is not None:
            page.paste(qr, (px(lay.qr.x), px(lay.qr.y)))
        font = load_cell_font(max(1, round(lay.size_pt * PREVIEW_DPI / 72)))
        if lay.rotation == 90:
            _paste_turned_text(page, lay, font, (px(lay.text_x), px(lay.baseline_y)))
        else:
            ImageDraw.Draw(page).text(
                (px(lay.text_x), px(lay.baseline_y)), lay.text, font=font, fill=0, anchor="ls"
            )
    out = io.BytesIO()
    page.save(out, format="PNG")
    return out.getvalue()
