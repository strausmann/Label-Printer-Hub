# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tiers, thresholds and the QR box of the swatch label (#346, R-346-8, ruling N2)."""

from __future__ import annotations

import inspect

import pytest
from app.services.spool_swatch import (
    SHEET_METRICS,
    TAPE_METRICS,
    SwatchTier,
    render_swatch,
    swatch_layout,
    swatch_tier,
    tier_thresholds,
    to_px,
)

from tests.helpers.spool_swatch import (
    L4736REV,
    L4737REV,
    QL_BOX,
    SAMPLE_URL,
    Z6121,
    every_row,
    label_box,
    seed_box,
    swatch,
)

FULL, NO_FOOTER, FIRST, CORE = (
    SwatchTier.FULL,
    SwatchTier.NO_FOOTER,
    SwatchTier.FIRST_COLUMN,
    SwatchTier.CORE,
)


@pytest.mark.parametrize(
    ("box", "tier"),
    [
        ((6050, 2880), FULL),
        ((6049, 2880), NO_FOOTER),
        ((6050, 2879), NO_FOOTER),
        ((5450, 2580), NO_FOOTER),
        ((5449, 2580), FIRST),
        ((5450, 2579), FIRST),
        ((2880, 2340), FIRST),
        ((2879, 2340), CORE),
        ((2880, 2339), CORE),
        ((1980, 1380), CORE),
        ((1979, 1380), None),
        ((1980, 1379), None),
    ],
)
def test_tier_thresholds_sheet(box: tuple[int, int], tier: SwatchTier | None) -> None:
    assert swatch_tier(*box, SHEET_METRICS) is tier


@pytest.mark.parametrize(
    ("box", "tier"),
    [
        ((5090, 3040), FULL),
        ((5089, 3040), NO_FOOTER),
        ((5090, 3039), NO_FOOTER),
        ((4590, 2760), NO_FOOTER),
        ((4589, 2760), FIRST),
        ((4590, 2759), FIRST),
        ((2540, 2570), FIRST),
        ((2539, 2570), CORE),
        ((2540, 2569), CORE),
        ((2080, 1810), CORE),
        ((2079, 1810), None),
        ((2080, 1809), None),
    ],
)
def test_tier_thresholds_tape(box: tuple[int, int], tier: SwatchTier | None) -> None:
    assert swatch_tier(*box, TAPE_METRICS) is tier


def test_thresholds_table() -> None:
    assert tier_thresholds(SHEET_METRICS) == (
        (FULL, 6050, 2880),
        (NO_FOOTER, 5450, 2580),
        (FIRST, 2880, 2340),
        (CORE, 1980, 1380),
    )
    assert tier_thresholds(TAPE_METRICS) == (
        (FULL, 5090, 3040),
        (NO_FOOTER, 4590, 2760),
        (FIRST, 2540, 2570),
        (CORE, 2080, 1810),
    )


def test_reference_media() -> None:
    l4737 = seed_box(L4737REV)
    assert l4737 == (6030, 2640)
    assert label_box(6350, 2960) == l4737
    layout = swatch_layout(swatch_tier(*l4737, SHEET_METRICS), *l4737, SHEET_METRICS)  # type: ignore[arg-type]
    assert layout.tier is NO_FOOTER
    assert layout.qr_box == (6030 - 1280, 820, 1280)

    l4736 = seed_box(L4736REV)
    assert l4736 == (4250, 1800)
    layout = swatch_layout(swatch_tier(*l4736, SHEET_METRICS), *l4736, SHEET_METRICS)  # type: ignore[arg-type]
    assert (layout.tier, layout.qr_box) == (CORE, (4250 - 1550, 0, 1550))

    z6121 = seed_box(Z6121)
    assert z6121 == (3490, 1798)
    layout = swatch_layout(swatch_tier(*z6121, SHEET_METRICS), *z6121, SHEET_METRICS)  # type: ignore[arg-type]
    assert (layout.tier, layout.qr_box) == (CORE, (3490 - 1550, 0, 1550))

    px = (696 - 2 * 12, 425 - 2 * 12)
    assert px == (672, 401)
    assert tuple(round(p * 2540 / 300) for p in px) == QL_BOX
    layout = swatch_layout(swatch_tier(*QL_BOX, TAPE_METRICS), *QL_BOX, TAPE_METRICS)  # type: ignore[arg-type]
    assert layout.tier is FULL
    assert layout.qr_box == (5690 - 1550, 1300, 1550)


