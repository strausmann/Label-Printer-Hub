"""Pure placement planner: which items go into which cells (spec 8, 10.1, 10.2).

Decides ``first_free`` and explicit placements, skipped cells, overflow onto further sheets,
the ID cell and the margin ID, including the band of the sheet margin (top, bottom, right or
left) it is drawn in. It reads ``SheetView`` values and writes nothing; reserving the
cells atomically is the job of the reservation service.

All lengths are hundredths of a millimetre (hmm).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal
from uuid import UUID

import qrcode
import qrcode.constants
import qrcode.exceptions

from app.page_render.pdf import text_width_mm
from app.page_render.transform import PT_PER_MM, Deviation
from app.printer_backends.ipp.attributes import Margins
from app.sheets.cell_render import qr_edge_px
from app.sheets.errors import (
    CellOutOfRangeError,
    CellsTakenError,
    InsufficientCellsError,
    InvalidPlacementsError,
    SheetDiscardedError,
)
from app.sheets.geometry import Geometry, cell_count, cell_origin, remaining_margins

__all__ = [
    "BAND_CORNER",
    "BAND_ORDER",
    "FEED_MARK_MIN_PT",
    "FEED_MARK_PT",
    "FEED_MARK_TEXTS",
    "FeedMarkPlacement",
    "MarginBand",
    "MarginContext",
    "MarginCorner",
    "MarginPlacement",
    "PagePlan",
    "PlacementIn",
    "Plan",
    "SheetView",
    "band_length_hmm",
    "choose_feed_mark",
    "choose_margin_placement",
    "feed_mark_text",
    "margin_bands_hmm",
    "margin_qr_allowed",
    "margin_qr_fits",
    "plan",
]

MarginBand = Literal["top", "bottom", "right", "left"]
MarginCorner = Literal["top_left", "top_right", "bottom_left"]

BAND_ORDER: Final[tuple[MarginBand, ...]] = ("top", "bottom", "right", "left")  # OC-46
BAND_CORNER: Final[dict[MarginBand, MarginCorner]] = {  # OC-45
    "top": "top_left",
    "bottom": "bottom_left",
    "right": "top_right",
    "left": "top_left",
}

DEFAULT_HW_HMM: Final = 500  # 5.0 mm per side assumed when the printer does not report it (OC-16)
SAFETY_HMM: Final = 100  # 1.0 mm
MIN_MARGIN_TEXT_HMM: Final = 400  # below: margin ID impossible
MIN_MARGIN_QR_HMM: Final = 900  # from here a QR may sit next to the text
MIN_QR_MODULE_HMM: Final = 25  # 0.25 mm
MARGIN_TEXT_GAP_HMM: Final = 200  # 2 mm between the margin QR and the text
MIN_MARGIN_TEXT_RUN_HMM: Final = 1000  # 10 mm of text beside a QR (OC-48)
MAX_MARGIN_ID_HMM: Final = 2000  # usable size cap, 20 mm (OC-52)
VERTICAL_BAND_LEAD_HMM: Final = 200  # a side band must be 2 mm deeper to beat top or bottom
_QUIET_MODULES: Final = 4
_CAP_EM: Final = 0.72  # cap height as a fraction of the font size

FEED_MARK_TEXTS: Final[dict[str, str]] = {  # OC-55, ruling A-5; \u2013 is the en dash (RUF001)
    "en": "▲ Top \u2013 this edge first",
    "de": "▲ Oben \u2013 diese Kante zuerst",
}
FEED_MARK_PT: Final = 7.0  # OC-54
FEED_MARK_MIN_PT: Final = 6.0


@dataclass
class SheetView:
    """What the planner needs to know about one sheet (an existing one or a new one).

    ``non_free`` maps every cell that has a ``sheet_cells`` row to its state. A new sheet has
    ``code=None`` and no non-free cells. ``margin_id_in_flight`` is computed by the caller
    inside the write lock: another job already carries the margin ID of this sheet.
    """

    code: str | None
    type_key: str
    type_version_id: UUID
    geometry: Geometry
    allow_qr: bool
    non_free: dict[int, str]
    id_placement: Literal["cell", "margin", "manual"]
    id_printed: bool
    has_hub_cell: bool
    margin_id_in_flight: bool
    state: Literal["active", "discarded"]
    # The database id of an existing or just created sheet; the planner ignores it.
    sheet_id: UUID | None = None
    # The probable code of a sheet that does not exist yet (a preview); used for the QR payload.
    code_hint: str | None = None
    # The feed-direction mark (spec 10.2a): its own flag, and whether another job carries it.
    feed_mark_printed: bool = False
    feed_mark_in_flight: bool = False


@dataclass
class PlacementIn:
    sheet: SheetView
    cells: Literal["first_free"] | list[int]
    skip: list[int] = field(default_factory=list)
    count: int | None = None


@dataclass
class PagePlan:
    index: int
    sheet: SheetView
    item_cells: list[int]
    id_cell: int | None
    margin_id: bool
    hw_margin_cells: list[int]
    margin_placement: MarginPlacement | None = None
    id_not_printed: bool = False
    feed_mark: FeedMarkPlacement | None = None


@dataclass
class Plan:
    pages: list[PagePlan]
    # Per page: how many cells of its sheet are still free afterwards. Skipped cells stay free
    # (skip is never stored, OC-38).
    free_after: list[int]


@dataclass(frozen=True)
class MarginContext:
    """What the margin decisions need. ``language`` is required on purpose (no default): a
    caller that leaves it out is reported by ``mypy`` and raises ``TypeError``, so the mark
    never turns English by accident. ``None`` or an unknown value gives English."""

    deviation: Deviation
    scan_payload: Callable[[str], str]
    render_dpi: int
    language: str | None


@dataclass(frozen=True)
class FeedMarkPlacement:
    """The feed-direction mark: ``x_hmm`` is the left end of the text."""

    text: str
    x_hmm: int
    baseline_y_hmm: int
    size_pt: float
    width_hmm: int


@dataclass(frozen=True)
class MarginPlacement:
    """Where the margin ID goes. ``depth_hmm`` is the usable size that is drawn (capped)."""

    band: MarginBand
    corner: MarginCorner
    depth_hmm: int
    qr: bool


def margin_bands_hmm(g: Geometry, *, hw: Margins | None, dev: Deviation) -> dict[MarginBand, int]:
    """Room of each margin band after the printer's hardware margin of that side (5 mm if
    unknown), the calibration shift on that axis and 1 mm of safety.

    Every band of an axis loses the full ``|offset|`` of the axis, whatever its sign (ruling
    A-1). Values may be negative; scale and rotation are ignored (OC-51).
    """
    m = (
        hw
        if hw is not None
        else Margins(
            top=DEFAULT_HW_HMM, left=DEFAULT_HW_HMM, bottom=DEFAULT_HW_HMM, right=DEFAULT_HW_HMM
        )
    )
    right, bottom = remaining_margins(g)
    dx = abs(dev.offset_x_hmm)
    dy = abs(dev.offset_y_hmm)
    return {
        "top": g.margin_top - m.top - dy - SAFETY_HMM,
        "bottom": bottom - m.bottom - dy - SAFETY_HMM,
        "right": right - m.right - dx - SAFETY_HMM,
        "left": g.margin_left - m.left - dx - SAFETY_HMM,
    }


def band_length_hmm(g: Geometry, band: MarginBand) -> int:
    """Length of the grid along ``band``: the room a text beside the QR can run."""
    if band in ("top", "bottom"):
        return (g.cols - 1) * g.pitch_x + g.label_w
    return (g.rows - 1) * g.pitch_y + g.label_h


def margin_qr_allowed(usable_hmm: int, payload: str, dpi: int) -> bool:
    """Whether a QR of ``payload`` is drawn next to the margin ID (OC-16, ruling T4-1).

    The one decision the planner and the renderer both use. True only if the band is at least
    9 mm tall and the module ``build_qr`` really produces at ``dpi`` (the symbol is
    ``qr_edge_px`` square, modules a whole number of device pixels, four-module quiet zone
    inside) is at least 0.25 mm. Pixel flooring is part of the answer, not an afterthought.
    """
    if usable_hmm < MIN_MARGIN_QR_HMM or dpi <= 0:
        return False
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0)
    try:
        qr.add_data(payload)
        qr.make(fit=True)
    except (qrcode.exceptions.DataOverflowError, ValueError):
        return False
    edge = qr_edge_px(usable_hmm / 100, usable_hmm / 100, dpi)
    module_px = edge // (len(qr.get_matrix()) + 2 * _QUIET_MODULES)
    # module_px * 25.4 / dpi >= 0.25 mm, in integers: module_px * 2540 >= 25 * dpi
    return module_px >= 1 and module_px * 2540 >= MIN_QR_MODULE_HMM * dpi


margin_qr_fits = margin_qr_allowed
"""Name the plan uses; the same function."""


def feed_mark_text(language: str | None) -> str:
    """The mark's text for the hub language; any other value gives English (ruling A-5)."""
    return FEED_MARK_TEXTS.get(language or "", FEED_MARK_TEXTS["en"])


