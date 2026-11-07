"""Pure placement planner: which items go into which cells (spec 8, 10.1, 10.2).

Decides ``first_free`` and explicit placements, skipped cells, overflow onto further sheets,
the ID cell and the margin ID. It reads ``SheetView`` values and writes nothing; reserving the
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

from app.page_render.transform import Deviation
from app.printer_backends.ipp.attributes import Margins
from app.sheets.cell_render import qr_edge_px
from app.sheets.errors import (
    CellOutOfRangeError,
    CellsTakenError,
    InsufficientCellsError,
    InvalidPlacementsError,
    MarginTooSmallError,
    SheetDiscardedError,
)
from app.sheets.geometry import Geometry, cell_count, cell_origin, hmm_to_mm

__all__ = [
    "MarginContext",
    "PagePlan",
    "PlacementIn",
    "Plan",
    "SheetView",
    "margin_qr_allowed",
    "margin_qr_fits",
    "margin_usable_hmm",
    "plan",
]

DEFAULT_HW_TOP_HMM: Final = 500  # 5.0 mm assumed when the printer does not report it (OC-16)
SAFETY_HMM: Final = 100  # 1.0 mm
MIN_MARGIN_TEXT_HMM: Final = 400  # below: margin ID impossible
MIN_MARGIN_QR_HMM: Final = 900  # from here a QR may sit next to the text
MIN_QR_MODULE_HMM: Final = 25  # 0.25 mm
_QUIET_MODULES: Final = 4


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


@dataclass
class Plan:
    pages: list[PagePlan]
    # Per page: how many cells of its sheet are still free afterwards. Skipped cells stay free
    # (skip is never stored, OC-38).
    free_after: list[int]


@dataclass(frozen=True)
class MarginContext:
    hw_top_hmm: int | None
    deviation: Deviation
    scan_payload: Callable[[str], str]


def margin_usable_hmm(g: Geometry, *, hw_top_hmm: int | None, dev: Deviation) -> int:
    """Height available for the margin ID: ``margin_top`` minus the printer's hardware top
    margin (5 mm if unknown), minus a calibration shift upwards, minus 1 mm of safety."""
    hw = DEFAULT_HW_TOP_HMM if hw_top_hmm is None else hw_top_hmm
    return g.margin_top - hw - max(0, -dev.offset_y_hmm) - SAFETY_HMM


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


def _draft(
    p: PlacementIn,
    count: int,
    taken: set[int],
    margin: MarginContext | None,
    id_done: bool,
) -> _Draft:
    """Plan one placement. ``id_done``: this sheet's ID label already went to an earlier page."""
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

    margin_id = (
        view.id_placement == "margin"
        and not view.id_printed
        and not view.margin_id_in_flight
        and not id_done
    )
    if margin_id and margin is not None:
        usable = margin_usable_hmm(g, hw_top_hmm=margin.hw_top_hmm, dev=margin.deviation)
        if usable < MIN_MARGIN_TEXT_HMM:
            raise MarginTooSmallError(hmm_to_mm(usable))

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
    context, so margin availability is not checked. A placement that would print nothing is
    ``empty_placement``.

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
    drafts: list[_Draft] = []
    for p, count in zip(placements, counts, strict=True):
        key = id(p.sheet)
        taken = taken_by_sheet.setdefault(key, set())
        d = _draft(p, count, taken, margin, key in id_done)
        drafts.append(d)
        if d.id_missing or len(d.item_cells) != count:
            continue
        taken.update(d.item_cells)
        if d.id_cell is not None:
            taken.add(d.id_cell)
        if d.id_cell is not None or d.margin_id:
            id_done.add(key)

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
        )
        for i, d in enumerate(drafts)
    ]
    return Plan(pages=pages, free_after=[d.free_after for d in drafts])
