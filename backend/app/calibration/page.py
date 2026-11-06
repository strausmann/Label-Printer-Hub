"""The printable calibration page (spec 13.2): a test grid the user measures.

The page shows the sheet type's cut lines with a ruler and a millimetre scale at every crossing
of four labels. The user prints it on the real paper, reads how far the ink landed from each
crossing, and enters the readings; ``fit`` turns them into the printer's deviation.

Only the page drawing, its footer and the payload renderer live here. The routes build the
payload with ``build_payload`` and then both the job and the PDF download call
``render_calibration_page`` on it, so they cannot drift apart (OC-35). No sheet record is
created or touched.

The four 15 x 15 mm squares at the page corners are reserved for the registration markers of
the scan (Part B). Nothing is drawn in them: a mark, tick, scale or text whose bounding box
overlaps the inside of a square is left out as a whole, and a gap line that runs into one is
clipped at it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from datetime import date
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from app.calibration.fit import crossing_point
from app.page_render.pdf import VectorPen, write_pdf
from app.page_render.transform import IDENTITY, Deviation
from app.services.page_jobs import PagePayload
from app.sheets.errors import CalibrationTypeUnsuitableError
from app.sheets.geometry import Geometry

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

#: Plan 2 decision: the page size the squares are measured on is the sheet's own.
CORNER_SQUARE_MM = 15.0
LINE_MM = 0.1
DASHED = (1.0, 0.5)
DOTTED = (0.2, 0.4)
LABEL_PT = 2.5
FOOTER_PT = 6.0
FOOTER_BASELINE_MM = 7.0
CHECKERBOARD_SENTENCE = "Peel every other label (checkerboard) if the cut is hard to see."
_SENTENCE_BASELINE_FROM_BOTTOM_MM = 11.0
_PT_MM = 25.4 / 72
#: A glyph is never wider than this many em: the omission test for text must not underestimate.
_EM_WIDTH = 0.6

_KEY_MAX = 40
_NAME_MAX = 24

# Mini scale at a crossing: ±2 mm, a tick every 0.2 mm.
_SCALE_HALF_MM = 2.0
_SCALE_STEP_MM = 0.2
_TICK_TENTH_MM, _TICK_WHOLE_MM, _TICK_CENTRE_MM = 0.6, 1.2, 1.8
# Ruler on a grid edge at a gap line: ±3 mm, a tick every 0.5 mm, drawn outwards.
_RULER_HALF_MM = 3.0
_RULER_STEP_MM = 0.5
_RULER_TICK_MM = 1.0
_CORNER_LEG_MM = 1.5

_Box = tuple[float, float, float, float]


def today_iso() -> str:
    """The hub's local date; the routes put it into the payload, the renderer never reads it."""
    return date.today().isoformat()


