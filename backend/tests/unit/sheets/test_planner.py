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
    SheetDiscardedError,
)
from app.sheets.geometry import Geometry
from app.sheets.planner import (
    MarginContext,
    MarginPlacement,
    PlacementIn,
    SheetView,
    band_length_hmm,
    choose_margin_placement,
    margin_bands_hmm,
    margin_qr_allowed,
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
    feed_mark_printed: bool = False,
    feed_mark_in_flight: bool = False,
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
        feed_mark_printed=feed_mark_printed,
        feed_mark_in_flight=feed_mark_in_flight,
    )


def first_free(
    view: SheetView, count: int | None = None, skip: list[int] | None = None
) -> PlacementIn:
    return PlacementIn(sheet=view, cells="first_free", skip=skip or [], count=count)


def margin_ctx(
    dev: Deviation | None = None, dpi: int = 600, language: str | None = None
) -> MarginContext:
    return MarginContext(
        deviation=dev or Deviation(),
        scan_payload=lambda code: f"https://hub.example/sheet/{code}",
        render_dpi=dpi,
        language=language,
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


PAYLOAD = "https://hub.example/sheet/L4736-0001"


def _syn(**kw: int) -> Geometry:
    """A synthetic A4 type; every field can be overridden."""
    base: dict[str, int] = {
        "label_w": 4000,
        "label_h": 2000,
        "cols": 4,
        "rows": 13,
        "pitch_x": 4600,
        "pitch_y": 2050,
        "margin_top": 600,
        "margin_left": 600,
    }
    base.update(kw)
    return Geometry(
        "A4",
        21000,
        29700,
        base["label_w"],
        base["label_h"],
        base["cols"],
        base["rows"],
        base["pitch_x"],
        base["pitch_y"],
        base["margin_top"],
        base["margin_left"],
        None,
        "rectangle",
    )


TIGHT = Geometry("A4", 21000, 29700, 19900, 28600, 1, 1, 19900, 28600, 550, 550, None, "rectangle")


def _bands(g: Geometry, hw: Margins | None, dev: Deviation | None = None) -> list[int]:
    b = margin_bands_hmm(g, hw=hw, dev=dev or Deviation())
    assert list(b) == ["top", "bottom", "right", "left"]
    return list(b.values())


def test_margin_bands_l4736_unknown_hw() -> None:
    assert _bands(L4736, None) == [1530, 1530, 385, 385]


def test_margin_bands_per_side_hw_and_calibration() -> None:
    hw = Margins(top=423, left=300, bottom=600, right=450)
    assert _bands(L4736, hw, Deviation(offset_x_hmm=120, offset_y_hmm=-80)) == [
        1527,
        1350,
        315,
        465,
    ]
    # The sign of the shift does not matter (ruling A-1).
    assert _bands(L4736, hw, Deviation(offset_x_hmm=-120, offset_y_hmm=80)) == [
        1527,
        1350,
        315,
        465,
    ]
    assert _bands(L4736, hw, Deviation(offset_x_hmm=-50, offset_y_hmm=30)) == [
        1577,
        1400,
        385,
        535,
    ]
    assert _bands(
        L4731, Margins(top=423, left=423, bottom=423, right=423), Deviation(offset_y_hmm=-50)
    ) == [
        777,
        777,
        337,
        337,
    ]


def test_margin_bands_dy_minus_0_8() -> None:
    dev = Deviation(offset_y_hmm=-80)
    full = Margins(top=423, left=423, bottom=423, right=423)
    assert _bands(L4736, None, dev) == [1450, 1450, 385, 385]
    assert _bands(L4736, full, dev) == [1527, 1527, 462, 462]
    assert _bands(L4731, None, dev) == [670, 670, 260, 260]
    assert _bands(L4731, full, dev) == [747, 747, 337, 337]
    cases = [
        (L4736, None, MarginPlacement("top", "top_left", 1450, True)),
        (L4736, full, MarginPlacement("top", "top_left", 1527, True)),
        (L4731, None, MarginPlacement("top", "top_left", 670, False)),
        (L4731, full, MarginPlacement("top", "top_left", 747, False)),
    ]
    for g, hw, want in cases:
        got = choose_margin_placement(g, hw=hw, dev=dev, payload=PAYLOAD, dpi=600)
        assert got == want


def test_band_length() -> None:
    assert [band_length_hmm(L4736, b) for b in ("top", "bottom", "right", "left")] == [
        19030,
        19030,
        25440,
        25440,
    ]


def _choose(
    g: Geometry,
    hw: Margins | None = None,
    dev: Deviation | None = None,
    payload: str | None = PAYLOAD,
    dpi: int = 600,
) -> MarginPlacement | None:
    return choose_margin_placement(g, hw=hw, dev=dev or Deviation(), payload=payload, dpi=dpi)


def test_choose_top_on_l4736_with_qr() -> None:
    assert _choose(L4736) == MarginPlacement("top", "top_left", 1530, True)


def test_choose_bottom_when_the_printer_clips_more_at_the_top() -> None:
    hw = Margins(top=600, left=500, bottom=423, right=500)
    assert _choose(L4736, hw) == MarginPlacement("bottom", "bottom_left", 1607, True)
    got = _choose(L4736, hw, Deviation(offset_y_hmm=-80))
    assert got == MarginPlacement("bottom", "bottom_left", 1527, True)


def test_vertical_band_needs_a_two_mm_lead() -> None:
    payload = "https://hub.example/sheet/LEAD-0001"
    assert margin_qr_allowed(1800, payload, 600) is True
    g = _syn(margin_top=2401)
    assert _bands(g, None) == [1801, 99, 2000, 0]
    assert _choose(g, payload=payload) == MarginPlacement("top", "top_left", 1801, True)
    g = _syn(margin_top=2400)
    assert _bands(g, None)[:3] == [1800, 100, 2000]
    assert _choose(g, payload=payload) == MarginPlacement("right", "top_right", 2000, True)


def test_usable_size_capped_at_twenty_mm() -> None:
    g = replace(L4736, rows=10)
    assert _bands(g, None)[:2] == [1530, 5770]
    assert _choose(g) == MarginPlacement("bottom", "bottom_left", 2000, True)
    g = replace(g, margin_top=3000)
    assert _bands(g, None)[:2] == [2400, 4900]
    assert _choose(g) == MarginPlacement("top", "top_left", 2000, True)


def test_choose_right_on_wide_right_margin() -> None:
    g = _syn(rows=14, margin_top=600, margin_left=600)
    assert _bands(g, None) == [0, -150, 2000, 0]
    assert _choose(g) == MarginPlacement("right", "top_right", 2000, True)


def test_qr_band_beats_a_larger_text_only_band() -> None:
    payload = "https://hub.example/sheet/TEST-0001"
    g = _syn(
        label_w=2500,
        label_h=2500,
        cols=1,
        rows=1,
        pitch_x=2500,
        pitch_y=2500,
        margin_top=1700,
        margin_left=1000,
    )
    assert margin_qr_allowed(1100, payload, 600) is True
    assert _bands(g, None) == [1100, 24900, 16900, 400]
    assert _choose(g, payload=payload) == MarginPlacement("top", "top_left", 1100, True)


def test_text_only_from_four_mm() -> None:
    hw = Margins(top=1630, left=500, bottom=1630, right=500)
    assert _choose(L4736, hw) == MarginPlacement("top", "top_left", 400, False)
    hw = Margins(top=1631, left=500, bottom=1631, right=500)
    assert _choose(L4736, hw) is None


def test_l4731_text_only_on_typical_laser() -> None:
    got = _choose(L4731, Margins(top=423, left=423, bottom=423, right=423))
    assert got == MarginPlacement("top", "top_left", 827, False)
    assert margin_qr_allowed(950, PAYLOAD, 600) is True
    got = _choose(L4731, Margins(top=300, left=300, bottom=300, right=300))
    assert got == MarginPlacement("top", "top_left", 950, True)


def test_no_payload_means_text_only() -> None:
    assert _choose(L4736, payload=None) == MarginPlacement("top", "top_left", 1530, False)


def test_plan_carries_margin_placement() -> None:
    view = sheet(id_placement="margin")
    page = plan([first_free(view, 1)], 1, hw_margins_hmm=None, margin=margin_ctx()).pages[0]
    assert page.margin_id is True
    assert page.margin_placement == MarginPlacement("top", "top_left", 1530, True)
    assert page.id_not_printed is False


def test_plan_margin_unprintable_prints_without_id() -> None:
    view = sheet(TIGHT, id_placement="margin")
    page = plan([first_free(view, 1)], 1, hw_margins_hmm=None, margin=margin_ctx()).pages[0]
    assert page.item_cells == [1]
    assert page.margin_id is False
    assert page.margin_placement is None
    assert page.id_not_printed is True
    # Without a printer context nothing is checked.
    page = plan([first_free(view, 1)], 1, hw_margins_hmm=None, margin=None).pages[0]
    assert page.margin_id is True
    assert page.margin_placement is None
    assert page.id_not_printed is False


def test_unprintable_flag_once_per_sheet() -> None:
    view = sheet(id_placement="margin")
    result = plan(
        [first_free(view, 1), first_free(view, 1)],
        2,
        hw_margins_hmm=Margins(top=2000, left=2000, bottom=2000, right=2000),
        margin=margin_ctx(),
    )
    assert [p.id_not_printed for p in result.pages] == [True, False]


def test_unprintable_margin_id_alone_is_empty() -> None:
    view = sheet(TIGHT, id_placement="margin")
    with pytest.raises(InvalidPlacementsError) as exc:
        plan([first_free(view, None)], 0, hw_margins_hmm=None, margin=margin_ctx())
    assert exc.value.detail == {"reason": "empty"}


def test_payload_code_falls_back_to_code_hint() -> None:
    seen: list[str] = []

    def record(code: str) -> str:
        seen.append(code)
        return f"https://hub.example/sheet/{code}"

    ctx = MarginContext(deviation=Deviation(), scan_payload=record, render_dpi=600, language=None)
    view = replace(sheet(id_placement="margin", code=None), code_hint="L4736-0003")
    plan([first_free(view, 1)], 1, hw_margins_hmm=None, margin=ctx)
    assert seen == ["L4736-0003"]
    seen.clear()
    bare = sheet(id_placement="margin", code=None)
    page = plan([first_free(bare, 1)], 1, hw_margins_hmm=None, margin=ctx).pages[0]
    assert seen == []
    assert page.margin_placement is not None and page.margin_placement.qr is False


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
    # Not even when it would carry the margin ID: nothing records that (R10-3, spec OC-58: the
    # mark and the ID never cause a job by themselves).
    with pytest.raises(InvalidPlacementsError) as margin_exc:
        plan(
            [first_free(sheet(id_placement="margin"), 0), first_free(sheet(code=None), None)],
            3,
            hw_margins_hmm=None,
            margin=None,
        )
    assert margin_exc.value.detail == {"reason": "empty_placement"}


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


# ---------------------------------------------------------------- feed-direction mark (Task 5c)
# The names are read from the module at call time, so each test fails on its own.

EN_MARK = "▲ Top \u2013 this edge first"
DE_MARK = "▲ Oben \u2013 diese Kante zuerst"


def _one_cell_type(label_w: int, label_h: int = 2000) -> Geometry:
    return Geometry(
        "A4", 21000, 29700, label_w, label_h, 1, 1, label_w, label_h, 1700, 1000, None, "rectangle"
    )


def test_font_has_the_mark_glyphs() -> None:
    from app.page_render.pdf import resolve_font_path
    from reportlab.pdfbase.ttfonts import TTFont

    cmap = TTFont("mark-font-probe", str(resolve_font_path())).face.charToGlyph
    assert 0x25B2 in cmap and 0x2013 in cmap


def test_feed_mark_text_per_language() -> None:
    from app.sheets import planner

    assert planner.feed_mark_text("de") == DE_MARK
    assert planner.feed_mark_text("en") == EN_MARK
    for other in ("fr", "", "DE", None):
        assert planner.feed_mark_text(other) == EN_MARK


def test_feed_mark_l4736() -> None:
    from app.sheets import planner

    got = planner.choose_feed_mark(L4736, hw=None, dev=Deviation(), text=EN_MARK)
    assert got == planner.FeedMarkPlacement(EN_MARK, 17300, 1354, 7.0, 2715)


def test_feed_mark_l4736_de() -> None:
    from app.sheets import planner

    got = planner.choose_feed_mark(L4736, hw=None, dev=Deviation(), text=DE_MARK)
    assert got == planner.FeedMarkPlacement(DE_MARK, 16508, 1354, 7.0, 3507)
    seen: list[int] = []
    real = planner.choose_margin_placement

    def spy(*a: object, **kw: object) -> object:
        seen.append(planner.band_length_hmm(L4736, "top") - int(kw.get("top_taken_hmm", 0)))
        return real(*a, **kw)  # type: ignore[arg-type]

    import pytest as _pytest

    with _pytest.MonkeyPatch.context() as mp:
        mp.setattr(planner, "choose_margin_placement", spy)
        page = plan(
            [first_free(sheet(id_placement="margin"), 1)],
            1,
            hw_margins_hmm=None,
            margin=margin_ctx(language="de"),
        ).pages[0]
    assert page.feed_mark is not None and page.feed_mark.text == DE_MARK
    assert seen == [19030 - 3507 - 200]
    assert page.margin_placement is not None and page.margin_placement.qr is True
    fr = plan(
        [first_free(sheet(), 1)], 1, hw_margins_hmm=None, margin=margin_ctx(language="fr")
    ).pages[0]
    assert fr.feed_mark == planner.FeedMarkPlacement(EN_MARK, 17300, 1354, 7.0, 2715)


def test_feed_mark_stops_at_the_right_hardware_margin() -> None:
    from app.sheets import planner

    wide = Margins(top=500, left=500, bottom=500, right=1000)
    got = planner.choose_feed_mark(L4736, hw=wide, dev=Deviation(), text=EN_MARK)
    assert got is not None and got.x_hmm == 17185  # right end 19900
    got = planner.choose_feed_mark(
        L4736,
        hw=Margins(top=500, left=500, bottom=500, right=500),
        dev=Deviation(offset_x_hmm=-120),
        text=EN_MARK,
    )
    assert got is not None and got.x_hmm == 17300  # right end min(20015, 20280)


def test_feed_mark_not_printed_below_four_mm() -> None:
    from app.sheets import planner

    thin = Margins(top=1631, left=500, bottom=500, right=500)
    assert planner.choose_feed_mark(L4736, hw=thin, dev=Deviation(), text=EN_MARK) is None
    got = plan(
        [first_free(sheet(id_placement="margin"), 1)],
        1,
        hw_margins_hmm=thin,
        margin=margin_ctx(),
    ).pages[0]
    assert got.feed_mark is None
    assert got.margin_placement == MarginPlacement("bottom", "bottom_left", 1530, True)
    ok = Margins(top=1630, left=500, bottom=500, right=500)
    mark = planner.choose_feed_mark(L4736, hw=ok, dev=Deviation(), text=EN_MARK)
    assert mark is not None and mark.baseline_y_hmm == round(1830 + 88.9) == 1919


def test_feed_mark_shrinks_then_drops() -> None:
    from app.sheets import planner

    def mark(label_w: int, text: str) -> object:
        return planner.choose_feed_mark(
            _one_cell_type(label_w), hw=None, dev=Deviation(), text=text
        )

    en = mark(2400, EN_MARK)
    assert en == planner.FeedMarkPlacement(EN_MARK, 1073, en.baseline_y_hmm, 6.0, 2327)
    assert mark(2300, EN_MARK) is None
    de = mark(3200, DE_MARK)
    assert (de.size_pt, de.width_hmm, de.x_hmm) == (6.0, 3006, 1194)
    assert mark(3000, DE_MARK) is None
    assert mark(3000, EN_MARK) is not None and mark(3000, EN_MARK).size_pt == 7.0


def test_id_shares_the_top_band_with_the_mark() -> None:
    from app.sheets import planner

    page = plan(
        [first_free(sheet(id_placement="margin"), 1)], 1, hw_margins_hmm=None, margin=margin_ctx()
    ).pages[0]
    assert page.feed_mark.x_hmm == 17300
    assert page.margin_placement == MarginPlacement("top", "top_left", 1530, True)

    def tight(label_w: int, label_h: int = 27000) -> Geometry:
        return Geometry(
            "A4", 21000, 29700, label_w, label_h, 1, 1, label_w, label_h, 1700, 1000, None,
            "rectangle",
        )  # fmt: skip

    g = tight(4600)
    hw = Margins(top=500, left=500, bottom=500, right=16000)
    assert margin_bands_hmm(g, hw=hw, dev=Deviation()) == {
        "top": 1100, "bottom": 400, "right": -700, "left": 400,
    }  # fmt: skip
    mark = planner.choose_feed_mark(g, hw=hw, dev=Deviation(), text=EN_MARK)
    assert mark == planner.FeedMarkPlacement(EN_MARK, 2185, 1139, 7.0, 2715)
    args = {"hw": hw, "dev": Deviation(), "payload": "https://hub.example/sheet/X", "dpi": 600}
    assert choose_margin_placement(g, **args) == MarginPlacement("top", "top_left", 1100, True)
    taken = 5600 - 2185 + 200
    got = choose_margin_placement(g, **args, top_taken_hmm=taken)  # type: ignore[arg-type]
    assert got == MarginPlacement("top", "top_left", 1100, False)  # 4600 - 3615 = 985

    g2 = tight(6000)
    hw2 = Margins(top=500, left=500, bottom=500, right=14900)
    assert margin_bands_hmm(g2, hw=hw2, dev=Deviation()) == {
        "top": 1100, "bottom": 400, "right": -1000, "left": 400,
    }  # fmt: skip
    mark2 = planner.choose_feed_mark(g2, hw=hw2, dev=Deviation(), text=EN_MARK)
    assert mark2 is not None and mark2.x_hmm == 3285
    result = plan(
        [first_free(sheet(g2, id_placement="margin"), 1)], 1, hw_margins_hmm=hw2,
        margin=margin_ctx(),
    ).pages[0]  # fmt: skip
    assert result.margin_placement == MarginPlacement("top", "top_left", 1100, False)
    # 7000 - 3285 + 200 = 3915 -> 2085 < 2300; "width + gap" would leave 3085 and a QR
    assert 6000 - (7000 - 3285 + 200) == 2085


def test_feed_mark_for_every_placement() -> None:
    def marks(view: SheetView, n_pages: int = 1) -> list[object]:
        pls = [first_free(view, 1) for _ in range(n_pages)]
        pages = plan(pls, n_pages, hw_margins_hmm=None, margin=margin_ctx()).pages
        return [p.feed_mark for p in pages]

    for placement in ("cell", "margin", "manual"):
        (m,) = marks(sheet(id_placement=placement))  # type: ignore[arg-type]
        assert m is not None, placement
        assert marks(sheet(id_placement=placement, feed_mark_printed=True)) == [None]  # type: ignore[arg-type]
        assert marks(sheet(id_placement=placement, feed_mark_in_flight=True)) == [None]  # type: ignore[arg-type]
    # the ID is printed already; the mark is still due (its own flag)
    assert marks(sheet(id_placement="margin", id_printed=True))[0] is not None
    first, second = marks(sheet(), 2)
    assert first is not None and second is None
    assert (
        plan([first_free(sheet(), 1)], 1, hw_margins_hmm=None, margin=None).pages[0].feed_mark
        is None
    )


def test_feed_mark_alone_is_empty() -> None:
    with pytest.raises(InvalidPlacementsError) as exc:
        plan([first_free(sheet(), None)], 0, hw_margins_hmm=None, margin=margin_ctx())
    assert exc.value.detail == {"reason": "empty"}


def test_margin_context_language_is_required() -> None:
    with pytest.raises(TypeError):
        MarginContext(deviation=Deviation(), scan_payload=str, render_dpi=600)  # type: ignore[call-arg]


def test_id_leaves_a_top_band_the_mark_has_used_up() -> None:
    """Fix round 1, I1 (spec 10.2a: the ID chooses with the shorter band like any other)."""
    narrow = Geometry(
        "A4", 4000, 29700, 3000, 2600, 1, 10, 3000, 2700, 1700, 500, None, "rectangle"
    )
    page = plan(
        [first_free(sheet(narrow, id_placement="margin"), 1)],
        1,
        hw_margins_hmm=None,
        margin=margin_ctx(),
    ).pages[0]
    assert page.feed_mark is not None and page.feed_mark.x_hmm == 685
    assert page.margin_placement is not None and page.margin_placement.band == "bottom"
    # without the mark (already printed) the top band is the ID's again
    again = plan(
        [first_free(sheet(narrow, id_placement="margin", feed_mark_printed=True), 1)],
        1,
        hw_margins_hmm=None,
        margin=margin_ctx(),
    ).pages[0]
    assert again.margin_placement is not None and again.margin_placement.band == "top"


# ---- R10-2: planning is cheap enough to run while the write lock is held -----------------


def _reference_qr_allowed(usable_hmm: int, payload: str, dpi: int) -> bool:
    """The original decision: build the whole symbol (mask search included) and count modules."""
    import qrcode
    import qrcode.constants
    from app.sheets.cell_render import qr_edge_px

    if usable_hmm < 900 or dpi <= 0:
        return False
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0)
    try:
        qr.add_data(payload)
        qr.make(fit=True)
    except (qrcode.exceptions.DataOverflowError, ValueError):
        return False
    edge = qr_edge_px(usable_hmm / 100, usable_hmm / 100, dpi)
    module_px = edge // (len(qr.get_matrix()) + 2 * 4)
    return module_px >= 1 and module_px * 2540 >= 25 * dpi


