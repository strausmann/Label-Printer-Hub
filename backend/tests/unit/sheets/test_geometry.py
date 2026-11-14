# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest
from app.sheets.errors import CellOutOfRangeError, InvalidGeometryError
from app.sheets.geometry import (
    Geometry,
    cell_count,
    cell_origin,
    geometry_hash,
    hmm_to_mm,
    mm_to_hmm,
    normalise,
    remaining_margins,
    validate_geometry,
)

L4736 = Geometry("A4", 21000, 29700, 4570, 2120, 4, 12, 4820, 2120, 2130, 985, None, "rectangle")
L4731 = Geometry("A4", 21000, 29700, 2540, 1000, 7, 27, 2790, 1000, 1350, 860, 150, "rectangle")
AVERY7160 = Geometry("A4", 21000, 29700, 6399, 3810, 3, 7, 6604, 3810, 1549, 748, 176, "rectangle")
ROUND = Geometry("A4", 21000, 29700, 3000, 3000, 5, 7, 3500, 3500, 1000, 1000, None, "round")


def test_mm_to_hmm_two_decimals() -> None:
    assert mm_to_hmm(9.85, field="margin_left") == 985
    assert mm_to_hmm("21.2", field="label_h") == 2120
    assert mm_to_hmm(10, field="pitch_y") == 1000


def test_hmm_to_mm() -> None:
    assert hmm_to_mm(985) == 9.85


@pytest.mark.parametrize(
    "bad", [9.855, -1, float("nan"), float("inf"), "x", "1E+9999999", "-Infinity", "sNaN"]
)
def test_mm_to_hmm_rejects(bad: object) -> None:
    with pytest.raises(InvalidGeometryError) as exc:
        mm_to_hmm(bad, field="margin_left")  # type: ignore[arg-type]
    assert exc.value.detail is not None
    assert exc.value.detail["field"] == "margin_left"


def test_l4736rev_valid_and_symmetric() -> None:
    assert validate_geometry(L4736) == []
    assert remaining_margins(L4736) == (985, 2130)
    assert cell_count(L4736) == 48


def test_l4731rev_valid() -> None:
    assert validate_geometry(L4731) == []
    assert cell_count(L4731) == 189
    assert remaining_margins(L4731) == (860, 1350)


def test_cell_origin_row_major() -> None:
    assert cell_origin(L4736, 1) == (985, 2130)
    assert cell_origin(L4736, 9) == (985, 6370)
    assert cell_origin(L4736, 48) == (985 + 3 * 4820, 2130 + 11 * 2120)
    for bad in (0, 49):
        with pytest.raises(CellOutOfRangeError) as exc:
            cell_origin(L4736, bad)
        assert exc.value.detail == {"cells": [bad], "max": 48}


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"pitch_x": 4000}, "pitch_x"),
        ({"pitch_y": 2000}, "pitch_y"),
        ({"cols": 0}, "cols"),
        ({"cols": 21, "rows": 20, "label_w": 100, "pitch_x": 100}, "cols"),
        ({"margin_left": 5000}, "cols"),
        ({"margin_top": 9000}, "rows"),
        ({"shape": "round"}, "label_h"),
        ({"page_w": 20000}, "page_w"),
        ({"page_h": 29000}, "page_h"),
        ({"page_size": "A3"}, "page_size"),
        ({"shape": "oval"}, "shape"),
        ({"label_w": 0}, "label_w"),
        ({"pitch_y": 0}, "pitch_y"),
        ({"margin_top": -1}, "margin_top"),
        ({"margin_left": -1}, "margin_left"),
    ],
)
def test_validation_rules(change: dict[str, object], field: str) -> None:
    with pytest.raises(InvalidGeometryError) as exc:
        validate_geometry(replace(L4736, **change))  # type: ignore[arg-type]
    assert exc.value.detail is not None
    assert exc.value.detail["field"] == field


def test_round_square_label_valid() -> None:
    # accepted (no raise); remaining margins of 30 mm differ from 10 mm -> hints only
    assert validate_geometry(ROUND) == ["margins_asymmetric_x", "margins_asymmetric_y"]


def test_asymmetric_margins_are_hints_not_errors() -> None:
    assert validate_geometry(AVERY7160) == ["margins_asymmetric_x", "margins_asymmetric_y"]
    # margin_left 885 leaves right 1085: 2.0 mm apart, beyond the 0.5 mm tolerance
    only_x = replace(L4736, margin_left=885)
    assert validate_geometry(only_x) == ["margins_asymmetric_x"]


def test_geometry_hash_canonical() -> None:
    canonical = (
        '{"cols":4,"corner_radius":null,"label_h":2120,"label_w":4570,"margin_left":985,'
        '"margin_top":2130,"page_h":29700,"page_size":"A4","page_w":21000,"pitch_x":4820,'
        '"pitch_y":2120,"rows":12,"shape":"rectangle"}'
    )
    assert geometry_hash(L4736) == hashlib.sha256(canonical.encode()).hexdigest()


def test_hash_ignores_radius_on_round() -> None:
    assert geometry_hash(replace(ROUND, corner_radius=100)) == geometry_hash(ROUND)
    assert geometry_hash(replace(L4731, corner_radius=100)) != geometry_hash(L4731)


def test_margin_difference_within_tolerance_gives_no_hint() -> None:
    # right margin = 1970 - margin_left; the difference is |1970 - 2 * margin_left|
    assert validate_geometry(replace(L4736, margin_left=973)) == []  # 0.24 mm
    assert validate_geometry(replace(L4736, margin_left=960)) == []  # exactly 0.5 mm
    assert validate_geometry(replace(L4736, margin_left=959)) == ["margins_asymmetric_x"]


def test_normalise_sets_page_from_table() -> None:
    off = replace(L4736, page_w=1, page_h=2)
    assert (normalise(off).page_w, normalise(off).page_h) == (21000, 29700)
    assert geometry_hash(off) == geometry_hash(L4736)
