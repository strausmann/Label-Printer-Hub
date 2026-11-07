"""The ``sheet_page`` payload and its renderers (spec 10.2, 11.4, 12.4 and 13).

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
from typing import Any, Final
from uuid import UUID

from PIL import Image, ImageDraw
from pydantic import BaseModel, ConfigDict

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
from app.sheets.geometry import Geometry
from app.sheets.planner import SAFETY_HMM

__all__ = [
    "PREVIEW_DPI",
    "MarginIdPayload",
    "SheetCellPayload",
    "SheetPageDetail",
    "render_preview_png",
    "render_sheet_page",
]

PREVIEW_DPI: Final = 150
_TEXT_GAP_HMM: Final = 200  # 2 mm between the margin QR and the text
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
    """The sheet ID in the top margin; ``qr_payload`` is set only if the QR fits (OC-16)."""

    model_config = ConfigDict(extra="forbid")

    text: str
    qr_payload: str | None = None
    usable_hmm: int


class SheetPageDetail(BaseModel):
    """``PagePayload.detail`` of a ``sheet_page`` job."""

    model_config = ConfigDict(extra="forbid")

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


@dataclass(frozen=True)
class _MarginLayout:
    qr: BoxHmm | None
    text: str
    text_x: int
    baseline_y: int
    size_pt: float


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
    """Where the margin ID goes: left-aligned with the grid, centred in the usable band.

    The band ends ``SAFETY_HMM`` above the grid and is ``usable_hmm`` tall; a QR is a square of
    that height, the text sits to its right (or at the grid edge without a QR).
    """
    bottom = g.margin_top - SAFETY_HMM
    top = bottom - margin.usable_hmm
    qr = BoxHmm(g.margin_left, top, margin.usable_hmm, margin.usable_hmm) if with_qr else None
    text_x = g.margin_left + (margin.usable_hmm + _TEXT_GAP_HMM if with_qr else 0)
    grid_right = g.margin_left + (g.cols - 1) * g.pitch_x + g.label_w
    start = min(_MAX_PT, max(7.0, margin.usable_hmm / 100 * 1.4))
    text, size = _fit_margin_text(margin.text, start, (grid_right - text_x) / 100)
    em_hmm = size / PT_PER_MM * 100
    centre = top + margin.usable_hmm / 2
    return _MarginLayout(qr, text, text_x, round(centre + _CAP_EM * em_hmm / 2), size)


def render_sheet_page(
    payload: PagePayload,
    renderer: CellRenderer = DEFAULT_CELL_RENDERER,
    *,
    compress: bool = True,
) -> bytes:
    """The PDF of a ``sheet_page`` payload (spec 12.4).

    Geometry comes only from the payload. Cells are drawn at their content boxes at
    ``payload.render_dpi``, the margin ID (if present) in the top margin, and the printer/tray
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
        if m.qr_payload:
            edge_mm = m.usable_hmm / 100
            qr_image = build_qr(m.qr_payload, qr_edge_px(edge_mm, edge_mm, payload.render_dpi))
        lay = _margin_layout(g, m, with_qr=qr_image is not None)
        if qr_image is not None and lay.qr is not None:
            images.append(PageImage(lay.qr.x, lay.qr.y, lay.qr.w, lay.qr.h, qr_image))
        texts.append(PageText(lay.text_x, lay.baseline_y, lay.size_pt, lay.text))
    return write_pdf(
        payload.media,
        images=images,
        texts=texts,
        correction=snapshot_to_deviation(payload.calibration),
        compress=compress,
        title=payload.job_name,
    )


def render_preview_png(
    geometry: Geometry,
    cells: Sequence[tuple[int, CellImage]],
    margin: MarginIdPayload | None,
) -> bytes:
    """1-bit PNG of the page at 150 dpi (spec 12): only the new content, at nominal positions.

    The page size comes from ``geometry``. The preview is never calibrated. ``cells`` carry
    images rendered at ``PREVIEW_DPI`` for their content boxes.
    """
    k = PREVIEW_DPI / 2540

    def px(v: float) -> int:
        return round(v * k)

    page = Image.new("1", (px(geometry.page_w), px(geometry.page_h)), 1)
    for n, cell in cells:
        box = content_box(geometry, n)
        page.paste(cell.image, (px(box.x), px(box.y)))
    if margin is not None:
        edge_mm = margin.usable_hmm / 100
        qr = (
            build_qr(margin.qr_payload, qr_edge_px(edge_mm, edge_mm, PREVIEW_DPI))
            if margin.qr_payload
            else None
        )
        lay = _margin_layout(geometry, margin, with_qr=qr is not None)
        if qr is not None and lay.qr is not None:
            page.paste(qr, (px(lay.qr.x), px(lay.qr.y)))
        font = load_cell_font(max(1, round(lay.size_pt * PREVIEW_DPI / 72)))
        ImageDraw.Draw(page).text(
            (px(lay.text_x), px(lay.baseline_y)), lay.text, font=font, fill=0, anchor="ls"
        )
    out = io.BytesIO()
    page.save(out, format="PNG")
    return out.getvalue()
