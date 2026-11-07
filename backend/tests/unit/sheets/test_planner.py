from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Literal

import pytest
from app.page_render.transform import Deviation
from app.printer_backends.ipp.attributes import Margins
from app.sheets.errors import (
    CellOutOfRangeError,
    CellsTakenError,
    InsufficientCellsError,
    InvalidPlacementsError,
    MarginTooSmallError,
    SheetDiscardedError,
)
from app.sheets.geometry import Geometry
from app.sheets.planner import (
    MarginContext,
    PlacementIn,
    SheetView,
    margin_qr_fits,
    margin_usable_hmm,
    plan,
)

L4736 = Geometry("A4", 21000, 29700, 4570, 2120, 4, 12, 4820, 2120, 2130, 985, None, "rectangle")
L4731 = Geometry("A4", 21000, 29700, 2540, 1000, 7, 27, 2790, 1000, 1350, 860, 150, "rectangle")
TYPE_VERSION = uuid.UUID(int=1)


def sheet(
    geometry: Geometry = L4736,
    used: set[int] | None = None,
    *,
    id_placement: Literal["cell", "margin", "manual"] = "manual",
    id_printed: bool = False,
    has_hub_cell: bool = False,
    margin_id_in_flight: bool = False,
    state: Literal["active", "discarded"] = "active",
    code: str | None = "L4736-0001",
) -> SheetView:
    return SheetView(
        code=code,
        type_key="l4736rev",
        type_version_id=TYPE_VERSION,
        geometry=geometry,
        allow_qr=True,
        non_free=dict.fromkeys(used or set(), "used"),
        id_placement=id_placement,
        id_printed=id_printed,
        has_hub_cell=has_hub_cell,
        margin_id_in_flight=margin_id_in_flight,
        state=state,
    )


def first_free(
    view: SheetView, count: int | None = None, skip: list[int] | None = None
) -> PlacementIn:
    return PlacementIn(sheet=view, cells="first_free", skip=skip or [], count=count)


def margin_ctx(hw_top: int | None, dev: Deviation | None = None) -> MarginContext:
    return MarginContext(
        hw_top_hmm=hw_top,
        deviation=dev or Deviation(),
        scan_payload=lambda code: f"https://hub.example/sheet/{code}",
    )


def test_nine_into_seventeen_used() -> None:
    result = plan(
        [first_free(sheet(used=set(range(1, 18))), 9)], 9, hw_margins_hmm=None, margin=None
    )
    assert len(result.pages) == 1
    assert result.pages[0].item_cells == list(range(18, 27))
    assert result.free_after == [22]


def test_ordering_is_ascending_row_major_with_gaps() -> None:
    # Counter-check of the ordering rule: gaps are filled lowest first, never out of order.
    result = plan([first_free(sheet(used={2, 4}), 4)], 4, hw_margins_hmm=None, margin=None)
    assert result.pages[0].item_cells == [1, 3, 5, 6]


def test_gaps_and_skip() -> None:
    result = plan(
        [first_free(sheet(used={1, 2, 5}), 3, skip=[3])], 3, hw_margins_hmm=None, margin=None
    )
    assert result.pages[0].item_cells == [4, 6, 7]
    # A skipped cell stays free: it is not stored (OC-38).
    assert 3 not in result.pages[0].item_cells
    assert result.free_after == [42]


def test_skip_is_ignored_for_cells_that_are_not_free() -> None:
    result = plan(
        [first_free(sheet(used={1}), 2, skip=[1, 99])], 2, hw_margins_hmm=None, margin=None
    )
    assert result.pages[0].item_cells == [2, 3]


def test_insufficient() -> None:
    view = sheet(used=set(range(1, 18)))  # 31 free
    with pytest.raises(InsufficientCellsError) as exc:
        plan([first_free(view)], 40, hw_margins_hmm=None, margin=None)
    assert exc.value.status == 409
    assert exc.value.error_code == "insufficient_cells"
    assert exc.value.detail == {"free_cells": [31], "needed": 40, "shortfall": 9}


def test_overflow_goes_to_a_new_sheet() -> None:
    old = sheet(used=set(range(1, 18)))
    new = sheet(code=None)
    result = plan([first_free(old, 31), first_free(new)], 40, hw_margins_hmm=None, margin=None)
    assert [len(p.item_cells) for p in result.pages] == [31, 9]
    assert result.pages[0].item_cells == list(range(18, 49))
    assert result.pages[1].item_cells == list(range(1, 10))
    assert [p.index for p in result.pages] == [0, 1]
    assert result.free_after == [0, 39]


