from __future__ import annotations

import math

import pytest
from app.page_render.transform import (
    IDENTITY,
    PT_PER_MM,
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


def test_unknown_page_is_rejected() -> None:
    with pytest.raises(ValueError, match="A5"):
        correction_mm(IDENTITY, "A5")  # type: ignore[arg-type]


def test_page_height_pt() -> None:
    assert page_height_pt("A4") == pytest.approx(297.0 * PT_PER_MM)
    assert page_height_pt("Letter") == pytest.approx(792.0)