@pytest.mark.parametrize("dpi", [150, 300, 600])
@pytest.mark.parametrize("usable", [900, 1100, 1500, 2000])
@pytest.mark.parametrize(
    "payload",
    [
        "L4736-0001",
        "https://hub.example/sheet/L4736-0001",
        "https://hub.example/sheet/" + "x" * 120,
        "https://hub.example/s/" + "A1" * 300,
        "äöü" * 40,
        "9" * 200,
        "x" * 5000,  # more than any symbol holds
    ],
)
def test_margin_qr_decision_equals_the_full_symbol_decision(
    payload: str, usable: int, dpi: int
) -> None:
    assert margin_qr_allowed(usable, payload, dpi) is _reference_qr_allowed(usable, payload, dpi)


def test_planning_builds_no_qr_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    """R10-2: the plan runs under the global write lock; a full QR build (eight masks) per page
    cost about 15 ms each. The fit decision needs only the symbol size."""
    import qrcode

    built: list[int] = []
    real = qrcode.QRCode.make

    def counting(self: qrcode.QRCode, fit: bool = True) -> None:  # type: ignore[type-arg]
        built.append(1)
        real(self, fit)

    monkeypatch.setattr(qrcode.QRCode, "make", counting)
    views = [sheet(code=f"L4736-{n:04d}", id_placement="margin") for n in range(1, 21)]
    plan(
        [first_free(v, 1) for v in views],
        20,
        hw_margins_hmm=None,
        margin=margin_ctx(),
    )
    assert built == []