def choose_feed_mark(
    g: Geometry, *, hw: Margins | None, dev: Deviation, text: str
) -> FeedMarkPlacement | None:
    """Where the feed-direction mark goes: the top band's top-right end, or nowhere (OC-53/54).

    Not printed when the top band is below 4 mm; never in another band. 7 pt, shrinking in
    0.5 pt steps to 6 pt; never shortened, so it is dropped when 6 pt does not fit.
    """
    depth = margin_bands_hmm(g, hw=hw, dev=dev)["top"]
    if depth < MIN_MARGIN_TEXT_HMM:
        return None
    usable = min(depth, MAX_MARGIN_ID_HMM)
    right_margin = hw.right if hw is not None else DEFAULT_HW_HMM
    grid_right = g.page_w - remaining_margins(g)[0]
    right_end = min(grid_right, g.page_w - right_margin - abs(dev.offset_x_hmm) - SAFETY_HMM)
    room = right_end - g.margin_left
    size = FEED_MARK_PT
    while round(text_width_mm(text, size) * 100) > room and size > FEED_MARK_MIN_PT:
        size -= 0.5
    width = round(text_width_mm(text, size) * 100)
    if width > room:
        return None
    centre = g.margin_top - SAFETY_HMM - usable / 2
    baseline = round(centre + _CAP_EM * size / PT_PER_MM * 100 / 2)
    return FeedMarkPlacement(text, right_end - width, baseline, size, width)