def _short(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def footer_text(
    type_key: str, version: int, printer_name: str, tray: str, day: str, *, corrected: bool
) -> str:
    """The footer line. Long names are shortened so the line stays clear of the corner squares."""
    outcome = "check print with correction" if corrected else "printed without correction"
    return (
        f"{_short(type_key, _KEY_MAX)} v{version} · {_short(printer_name, _NAME_MAX)}"
        f" · tray {_short(tray, _NAME_MAX)} · {day} · Calibration page — {outcome}"
    )


class _Page:
    """The pen plus the corner-square rule; every drawing call goes through here."""

    def __init__(self, pen: VectorPen, width_mm: float, height_mm: float) -> None:
        self._pen = pen
        self._w = width_mm
        self._h = height_mm
        s = CORNER_SQUARE_MM
        self._squares: tuple[_Box, ...] = (
            (0, 0, s, s),
            (width_mm - s, 0, width_mm, s),
            (0, height_mm - s, s, height_mm),
            (width_mm - s, height_mm - s, width_mm, height_mm),
        )

    def clear(self, box: _Box) -> bool:
        """True if no point of ``box`` lies strictly inside a corner square."""
        x0, y0, x1, y1 = box
        return not any(
            x0 < sx1 and x1 > sx0 and y0 < sy1 and y1 > sy0 for sx0, sy0, sx1, sy1 in self._squares
        )

    def segments(
        self,
        segs: Sequence[tuple[float, float, float, float]],
        dash: tuple[float, ...] | None = None,
    ) -> None:
        """One element made of several segments; omitted as a whole if its box is not clear."""
        xs = [v for s in segs for v in (s[0], s[2])]
        ys = [v for s in segs for v in (s[1], s[3])]
        if not self.clear((min(xs), min(ys), max(xs), max(ys))):
            return
        for x1, y1, x2, y2 in segs:
            self._pen.line(x1, y1, x2, y2, width_mm=LINE_MM, dash=dash)

    def run(
        self, x: float, y1: float, y2: float, *, vertical: bool, dash: tuple[float, ...] | None
    ) -> None:
        """A long axis-parallel line, clipped at the corner squares instead of dropped."""
        s = CORNER_SQUARE_MM
        lo, hi = (s, self._h - s) if vertical else (s, self._w - s)
        across = self._w if vertical else self._h
        in_band = x < s or x > across - s
        a, b = min(y1, y2), max(y1, y2)
        if in_band:
            a, b = max(a, lo), min(b, hi)
        if b <= a:
            return
        if vertical:
            self._pen.line(x, a, x, b, width_mm=LINE_MM, dash=dash)
        else:
            self._pen.line(a, x, b, x, width_mm=LINE_MM, dash=dash)

    def text(
        self,
        x: float,
        y: float,
        s: str,
        *,
        size_pt: float,
        anchor: Literal["start", "middle", "end"],
    ) -> None:
        em = size_pt * _PT_MM
        width = len(s) * em * _EM_WIDTH
        left = {"start": x, "middle": x - width / 2, "end": x - width}[anchor]
        if self.clear((left, y - em, left + width, y + em * 0.25)):
            self._pen.text(x, y, s, size_pt=size_pt, anchor=anchor)


def _mini_scale(page: _Page, cx: float, cy: float, *, along_x: bool) -> None:
    """Ticks of a ±2 mm scale; one element, so it is left out whole if it touches a square."""
    segs: list[tuple[float, float, float, float]] = []
    for k in range(-10, 11):
        off = k * _SCALE_STEP_MM
        length = _TICK_CENTRE_MM if k == 0 else _TICK_WHOLE_MM if k % 5 == 0 else _TICK_TENTH_MM
        h = length / 2
        segs.append(
            (cx + off, cy - h, cx + off, cy + h)
            if along_x
            else (cx - h, cy + off, cx + h, cy + off)
        )
    xs = [v for s in segs for v in (s[0], s[2])]
    ys = [v for s in segs for v in (s[1], s[3])]
    if not page.clear((min(xs), min(ys), max(xs), max(ys))):
        return
    for s in segs:
        page.segments([s])


def _ruler(page: _Page, pos: float, edge: float, *, horizontal: bool, outward: int) -> None:
    """Half-millimetre ticks around ``pos`` along one grid edge; every tick is its own element."""
    for k in range(-6, 7):
        t = pos + k * _RULER_STEP_MM
        a, b = edge, edge + outward * _RULER_TICK_MM
        page.segments([(t, a, t, b)] if horizontal else [(a, t, b, t)])


def _corner_mark(page: _Page, x: float, y: float, dx: int, dy: int) -> None:
    """An L at a label corner whose legs run along the label's two edges, inwards."""
    leg = _CORNER_LEG_MM
    page.segments([(x, y, x + dx * leg, y), (x, y, x, y + dy * leg)])


def draw_calibration_page(pen: VectorPen, g: Geometry, *, footer: str) -> None:
    """Draw the page for ``g`` (everything in black, 0.1 mm lines); see the module docstring."""
    if g.cols < 2 or g.rows < 2:
        raise CalibrationTypeUnsuitableError(g.cols, g.rows)
    page = _Page(pen, g.page_w / 100, g.page_h / 100)
    x0, y0 = g.margin_left / 100, g.margin_top / 100
    gw = ((g.cols - 1) * g.pitch_x + g.label_w) / 100
    gh = ((g.rows - 1) * g.pitch_y + g.label_h) / 100
    col_gap, row_gap = g.pitch_x > g.label_w, g.pitch_y > g.label_h
    col_x = [crossing_point(g, i, 1)[0] for i in range(1, g.cols)]
    row_y = [crossing_point(g, 1, j)[1] for j in range(1, g.rows)]

    for x in col_x:  # solid when there is a gap to centre in, else dotted on the nominal cut
        page.run(x, y0, y0 + gh, vertical=True, dash=None if col_gap else DOTTED)
    for y in row_y:
        page.run(y, x0, x0 + gw, vertical=False, dash=DASHED if row_gap else DOTTED)

    for x in col_x:
        for y in row_y:
            _mini_scale(page, x, y, along_x=True)
            _mini_scale(page, x, y, along_x=False)

    for x in col_x:
        _ruler(page, x, y0, horizontal=True, outward=-1)
        _ruler(page, x, y0 + gh, horizontal=True, outward=1)
    for y in row_y:
        _ruler(page, y, x0, horizontal=False, outward=-1)
        _ruler(page, y, x0 + gw, horizontal=False, outward=1)

    for r in range(g.rows):
        for c in range(g.cols):
            lx0 = (g.margin_left + c * g.pitch_x) / 100
            ly0 = (g.margin_top + r * g.pitch_y) / 100
            lx1, ly1 = lx0 + g.label_w / 100, ly0 + g.label_h / 100
            _corner_mark(page, lx0, ly0, 1, 1)
            _corner_mark(page, lx1, ly0, -1, 1)
            _corner_mark(page, lx0, ly1, 1, -1)
            _corner_mark(page, lx1, ly1, -1, -1)

    for i, x in enumerate(col_x, start=1):
        page.text(x, y0 - _RULER_TICK_MM - 0.6, f"S{i}", size_pt=LABEL_PT, anchor="middle")
        page.text(x, y0 + gh + _RULER_TICK_MM + 1.1, f"S{i}", size_pt=LABEL_PT, anchor="middle")
    for j, y in enumerate(row_y, start=1):
        page.text(x0 - _RULER_TICK_MM - 0.6, y + 0.3, f"Z{j}", size_pt=LABEL_PT, anchor="end")
        page.text(
            x0 + gw + _RULER_TICK_MM + 0.6, y + 0.3, f"Z{j}", size_pt=LABEL_PT, anchor="start"
        )

    if not (col_gap and row_gap):
        page.text(
            g.page_w / 200,
            g.page_h / 100 - _SENTENCE_BASELINE_FROM_BOTTOM_MM,
            CHECKERBOARD_SENTENCE,
            size_pt=FOOTER_PT,
            anchor="middle",
        )
    page.text(
        g.page_w / 200,
        g.page_h / 100 - FOOTER_BASELINE_MM,
        footer,
        size_pt=FOOTER_PT,
        anchor="middle",
    )


# ---------------------------------------------------------------------------- payload, renderer


def render_calibration_page(payload: PagePayload, *, compress: bool = True) -> bytes:
    """The PDF of a ``calibration_page`` payload. Used by the job and by the download alike."""
    d = payload.detail
    g = Geometry(**d["geometry"])
    corrected = bool(d["corrected"])
    snap = payload.calibration if corrected else None
    dev = (
        Deviation(snap.dx_hmm, snap.dy_hmm, snap.sx_ppm, snap.sy_ppm, snap.rotation_udeg)
        if snap is not None
        else IDENTITY
    )
    footer = footer_text(
        d["type_key"], d["version"], d["printer_name"], payload.tray, d["date"], corrected=corrected
    )
    return write_pdf(
        payload.media,
        vector=lambda pen: draw_calibration_page(pen, g, footer=footer),
        correction=dev,
        compress=compress,
        title="Calibration page",
    )


async def build_payload(
    session: AsyncSession,
    printer_id: UUID,
    tray: str,
    *,
    type_key: str,
    version: int | None,
    corrected: bool,
) -> PagePayload:
    """Validate printer, tray and type and build the payload; the only place that does.

    Raises the ``SheetApiError``s of the calibration service and the type service, and
    ``CalibrationTypeUnsuitableError`` for a type without crossings.
    """
    from app.calibration import service
    from app.models.printer import Printer
    from app.sheets import type_service as ts

    snapshot = await service.snapshot(session, printer_id, tray)  # kind and tray are checked
    printer = await session.get(Printer, printer_id)
    assert printer is not None  # snapshot() found it
    sheet_type = await ts.get_type(session, type_key)
    v = (
        await ts.current_version(session, sheet_type.id)
        if version is None
        else await ts.get_version(session, type_key, version)
    )
    g = ts.version_geometry(v)
    if g.cols < 2 or g.rows < 2:
        raise CalibrationTypeUnsuitableError(g.cols, g.rows)
    detail: dict[str, Any] = {
        "type_key": sheet_type.key,
        "version": v.version,
        "printer_name": printer.name,
        "date": today_iso(),
        "corrected": corrected,
        "geometry": asdict(g),
    }
    return PagePayload(
        kind="calibration_page",
        media=g.page_size,
        tray=tray,
        render_dpi=600,
        job_name=f"Calibration page · {sheet_type.key} v{v.version}",
        calibration=snapshot if corrected else None,
        detail=detail,
    )