# ---- R10-3: a page without cells is refused when there is something to print -----------------


def test_a_cell_less_page_of_a_margin_sheet_is_refused() -> None:
    """R10-3: ``cells: []`` on a margin sheet gave a page with only the ID and the feed mark.
    Both are recorded when a cell turns used, and a cell-less page has none, so the next print
    drew them again. The request is refused; nothing is printed unrecorded."""
    first = sheet(code="L4736-0001", id_placement="margin")
    second = sheet(code="L4736-0002", id_placement="margin")
    with pytest.raises(InvalidPlacementsError) as exc:
        plan(
            [
                PlacementIn(sheet=first, cells=[]),
                first_free(second, None),
            ],
            2,
            hw_margins_hmm=None,
            margin=margin_ctx(),
        )
    assert exc.value.detail == {"reason": "empty_placement"}


def test_a_cell_less_page_is_refused_without_a_printer_context_too() -> None:
    with pytest.raises(InvalidPlacementsError) as exc:
        plan(
            [
                PlacementIn(sheet=sheet(id_placement="margin"), cells=[]),
                first_free(sheet(code="L4736-0002"), None),
            ],
            1,
            hw_margins_hmm=None,
            margin=None,
        )
    assert exc.value.detail == {"reason": "empty_placement"}


def test_an_id_only_page_is_still_planned_when_there_are_no_items() -> None:
    """C2 stays: the ID-only job of a margin or cell sheet (``n_items == 0``) is not a
    cell-less page of a print, it is the job itself."""
    result = plan(
        [first_free(sheet(id_placement="margin"), None)],
        0,
        hw_margins_hmm=None,
        margin=margin_ctx(),
    )
    assert result.pages[0].item_cells == [] and result.pages[0].margin_id is True


def test_free_cells_for_explicit_list() -> None:
    """266-01: an explicit list with no room for the ID reports the capacity left for items
    once the ID takes its cell, like a ``first_free`` placement does, not the list's length."""
    full = sheet(used=set(range(1, 47)), id_placement="cell")  # cells 47 and 48 free
    explicit = PlacementIn(sheet=full, cells=[47, 48], skip=[], count=None)
    with pytest.raises(InsufficientCellsError) as exc:
        plan([explicit], 2, hw_margins_hmm=None, margin=None)
    auto = sheet(used=set(range(1, 47)), id_placement="cell")
    with pytest.raises(InsufficientCellsError) as same:
        plan([first_free(auto, 2)], 2, hw_margins_hmm=None, margin=None)
    assert (
        exc.value.detail
        == same.value.detail
        == {
            "free_cells": [1],
            "needed": 2,
            "shortfall": 1,
        }
    )