def choose_margin_placement(
    g: Geometry,
    *,
    hw: Margins | None,
    dev: Deviation,
    payload: str | None,
    dpi: int,
    top_taken_hmm: int = 0,
) -> MarginPlacement | None:
    """The band the margin ID goes into, or ``None`` if no band is deep enough (OC-46).

    A band with a QR beats any text-only band; then depth decides, with the tie-break top,
    bottom, right, left. A side band beats the best of top and bottom only if it is
    ``VERTICAL_BAND_LEAD_HMM`` deeper (ruling A-2). Decided once, at render dpi.
    ``top_taken_hmm`` is the length of the top band the feed-direction mark takes (from its left
    end to the grid's right end, plus the gap); the top band's length rule sees the rest.
    """
    usable = {
        band: min(depth, MAX_MARGIN_ID_HMM)
        for band, depth in margin_bands_hmm(g, hw=hw, dev=dev).items()
    }
    qr_of: dict[MarginBand, bool] = {}
    for band in BAND_ORDER:
        if usable[band] < MIN_MARGIN_TEXT_HMM:
            continue
        qr_of[band] = (
            payload is not None
            and margin_qr_allowed(usable[band], payload, dpi)
            and band_length_hmm(g, band) - (top_taken_hmm if band == "top" else 0)
            >= usable[band] + MARGIN_TEXT_GAP_HMM + MIN_MARGIN_TEXT_RUN_HMM
        )
    if not qr_of:
        return None
    if any(qr_of.values()):
        qr_of = {band: qr for band, qr in qr_of.items() if qr}

    def deepest(bands: tuple[MarginBand, ...]) -> MarginBand | None:
        best_of: MarginBand | None = None
        for b in bands:  # strict ">" keeps the first of equal bands
            if b in qr_of and (best_of is None or usable[b] > usable[best_of]):
                best_of = b
        return best_of

    h = deepest(("top", "bottom"))
    v = deepest(("right", "left"))
    if h is not None and v is not None:
        best: MarginBand = v if usable[v] >= usable[h] + VERTICAL_BAND_LEAD_HMM else h
    else:
        only = h or v
        assert only is not None  # qr_of is not empty
        best = only
    return MarginPlacement(best, BAND_CORNER[best], usable[best], qr_of[best])


