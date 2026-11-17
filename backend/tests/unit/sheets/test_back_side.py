# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The sheet code strip on the back of the liner and the tray loading page (#350, R-350-3/5)."""

from __future__ import annotations

from typing import Any

import pytest
from app.services.page_jobs import PagePayload
from app.sheets.back_side import (
    QR_EDGE_HMM,
    QR_INSET_HMM,
    STRIP_H_HMM,
    STRIP_W_HMM,
    BackStripDoesNotFitError,
    StripHmm,
    back_page_layout,
    loading_page_payload,
    place_strip,
    render_sheet_back_page,
    render_tray_loading_page,
)

from tests.helpers import pdf_inspect as inspect

A4 = (21000, 29700)
ULTRAGRIP = [StripHmm(3350, 2200, 2200, 25300), StripHmm(15450, 2200, 2200, 25300)]


def _detail(**kw: Any) -> dict[str, Any]:
    strip = kw.pop("strip", StripHmm(3350, 2400, STRIP_W_HMM, STRIP_H_HMM))
    return {
        "sheet_id": "00000000-0000-0000-0000-000000000001",
        "sheet_code": "A3490-0001",
        "type_text": "3490",
        "date": "2026-11-17",
        "scan_payload": "https://hub.example.invalid/s/A3490-0001",
        "strip": {"x": strip.x, "y": strip.y, "w": strip.w, "h": strip.h},
        "rotate_180": False,
        **kw,
    }


def _payload(**kw: Any) -> PagePayload:
    return PagePayload(
        kind="sheet_back_page",
        media="A4",
        tray="tray-1",
        render_dpi=600,
        job_name="Sheet A3490-0001 · back",
        detail=_detail(**kw),
    )


def test_place_strip_ultragrip_left_strip() -> None:
    assert place_strip(*A4, ULTRAGRIP) == StripHmm(3350, 2400, 2200, 6200)


def test_place_strip_skips_narrow_strip() -> None:
    free = [StripHmm(1000, 2200, 2000, 25300), StripHmm(15450, 2200, 2200, 25300)]
    assert place_strip(*A4, free).x == 15450


def test_place_strip_centres_in_a_wider_strip() -> None:
    assert place_strip(*A4, [StripHmm(1000, 2200, 3000, 25300)]).x == 1400


def test_place_strip_none_fits() -> None:
    with pytest.raises(BackStripDoesNotFitError):
        place_strip(*A4, [StripHmm(1000, 2200, 2000, 25300), StripHmm(5000, 2200, 2200, 6000)])


def test_place_strip_default_without_design() -> None:
    assert place_strip(*A4, []) == StripHmm(1000, 1000, 2200, 6200)


def test_strip_stays_in_a_free_strip_after_a_half_turn() -> None:
    s = place_strip(*A4, ULTRAGRIP)
    turned = StripHmm(A4[0] - s.x - s.w, A4[1] - s.y - s.h, s.w, s.h)
    second = ULTRAGRIP[1]
    assert second.x <= turned.x and turned.x + turned.w <= second.x + second.w
    assert second.y <= turned.y and turned.y + turned.h <= second.y + second.h


def test_render_back_page_is_one_a4_page_with_qr_text() -> None:
    pdf = render_sheet_back_page(_payload(), compress=False)
    assert inspect.media_box(pdf) == pytest.approx((0, 0, 595.276, 841.89), abs=1e-2)
    assert "A3490-0001" in inspect.texts(pdf)
    assert "3490 · 2026-11-17" in inspect.texts(pdf)
    (image,) = inspect.placed_images(pdf)
    turned = inspect.placed_images(
        render_sheet_back_page(_payload(rotate_180=True), compress=False)
    )[0]
    cx, cy = image.x_pt + image.w_pt / 2, image.y_pt + image.h_pt / 2
    tx, ty = turned.x_pt + turned.w_pt / 2, turned.y_pt + turned.h_pt / 2
    assert (tx, ty) == pytest.approx((595.276 - cx, 841.89 - cy), abs=0.01)


def test_back_page_qr_sits_at_the_strip_top() -> None:
    lay = back_page_layout(_detail_model())
    assert (lay.qr.x, lay.qr.y) == (3350 + QR_INSET_HMM, 2400 + QR_INSET_HMM)
    assert lay.qr.w == lay.qr.h == QR_EDGE_HMM


def _detail_model(**kw: Any) -> Any:
    from app.sheets.back_side import SheetBackDetail

    return SheetBackDetail.model_validate(_detail(**kw))


def test_back_page_text_is_shrunk_not_cut() -> None:
    lay = back_page_layout(_detail_model(type_text="X" * 40))
    code, info = lay.texts
    assert code.text == "A3490-0001"
    assert info.text.endswith("…")
    pdf = render_sheet_back_page(_payload(type_text="X" * 40), compress=False)
    assert "A3490-0001" in inspect.texts(pdf)


def test_back_text_reads_bottom_to_top() -> None:
    lay = back_page_layout(_detail_model())
    strip = StripHmm(3350, 2400, STRIP_W_HMM, STRIP_H_HMM)
    qr_bottom = lay.qr.y + lay.qr.h
    for t in lay.texts:
        assert t.rotation == 270
        assert strip.x <= t.x_hmm <= strip.x + strip.w
        assert qr_bottom < t.baseline_y_hmm <= strip.y + strip.h


def test_rotate_180_turns_texts_and_qr() -> None:
    upright = back_page_layout(_detail_model())
    turned = back_page_layout(_detail_model(rotate_180=True))
    w, h = A4
    assert turned.qr.x == w - upright.qr.x - upright.qr.w
    assert turned.qr.y == h - upright.qr.y - upright.qr.h
    for a, b in zip(upright.texts, turned.texts, strict=True):
        assert b.rotation == 90
        assert (b.x_hmm, b.baseline_y_hmm) == (w - a.x_hmm, h - a.baseline_y_hmm)
        assert b.text == a.text and b.size_pt == a.size_pt
    assert turned.frame == StripHmm(
        w - upright.frame.x - upright.frame.w,
        h - upright.frame.y - upright.frame.h,
        upright.frame.w,
        upright.frame.h,
    )


def test_render_loading_page_has_top_and_side_texts() -> None:
    en = inspect.texts(
        render_tray_loading_page(loading_page_payload("tray-1", "A4", "en"), compress=False)
    )
    assert "TOP ↑" in en and "PRINTED SIDE" in en
    de = inspect.texts(
        render_tray_loading_page(loading_page_payload("tray-1", "A4", "de"), compress=False)
    )
    assert "OBEN ↑" in de and "BEDRUCKTE SEITE" in de
    other = loading_page_payload("tray-1", "Letter", None)
    assert other.kind == "tray_loading_page" and other.media == "Letter"
    assert other.calibration is None