def test_skip_reduces_capacity() -> None:
    view = sheet(used=set(range(1, 47)))  # cells 47, 48 free
    with pytest.raises(InsufficientCellsError) as exc:
        plan([first_free(view, skip=[47])], 2, hw_margins_hmm=None, margin=None)
    assert exc.value.detail == {"free_cells": [1], "needed": 2, "shortfall": 1}


def test_explicit_cells() -> None:
    view = sheet(used={5})
    ok = plan(
        [PlacementIn(sheet=view, cells=[20, 21], skip=[], count=None)],
        2,
        hw_margins_hmm=None,
        margin=None,
    )
    assert ok.pages[0].item_cells == [20, 21]
    swapped = plan(
        [PlacementIn(sheet=view, cells=[21, 20], skip=[], count=None)],
        2,
        hw_margins_hmm=None,
        margin=None,
    )
    assert swapped.pages[0].item_cells == [21, 20]  # item i goes to cells[i]
    with pytest.raises(CellsTakenError) as taken:
        plan(
            [PlacementIn(sheet=view, cells=[5], skip=[], count=None)],
            1,
            hw_margins_hmm=None,
            margin=None,
        )
    assert taken.value.detail == {"cells": [5]}
    with pytest.raises(CellOutOfRangeError) as oor:
        plan(
            [PlacementIn(sheet=view, cells=[49], skip=[], count=None)],
            1,
            hw_margins_hmm=None,
            margin=None,
        )
    assert oor.value.detail == {"cells": [49], "max": 48}
    with pytest.raises(InvalidPlacementsError) as mismatch:
        plan(
            [PlacementIn(sheet=view, cells=[20, 21], skip=[], count=None)],
            3,
            hw_margins_hmm=None,
            margin=None,
        )
    assert mismatch.value.status == 422
    assert mismatch.value.detail == {"reason": "explicit_count_mismatch"}


def test_explicit_count_that_disagrees_with_the_list() -> None:
    with pytest.raises(InvalidPlacementsError) as exc:
        plan(
            [PlacementIn(sheet=sheet(), cells=[20, 21], skip=[], count=3)],
            3,
            hw_margins_hmm=None,
            margin=None,
        )
    assert exc.value.detail == {"reason": "explicit_count_mismatch"}


def test_explicit_duplicate_cells_rejected() -> None:
    with pytest.raises(InvalidPlacementsError) as exc:
        plan(
            [PlacementIn(sheet=sheet(), cells=[7, 7], skip=[], count=None)],
            2,
            hw_margins_hmm=None,
            margin=None,
        )
    assert exc.value.detail == {"reason": "duplicate_cells"}


def test_last_only_may_omit_count() -> None:
    with pytest.raises(InvalidPlacementsError) as exc:
        plan(
            [first_free(sheet(), None), first_free(sheet(code=None), 2)],
            4,
            hw_margins_hmm=None,
            margin=None,
        )
    assert exc.value.detail == {"reason": "count_missing_not_last"}
    result = plan(
        [first_free(sheet(), 3), first_free(sheet(code=None), None)],
        5,
        hw_margins_hmm=None,
        margin=None,
    )
    assert [len(p.item_cells) for p in result.pages] == [3, 2]


def test_counts_must_add_up_to_the_items() -> None:
    with pytest.raises(InvalidPlacementsError) as exc:
        plan([first_free(sheet(), 3)], 5, hw_margins_hmm=None, margin=None)
    assert exc.value.detail == {"reason": "count_mismatch"}


def test_empty_without_placements_or_anything_due() -> None:
    with pytest.raises(InvalidPlacementsError) as no_placements:
        plan([], 0, hw_margins_hmm=None, margin=None)
    assert no_placements.value.detail == {"reason": "empty"}
    # Zero items and nothing due (manual sheet): still empty.
    with pytest.raises(InvalidPlacementsError) as nothing_due:
        plan([first_free(sheet(), None)], 0, hw_margins_hmm=None, margin=None)
    assert nothing_due.value.detail == {"reason": "empty"}


def test_zero_items_is_valid_when_an_id_is_due() -> None:
    # C2: the ID-only job of a new cell sheet and of a margin sheet.
    cell = plan(
        [first_free(sheet(id_placement="cell", code=None), None)],
        0,
        hw_margins_hmm=None,
        margin=None,
    )
    assert cell.pages[0].item_cells == []
    assert cell.pages[0].id_cell == 1
    margin_only = plan(
        [first_free(sheet(id_placement="margin"), None)], 0, hw_margins_hmm=None, margin=None
    )
    assert margin_only.pages[0].item_cells == []
    assert margin_only.pages[0].margin_id is True