def _hw_margin_cells(g: Geometry, cells: Sequence[int], hw: Margins | None) -> list[int]:
    """Cells whose rectangle reaches into a hardware-margin band (OC-44: flagged, not refused)."""
    if hw is None:
        return []
    flagged: list[int] = []
    for n in sorted(cells):
        x, y = cell_origin(g, n)
        if (
            y < hw.top
            or x < hw.left
            or y + g.label_h > g.page_h - hw.bottom
            or x + g.label_w > g.page_w - hw.right
        ):
            flagged.append(n)
    return flagged


def _resolve_counts(placements: Sequence[PlacementIn], n_items: int) -> list[int]:
    counts: list[int] = []
    last = len(placements) - 1
    for i, p in enumerate(placements):
        if isinstance(p.cells, list):
            if p.count is not None and p.count != len(p.cells):
                raise InvalidPlacementsError("explicit_count_mismatch")
            counts.append(len(p.cells))
        elif p.count is None:
            if i != last:
                raise InvalidPlacementsError("count_missing_not_last")
            counts.append(-1)  # takes the rest, resolved below
        else:
            if p.count < 0:
                raise InvalidPlacementsError("count_mismatch")
            counts.append(p.count)
    if counts and counts[-1] == -1:
        rest = n_items - sum(counts[:-1])
        if rest < 0:
            raise InvalidPlacementsError("count_mismatch")
        counts[-1] = rest
    if sum(counts) != n_items:
        raise InvalidPlacementsError(
            "explicit_count_mismatch"
            if any(isinstance(p.cells, list) for p in placements)
            else "count_mismatch"
        )
    return counts


@dataclass
class _Draft:
    placement: PlacementIn
    count: int
    id_cell: int | None
    id_missing: bool
    item_cells: list[int]
    margin_id: bool
    available: int
    free_after: int
    margin_placement: MarginPlacement | None = None
    id_not_printed: bool = False
    id_was_due: bool = False
    feed_mark: FeedMarkPlacement | None = None
    mark_was_due: bool = False


def _draft(
    p: PlacementIn,
    count: int,
    taken: set[int],
    margin: MarginContext | None,
    id_done: bool,
    mark_done: bool,
    hw_margins_hmm: Margins | None,
) -> _Draft:
    """Plan one placement. ``id_done``: this sheet's ID label already went to an earlier page;
    ``mark_done``: so did its feed-direction mark."""
    view = p.sheet
    if view.state == "discarded":
        raise SheetDiscardedError()
    g = view.geometry
    total = cell_count(g)
    busy = set(view.non_free) | taken
    free = [n for n in range(1, total + 1) if n not in busy]
    skip = set(p.skip)
    needs_id_cell = (
        view.id_placement == "cell"
        and not view.id_printed
        and not view.has_hub_cell
        and not id_done
    )
    explicit = set(p.cells) if isinstance(p.cells, list) else set()

    if isinstance(p.cells, list):
        out = sorted(n for n in p.cells if n < 1 or n > total)
        if out:
            raise CellOutOfRangeError(out, total)
        if len(explicit) != len(p.cells):
            raise InvalidPlacementsError("duplicate_cells")
        not_free = sorted(n for n in p.cells if n in busy)
        if not_free:
            raise CellsTakenError(not_free)

    id_cell: int | None = None
    if needs_id_cell:
        id_cell = next((n for n in free if n not in skip and n not in explicit), None)
    id_missing = needs_id_cell and id_cell is None

    due = (
        view.id_placement == "margin"
        and not view.id_printed
        and not view.margin_id_in_flight
        and not id_done
    )
    margin_id = due
    placement: MarginPlacement | None = None
    id_not_printed = False
    # The mark has its own flag and is due for every ID placement (OC-56, OC-58). It is decided
    # before the margin ID, which then sees the shorter top band (OC-57).
    mark_due = not view.feed_mark_printed and not view.feed_mark_in_flight and not mark_done
    feed_mark: FeedMarkPlacement | None = None
    top_taken = 0
    if mark_due and margin is not None:
        feed_mark = choose_feed_mark(
            g,
            hw=hw_margins_hmm,
            dev=margin.deviation,
            text=feed_mark_text(margin.language),
        )
        if feed_mark is not None:
            top_taken = g.page_w - remaining_margins(g)[0] - feed_mark.x_hmm + MARGIN_TEXT_GAP_HMM
    if due and margin is not None:
        code = view.code or view.code_hint
        placement = choose_margin_placement(
            g,
            hw=hw_margins_hmm,
            dev=margin.deviation,
            payload=margin.scan_payload(code) if code else None,
            dpi=margin.render_dpi,
            top_taken_hmm=top_taken,
        )
        margin_id = placement is not None
        id_not_printed = placement is None

    if isinstance(p.cells, list):
        # Item i goes to cells[i]: the caller's order is kept.
        items = list(p.cells)
        available = len(items)
    else:
        pool = [n for n in free if n not in skip and n != id_cell]
        available = len(pool)
        items = pool[:count]
    enough = not id_missing and len(items) == count
    if not enough:
        items = []
    used = set(items) | ({id_cell} if id_cell is not None else set())
    return _Draft(
        placement=p,
        count=count,
        id_cell=id_cell,
        id_missing=id_missing,
        item_cells=items,
        margin_id=margin_id,
        available=available,
        free_after=len(free) - len(used),
        margin_placement=placement,
        id_not_printed=id_not_printed,
        id_was_due=due,
        feed_mark=feed_mark,
        mark_was_due=mark_due,
    )


