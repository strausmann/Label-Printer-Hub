# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import math

import pytest
from app.page_render.transform import (
    IDENTITY,
    PT_PER_MM,
    Affine,
    Deviation,
    apply_deviation,
    correction_mm,
    correction_pdf_matrix,
    page_height_pt,
)

BUSY = Deviation(150, -80, 1_002_000, 998_500, 500_000)


def _points() -> list[tuple[float, float]]:
    return [(5.0 + 9.7 * i, 3.0 + 13.9 * i) for i in range(20)]


def test_identity_roundtrip() -> None:
    for page, (w, h) in (("A4", (210.0, 297.0)), ("Letter", (215.9, 279.4))):
        for q in [*_points(), (0.0, 0.0), (w, h)]:
            if q[0] > w or q[1] > h:
                continue
            back = apply_deviation(BUSY, page, correction_mm(BUSY, page).apply(q))  # type: ignore[arg-type]
            assert back == pytest.approx(q, abs=1e-6)


def test_identity_deviation_is_a_noop() -> None:
    assert correction_pdf_matrix(IDENTITY, "A4") == pytest.approx((1, 0, 0, 1, 0, 0), abs=1e-12)
    assert apply_deviation(IDENTITY, "A4", (12.5, 99.0)) == pytest.approx((12.5, 99.0), abs=1e-12)


def test_offset_correction_matrix() -> None:
    dev = Deviation(offset_x_hmm=150, offset_y_hmm=-80)
    m = correction_pdf_matrix(dev, "A4")
    assert m == pytest.approx((1, 0, 0, 1, -4.2520, -2.2677), abs=1e-3)


def test_rotation_sign() -> None:
    dev = Deviation(rotation_udeg=1_000_000)
    cx, cy = 105.0, 148.5
    x, y = apply_deviation(dev, "A4", (cx + 50.0, cy))
    assert y > cy  # right of the centre moves down: clockwise as seen with y down
    assert x < cx + 50.0
    assert y - cy == pytest.approx(50.0 * math.sin(math.radians(1.0)), abs=1e-9)


def test_scale_acts_around_the_page_centre() -> None:
    dev = Deviation(scale_x_ppm=1_010_000)
    assert apply_deviation(dev, "A4", (105.0, 20.0))[0] == pytest.approx(105.0, abs=1e-9)
    assert apply_deviation(dev, "A4", (205.0, 20.0))[0] == pytest.approx(105.0 + 100.0 * 1.01)


# Hand-computed expectations: plain numbers, not the module's own formula. The page centre of
# A4 is (105, 148.5); y points down, a positive rotation is clockwise as seen.


def test_rotation_one_degree_literal() -> None:
    # (105, 98.5) is 50 mm above the centre; it swings to the right and down a little
    x, y = apply_deviation(Deviation(rotation_udeg=1_000_000), "A4", (105.0, 98.5))
    assert (x, y) == pytest.approx((105.872620, 98.507615), abs=1e-6)


def test_scale_y_only_literal() -> None:
    x, y = apply_deviation(Deviation(scale_y_ppm=990_000), "A4", (20.0, 248.5))
    assert (x, y) == pytest.approx((20.0, 148.5 + 100.0 * 0.99), abs=1e-9)


def test_scale_x_only_literal() -> None:
    x, y = apply_deviation(Deviation(scale_x_ppm=1_010_000), "A4", (205.0, 20.0))
    assert (x, y) == pytest.approx((105.0 + 100.0 * 1.01, 20.0), abs=1e-9)


def test_rotation_and_scale_combined_literal() -> None:
    dev = Deviation(scale_x_ppm=1_010_000, scale_y_ppm=990_000, rotation_udeg=1_000_000)
    x, y = apply_deviation(dev, "A4", (155.0, 98.5))
    assert (x, y) == pytest.approx((156.356203, 99.888886), abs=1e-6)


def test_rotation_one_degree_pdf_matrix_literal() -> None:
    m = correction_pdf_matrix(Deviation(rotation_udeg=1_000_000), "A4")
    assert m == pytest.approx(
        (0.999848, 0.017452, -0.017452, 0.999848, 7.391833, -5.130384), abs=1e-5
    )


def test_offset_is_added_after_the_rotation() -> None:
    dev = Deviation(offset_x_hmm=100, offset_y_hmm=-50, rotation_udeg=1_000_000)
    x, y = apply_deviation(dev, "A4", (105.0, 98.5))
    assert (x, y) == pytest.approx((105.872620 + 1.0, 98.507615 - 0.5), abs=1e-6)


def test_non_positive_scale_is_rejected() -> None:
    for kw in ({"scale_x_ppm": 0}, {"scale_y_ppm": 0}, {"scale_x_ppm": -1}, {"scale_y_ppm": -1}):
        with pytest.raises(ValueError, match="positive"):
            Deviation(**kw)  # type: ignore[arg-type]


def test_hand_built_singular_affine_is_rejected() -> None:
    with pytest.raises(ValueError, match="singular"):
        Affine(1, 0, 2, 0, 0, 0).inverse()


def test_unknown_page_is_rejected() -> None:
    with pytest.raises(ValueError, match="A5"):
        correction_mm(IDENTITY, "A5")  # type: ignore[arg-type]


def test_page_height_pt() -> None:
    assert page_height_pt("A4") == pytest.approx(297.0 * PT_PER_MM)
    assert page_height_pt("Letter") == pytest.approx(792.0)