def test_id_cell_on_new_cell_sheet() -> None:
    view = sheet(id_placement="cell", code=None)
    result = plan([first_free(view, 3)], 3, hw_margins_hmm=None, margin=None)
    page = result.pages[0]
    assert page.id_cell == 1
    assert page.item_cells == [2, 3, 4]
    assert page.margin_id is False
    assert result.free_after == [44]
    hub = plan(
        [first_free(replace(view, has_hub_cell=True), 3)], 3, hw_margins_hmm=None, margin=None
    )
    assert hub.pages[0].id_cell is None
    assert hub.pages[0].item_cells == [1, 2, 3]
    printed = plan(
        [first_free(replace(view, id_printed=True), 3)], 3, hw_margins_hmm=None, margin=None
    )
    assert printed.pages[0].id_cell is None


def test_id_cell_is_lowest_free_non_skipped_and_counts_against_capacity() -> None:
    view = sheet(used={1}, id_placement="cell")
    result = plan([first_free(view, 2, skip=[2])], 2, hw_margins_hmm=None, margin=None)
    assert result.pages[0].id_cell == 3
    assert result.pages[0].item_cells == [4, 5]
    full = sheet(used=set(range(1, 47)), id_placement="cell")  # two free cells
    with pytest.raises(InsufficientCellsError) as exc:
        plan([first_free(full, 2)], 2, hw_margins_hmm=None, margin=None)
    assert exc.value.detail == {"free_cells": [1], "needed": 2, "shortfall": 1}


def test_id_cell_avoids_explicit_cells() -> None:
    view = sheet(id_placement="cell")
    result = plan(
        [PlacementIn(sheet=view, cells=[1, 2], skip=[], count=None)],
        2,
        hw_margins_hmm=None,
        margin=None,
    )
    assert result.pages[0].id_cell == 3
    assert result.pages[0].item_cells == [1, 2]


def test_margin_id_due_once() -> None:
    def due(**kw: object) -> bool:
        view = replace(sheet(id_placement="margin"), **kw)  # type: ignore[arg-type]
        return plan([first_free(view, 1)], 1, hw_margins_hmm=None, margin=None).pages[0].margin_id

    assert due() is True
    assert due(id_printed=True) is False
    assert due(margin_id_in_flight=True) is False
    # Only the margin option draws a margin ID.
    manual = plan([first_free(sheet(), 1)], 1, hw_margins_hmm=None, margin=None)
    assert manual.pages[0].margin_id is False


def test_discarded_sheet() -> None:
    with pytest.raises(SheetDiscardedError):
        plan([first_free(sheet(state="discarded"), 1)], 1, hw_margins_hmm=None, margin=None)


def test_margin_usable() -> None:
    assert margin_usable_hmm(L4731, hw_top_hmm=423, dev=Deviation(offset_y_hmm=-50)) == 777
    assert margin_usable_hmm(L4736, hw_top_hmm=None, dev=Deviation()) == 1530
    # A shift down (positive) does not give margin back.
    assert margin_usable_hmm(L4736, hw_top_hmm=None, dev=Deviation(offset_y_hmm=80)) == 1530
    assert margin_qr_fits(777, "https://hub.example/sheet/L4731-0001", 600) is False  # < 9 mm
    assert margin_qr_fits(1530, "https://hub.example/sheet/L4736-0001", 600) is True
    assert margin_qr_fits(1530, "x" * 3000, 600) is False  # no QR holds it at >= 0.25 mm


def test_margin_too_small_raises_only_when_an_id_is_due() -> None:
    narrow = replace(L4736, margin_top=800)
    view = sheet(narrow, id_placement="margin")
    with pytest.raises(MarginTooSmallError) as exc:
        plan([first_free(view, 1)], 1, hw_margins_hmm=None, margin=margin_ctx(500))
    assert (exc.value.status, exc.value.error_code) == (422, "margin_too_small")
    assert exc.value.detail == {"usable_mm": 2.0}
    # margin=None: availability is not checked.
    plan([first_free(view, 1)], 1, hw_margins_hmm=None, margin=None)
    # ID already printed: nothing to draw, so no error.
    plan(
        [first_free(replace(view, id_printed=True), 1)],
        1,
        hw_margins_hmm=None,
        margin=margin_ctx(500),
    )
    # Enough room.
    plan(
        [first_free(sheet(id_placement="margin"), 1)],
        1,
        hw_margins_hmm=None,
        margin=margin_ctx(None),
    )