def plan(
    placements: Sequence[PlacementIn],
    n_items: int,
    *,
    hw_margins_hmm: Margins | None,
    margin: MarginContext | None,
) -> Plan:
    """Fill ``placements`` in order with ``n_items`` items.

    ``n_items == 0`` is valid when an ID cell or a margin ID is due (an ID-only job); with
    nothing to print at all the request is ``empty``. ``margin=None`` means there is no printer
    context, so the band is not chosen (the ID is still due). A placement that would print
    nothing is ``empty_placement``.

    Caller contract: one ``SheetView`` object stands for one sheet. Passing the same object in
    several placements shares its cells and its ID label (the ID goes out once, on the sheet's
    first page); two distinct objects are two sheets, even if they carry the same code, and a
    new sheet must therefore get its own object. Explicit cell lists keep the caller's order.
    ``InsufficientCellsError.free_cells`` is the capacity left for items per placement, after
    skip and the ID cell; a missing ID cell adds one to ``shortfall``.
    """
    if not placements:
        raise InvalidPlacementsError("empty")
    counts = _resolve_counts(placements, n_items)

    taken_by_sheet: dict[int, set[int]] = {}
    id_done: set[int] = set()
    mark_done: set[int] = set()
    drafts: list[_Draft] = []
    for p, count in zip(placements, counts, strict=True):
        key = id(p.sheet)
        taken = taken_by_sheet.setdefault(key, set())
        d = _draft(p, count, taken, margin, key in id_done, key in mark_done, hw_margins_hmm)
        drafts.append(d)
        if d.id_missing or len(d.item_cells) != count:
            continue
        taken.update(d.item_cells)
        if d.id_cell is not None:
            taken.add(d.id_cell)
        if d.id_cell is not None or d.id_was_due:
            id_done.add(key)
        if d.mark_was_due:
            mark_done.add(key)

    short = [d for d in drafts if d.id_missing or len(d.item_cells) != d.count]
    if short:
        shortfall = sum(max(0, d.count - d.available) + int(d.id_missing) for d in short)
        raise InsufficientCellsError(
            [d.available for d in drafts], needed=n_items, shortfall=shortfall
        )

    for d in drafts:
        if not d.item_cells and d.id_cell is None and not d.margin_id:
            # n_items == 0 with nothing due is "empty"; otherwise a zero-count placement.
            raise InvalidPlacementsError("empty" if n_items == 0 else "empty_placement")
    if n_items == 0 and not any(d.id_cell is not None or d.margin_id for d in drafts):
        raise InvalidPlacementsError("empty")

    pages = [
        PagePlan(
            index=i,
            sheet=d.placement.sheet,
            item_cells=d.item_cells,
            id_cell=d.id_cell,
            margin_id=d.margin_id,
            hw_margin_cells=_hw_margin_cells(
                d.placement.sheet.geometry,
                d.item_cells + ([d.id_cell] if d.id_cell is not None else []),
                hw_margins_hmm,
            ),
            margin_placement=d.margin_placement,
            id_not_printed=d.id_not_printed,
            feed_mark=d.feed_mark,
        )
        for i, d in enumerate(drafts)
    ]
    return Plan(pages=pages, free_after=[d.free_after for d in drafts])