@pytest.mark.parametrize(
    ("key", "tier"),
    [
        ("avery-7160", FULL),
        ("avery-7164", NO_FOOTER),
        ("avery-5195", NO_FOOTER),
        ("avery-zweckform-4780", FIRST),
        ("avery-5161", CORE),
        ("avery-l4732", CORE),
        ("avery-5167", None),
    ],
)
def test_seed_examples(key: str, tier: SwatchTier | None) -> None:
    assert swatch_tier(*seed_box(key), SHEET_METRICS) is tier


def _render(spool: object, box: tuple[int, int], metrics: object, dpi: int) -> object:
    tier = swatch_tier(*box, metrics)  # type: ignore[arg-type]
    assert tier is not None
    layout = swatch_layout(tier, *box, metrics)  # type: ignore[arg-type]
    image, _ = render_swatch(
        spool,  # type: ignore[arg-type]
        SAMPLE_URL,
        layout=layout,
        width_px=to_px(box[0], dpi),
        height_px=to_px(box[1], dpi),
        dpi=dpi,
        metrics=metrics,  # type: ignore[arg-type]
    )
    return image


def test_qr_box_is_independent_of_the_data() -> None:
    from app.services.spool_swatch import place_swatch

    box = seed_box(L4737REV)
    layout = swatch_layout(NO_FOOTER, *box, SHEET_METRICS)
    spools = [
        every_row("de"),
        swatch(nozzle_c=(210, 230), bed_c=60),
        swatch(),
    ]
    boxes = {place_swatch(s, layout, SHEET_METRICS).layout.qr_box for s in spools}
    assert boxes == {layout.qr_box}

    ql = swatch_layout(FULL, *QL_BOX, TAPE_METRICS)
    one = swatch(vendor="TecBears")
    two = swatch(vendor="Shenzhen Example Filament Corp")
    assert place_swatch(one, ql, TAPE_METRICS).layout.qr_box == (4140, 1300, 1550)
    assert place_swatch(two, ql, TAPE_METRICS).layout.qr_box == (4140, 1300, 1550)
    first = _render(one, QL_BOX, TAPE_METRICS, 300)
    second = _render(two, QL_BOX, TAPE_METRICS, 300)
    # Bar and colour line sit at the same pixels whatever the vendor is.
    region = (0, to_px(960, 300), to_px(4000, 300), to_px(960 + 340 + 320, 300))
    assert first.crop(region).tobytes() == second.crop(region).tobytes()  # type: ignore[attr-defined]


def test_qr_box_starts_at_the_bar_bottom() -> None:
    for tier in (FULL, NO_FOOTER, FIRST):
        assert swatch_layout(tier, 6100, 2900, SHEET_METRICS).qr_box[1] == 820
        assert swatch_layout(tier, 5690, 3395, TAPE_METRICS).qr_box[1] == 1300
    assert swatch_layout(CORE, 4250, 1800, SHEET_METRICS).qr_box[1] == 0
    assert swatch_layout(CORE, 5690, 3395, TAPE_METRICS).qr_box[1] == 0


def test_layout_has_no_resolution() -> None:
    assert "dpi" not in inspect.signature(swatch_layout).parameters
    assert set(inspect.signature(swatch_layout).parameters) == {
        "tier",
        "box_w_hmm",
        "box_h_hmm",
        "metrics",
    }


def test_layout_positions_in_hmm() -> None:
    layout = swatch_layout(NO_FOOTER, 6030, 2640, SHEET_METRICS)
    assert layout.bar == (0, 480, 6030, 340)
    assert layout.bar_baseline == 480 + 340 - 75
    assert layout.colour_baselines == (480 + 340 + 20 + 300 - 65, 480 + 340 + 20 + 600 - 65)
    assert layout.columns == ((0, 2100), (2200, 2470))
    assert layout.rows_bottom == 2640
    assert layout.footer_rule is None
    full = swatch_layout(FULL, *QL_BOX, TAPE_METRICS)
    assert full.vendor_baselines == (480 - 95, 960 - 95)
    assert full.footer_rule == (3395 - 250, 20)
    assert full.footer_baseline == 3395 - 55
    assert full.rows_bottom == 3395 - 250
    first = swatch_layout(FIRST, 4650, 2340, SHEET_METRICS)
    assert first.columns == ((0, 2100),)
    assert first.row_lines == 5
    core = swatch_layout(CORE, 4250, 1800, SHEET_METRICS)
    assert core.columns == ()
    assert core.left_w == 4250 - 1550 - 80
    assert core.bar == (0, 480, core.left_w, 340)