def test_hw_margin_flags() -> None:
    synthetic = replace(L4736, margin_top=0, pitch_y=2120)
    hw = Margins(top=423, left=0, bottom=0, right=0)
    result = plan([first_free(sheet(synthetic), 6)], 6, hw_margins_hmm=hw, margin=None)
    assert result.pages[0].item_cells == [1, 2, 3, 4, 5, 6]
    assert result.pages[0].hw_margin_cells == [1, 2, 3, 4]  # first row only
    # Real L4736REV top margin 21.3 mm clears a 4.23 mm band.
    clear = plan([first_free(sheet(), 6)], 6, hw_margins_hmm=hw, margin=None)
    assert clear.pages[0].hw_margin_cells == []
    none = plan([first_free(sheet(synthetic), 6)], 6, hw_margins_hmm=None, margin=None)
    assert none.pages[0].hw_margin_cells == []


def test_hw_margin_flags_other_sides_and_id_cell() -> None:
    hw = Margins(top=0, left=1000, bottom=0, right=0)  # left band 10 mm; margin_left is 9.85
    result = plan([first_free(sheet(id_placement="cell"), 4)], 4, hw_margins_hmm=hw, margin=None)
    page = result.pages[0]
    assert page.id_cell == 1
    assert page.hw_margin_cells == [1, 5]  # id cell 1 and item cell 5 (column 1, row 2)


def test_id_cell_once_per_sheet_when_the_sheet_is_in_two_placements() -> None:
    view = sheet(id_placement="cell", code=None)
    result = plan(
        [first_free(view, 2), first_free(view, None)], 5, hw_margins_hmm=None, margin=None
    )
    assert [p.id_cell for p in result.pages] == [1, None]
    assert result.pages[0].item_cells == [2, 3]
    assert result.pages[1].item_cells == [4, 5, 6]


def test_margin_id_once_per_sheet_when_the_sheet_is_in_two_placements() -> None:
    view = sheet(id_placement="margin")
    result = plan(
        [first_free(view, 2), first_free(view, None)], 4, hw_margins_hmm=None, margin=None
    )
    assert [p.margin_id for p in result.pages] == [True, False]


def test_full_cell_sheet_with_id_due_and_no_items_is_insufficient() -> None:
    full = sheet(used=set(range(1, 49)), id_placement="cell")
    with pytest.raises(InsufficientCellsError) as exc:
        plan([first_free(full, None)], 0, hw_margins_hmm=None, margin=None)
    assert exc.value.detail == {"free_cells": [0], "needed": 0, "shortfall": 1}


def test_zero_count_placement_never_yields_an_empty_page() -> None:
    full = sheet(used=set(range(1, 49)), id_placement="cell")
    with pytest.raises(InsufficientCellsError):
        plan(
            [first_free(full, 0), first_free(sheet(code=None), None)],
            3,
            hw_margins_hmm=None,
            margin=None,
        )
    with pytest.raises(InvalidPlacementsError) as exc:
        plan(
            [first_free(sheet(), 0), first_free(sheet(code=None), None)],
            3,
            hw_margins_hmm=None,
            margin=None,
        )
    assert exc.value.detail == {"reason": "empty_placement"}
    # A zero-count placement is fine when it carries the margin ID.
    ok = plan(
        [first_free(sheet(id_placement="margin"), 0), first_free(sheet(code=None), None)],
        3,
        hw_margins_hmm=None,
        margin=None,
    )
    assert ok.pages[0].margin_id is True


def test_hw_margin_flags_bottom_and_right_bands() -> None:
    # L4736REV leaves 21.3 mm at the bottom and 9.85 mm at the right.
    last_row = [45, 46, 47, 48]
    bottom = Margins(top=0, left=0, bottom=2200, right=0)
    result = plan(
        [first_free(sheet(used=set(range(1, 45))), 4)], 4, hw_margins_hmm=bottom, margin=None
    )
    assert result.pages[0].hw_margin_cells == last_row
    ok = Margins(top=0, left=0, bottom=2100, right=0)
    result = plan([first_free(sheet(used=set(range(1, 45))), 4)], 4, hw_margins_hmm=ok, margin=None)
    assert result.pages[0].hw_margin_cells == []
    right = Margins(top=0, left=0, bottom=0, right=1000)
    result = plan([first_free(sheet(), 4)], 4, hw_margins_hmm=right, margin=None)
    assert result.pages[0].hw_margin_cells == [4]


def test_reserved_and_unconfirmed_cells_are_not_free() -> None:
    view = sheet()
    view.non_free.update({1: "reserved", 2: "unconfirmed"})
    result = plan([first_free(view, 2)], 2, hw_margins_hmm=None, margin=None)
    assert result.pages[0].item_cells == [3, 4]


def test_five_hundred_items_over_eleven_sheets() -> None:
    placements = [first_free(sheet(code=None), 48) for _ in range(10)]
    placements.append(first_free(sheet(code=None), None))
    result = plan(placements, 500, hw_margins_hmm=None, margin=None)
    assert sum(len(p.item_cells) for p in result.pages) == 500
    assert result.free_after[-1] == 28
