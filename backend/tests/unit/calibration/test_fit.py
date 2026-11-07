"""The readings fit: recovers a known deviation, flags a bad reading, refuses bad input."""

from __future__ import annotations

import math

import pytest
from app.calibration.fit import Reading, crossing_point, fit
from app.page_render.transform import Deviation, apply_deviation
from app.sheets.errors import InvalidFieldError, ReadingsInsufficientError
from app.sheets.geometry import Geometry

# L4736REV: 4 x 12 labels on A4.
G48 = Geometry(
    page_size="A4",
    page_w=21000,
    page_h=29700,
    label_w=4570,
    label_h=2120,
    cols=4,
    rows=12,
    pitch_x=4820,
    pitch_y=2120,
    margin_top=2130,
    margin_left=985,
    corner_radius=None,
    shape="rectangle",
)
KNOWN = Deviation(120, -40, 1_001_000, 999_000, 300_000)
OUTER = [(1, 1), (3, 1), (1, 11), (3, 11)]


def _reading(g: Geometry, dev: Deviation, col: int, row: int) -> Reading:
    qx, qy = crossing_point(g, col, row)
    px, py = apply_deviation(dev, "A4", (qx, qy))
    return Reading(col, row, px - qx, py - qy)


def test_fit_recovers_known_deviation() -> None:
    result = fit(G48, "A4", [_reading(G48, KNOWN, c, r) for c, r in OUTER])
    assert result.dev.offset_x_hmm == pytest.approx(KNOWN.offset_x_hmm, abs=1)  # 0.01 mm
    assert result.dev.offset_y_hmm == pytest.approx(KNOWN.offset_y_hmm, abs=1)
    assert result.dev.scale_x_ppm == pytest.approx(KNOWN.scale_x_ppm, abs=10)  # 1e-5
    assert result.dev.scale_y_ppm == pytest.approx(KNOWN.scale_y_ppm, abs=10)
    assert result.dev.rotation_udeg == pytest.approx(KNOWN.rotation_udeg, abs=1000)  # 0.001 deg
    assert max(result.residuals_mm) < 0.01
    assert result.flagged == []
    assert result.out_of_range == []


def test_fit_flags_bad_reading() -> None:
    good = [_reading(G48, KNOWN, c, r) for c, r in [*OUTER, (2, 6)]]
    bad = good[4]
    good[4] = Reading(bad.col_gap, bad.row_gap, bad.across_mm + 1.0, bad.down_mm)
    result = fit(G48, "A4", good)
    assert 4 in result.flagged
    assert max(result.residuals_mm) > 0.3


def test_fit_insufficient_and_collinear() -> None:
    two = [_reading(G48, KNOWN, c, r) for c, r in OUTER[:2]]
    with pytest.raises(ReadingsInsufficientError) as few:
        fit(G48, "A4", two)
    assert few.value.detail == {"reason": "fewer_than_three_readings"}
    one_row = [_reading(G48, KNOWN, c, 5) for c in (1, 2, 3)]
    with pytest.raises(ReadingsInsufficientError) as line:
        fit(G48, "A4", one_row)
    assert line.value.detail == {"reason": "readings_on_one_line"}
    one_col = [_reading(G48, KNOWN, 2, r) for r in (1, 5, 9)]
    with pytest.raises(ReadingsInsufficientError):
        fit(G48, "A4", one_col)


def test_fit_out_of_range_reported_not_raised() -> None:
    wild = Deviation(1500, 0, 1_080_000, 1_000_000, 0)  # 15 mm and 1.08 are outside
    result = fit(G48, "A4", [_reading(G48, wild, c, r) for c, r in OUTER])
    assert result.out_of_range == ["offset_x_mm", "scale_x"]
    assert result.dev.offset_x_hmm == pytest.approx(1500, abs=1)


def test_crossing_point_no_gap() -> None:
    assert crossing_point(G48, 1, 1)[1] == pytest.approx(42.5)
    x, _ = crossing_point(G48, 1, 1)
    assert x == pytest.approx(9.85 + 45.7 + 1.25)


def test_crossing_point_pitch_equals_label_is_the_nominal_cut() -> None:
    # Z1 of a sheet without a vertical gap: margin_top + label_h.
    assert crossing_point(G48, 1, 1)[1] == pytest.approx((G48.margin_top + G48.label_h) / 100)


def test_crossing_point_gap_outside_the_sheet() -> None:
    with pytest.raises(InvalidFieldError):
        crossing_point(G48, 4, 1)  # only S1..S3 exist
    with pytest.raises(InvalidFieldError):
        crossing_point(G48, 1, 12)
    with pytest.raises(InvalidFieldError):
        crossing_point(G48, 0, 1)


def test_fit_pure_rotation_sign_matches_apply_deviation() -> None:
    dev = Deviation(0, 0, 1_000_000, 1_000_000, 500_000)  # +0.5 deg, clockwise
    result = fit(G48, "A4", [_reading(G48, dev, c, r) for c, r in OUTER])
    assert result.dev.rotation_udeg == pytest.approx(500_000, abs=1000)
    assert not math.isnan(result.residuals_mm[0])


def test_fit_collapsed_map_is_insufficient() -> None:
    # Every crossing printed on the page centre: no scale, nothing printable.
    collapsed = []
    for col, row in OUTER:
        qx, qy = crossing_point(G48, col, row)
        collapsed.append(Reading(col, row, 105.0 - qx, 148.5 - qy))
    with pytest.raises(ReadingsInsufficientError) as err:
        fit(G48, "A4", collapsed)
    assert err.value.detail == {"reason": "degenerate_fit"}


def test_gap_outside_the_sheet_names_the_reading() -> None:
    readings = [_reading(G48, KNOWN, c, r) for c, r in OUTER]
    readings[2] = Reading(9, 11, 0.0, 0.0)
    with pytest.raises(InvalidFieldError) as err:
        fit(G48, "A4", readings)
    assert err.value.detail is not None
    assert err.value.detail["reading"] == 2
    assert err.value.detail["field"] == "col_gap"
