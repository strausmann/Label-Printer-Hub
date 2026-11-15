# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Drawing the swatch label (#346, R-346-2, R-346-7a, R-346-8).

Version-independent: positions are compared in pixels derived from hmm with ``to_px``, never
against a drawn width. Runs in the main job and in the ``swatch-text-metrics`` job on Pillow
11.3 and 13.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from app.printer_backends.exceptions import ContentTypeDataMismatchError, QrPayloadTooLongError
from app.schemas.spool_swatch import SpoolSwatch
from app.services import spool_swatch as ss
from app.services.spool_swatch import (
    SHEET_METRICS,
    TAPE_METRICS,
    SwatchMetrics,
    SwatchTier,
    layout_for_box,
    place_swatch,
    render_swatch,
    swatch_layout,
    swatch_symbol,
    swatch_tier,
    text_mm,
    to_px,
)
from app.sheets.cell_render import QrDoesNotFitError
from PIL import Image, ImageDraw

from tests.helpers.spool_swatch import (
    L4736REV,
    L4737REV,
    QL_BOX,
    SAMPLE_URL,
    Z6121,
    every_row,
    ink_bbox,
    seed_box,
    swatch,
)

SHEET_DPIS = SHEET_METRICS.test_dpis
LONG_VENDOR = "Shenzhen Example Filament Corp"


def _box(medium: str) -> tuple[tuple[int, int], SwatchMetrics]:
    if medium == "ql":
        return QL_BOX, TAPE_METRICS
    return seed_box(medium), SHEET_METRICS


def _render(
    spool: SpoolSwatch,
    box: tuple[int, int],
    metrics: SwatchMetrics,
    dpi: int,
    payload: str = SAMPLE_URL,
) -> tuple[Image.Image, bool]:
    layout = layout_for_box(*box, metrics)
    return render_swatch(
        spool,
        payload,
        layout=layout,
        width_px=to_px(box[0], dpi),
        height_px=to_px(box[1], dpi),
        dpi=dpi,
        metrics=metrics,
    )


def _place(spool: SpoolSwatch, box: tuple[int, int], metrics: SwatchMetrics) -> Any:
    return place_swatch(spool, layout_for_box(*box, metrics), metrics)


def _black_rows(image: Image.Image, x0: int, x1: int) -> list[int]:
    gray = image.convert("L")
    return [
        y for y in range(gray.height) if any(gray.getpixel((x, y)) < 128 for x in range(x0, x1))
    ]


@pytest.mark.parametrize("dpi", SHEET_DPIS)
def test_image_is_exactly_the_box(dpi: int) -> None:
    box = seed_box(L4737REV)
    image, _ = _render(every_row(), box, SHEET_METRICS, dpi)
    assert image.size == (to_px(box[0], dpi), to_px(box[1], dpi))
    assert image.mode == "1"
    image, _ = render_swatch(
        every_row(),
        SAMPLE_URL,
        layout=layout_for_box(*box, SHEET_METRICS),
        width_px=301,
        height_px=140,
        dpi=dpi,
        metrics=SHEET_METRICS,
    )
    assert image.size == (301, 140)


@pytest.mark.parametrize("dpi", SHEET_DPIS)
def test_l4737rev_worst_case_fits_at_every_dpi(dpi: int) -> None:
    box = seed_box(L4737REV)
    spool = every_row("de")
    placement = _place(spool, box, SHEET_METRICS)
    assert placement.layout.tier is SwatchTier.NO_FOOTER
    assert len(placement.columns) == 2
    assert placement.layout.footer_rule is None
    last = max(b for column in placement.columns for row in column.rows for b in row.baselines)
    assert last == 2640 - 75
    image, _ = _render(spool, box, SHEET_METRICS, dpi)
    ink = ink_bbox(image)
    assert ink is not None
    assert ink[3] - 1 <= image.height - 2
    left = _black_rows(image, 0, to_px(4000, dpi))
    assert max(left) <= image.height - 2


def test_wrapped_lines_count_in_the_height() -> None:
    spool = every_row("de")
    placement = _place(spool, (5450, 2580), SHEET_METRICS)
    assert placement.layout.tier is SwatchTier.NO_FOOTER
    column_2 = placement.columns[1]
    assert column_2.lines == 6
    baselines = [b for row in column_2.rows for b in row.baselines]
    assert len(baselines) == 6
    assert max(baselines) == 2580 - 75
    assert min(baselines) - 240 + 75 >= 480 + 340 + 20 + 300
    for dpi in SHEET_DPIS:
        image, truncated = _render(spool, (5450, 2580), SHEET_METRICS, dpi)
        assert not truncated
        ink = ink_bbox(image)
        assert ink is not None and ink[3] <= image.height
    assert swatch_tier(5450, 2579, SHEET_METRICS) is SwatchTier.FIRST_COLUMN


@pytest.mark.parametrize("medium", [L4736REV, Z6121])
@pytest.mark.parametrize("dpi", SHEET_DPIS)
def test_core_caption_stays_inside_the_box(medium: str, dpi: int) -> None:
    box = seed_box(medium)
    layout = layout_for_box(*box, SHEET_METRICS)
    assert layout.tier is SwatchTier.CORE
    image, _ = _render(swatch(), box, SHEET_METRICS, dpi)
    x, _, edge = layout.qr_box
    caption = image.crop((to_px(x - 80, dpi), to_px(edge, dpi), image.width, image.height))
    ink = ink_bbox(caption)
    assert ink is not None
    assert ink[3] < caption.height
    assert layout.caption_baseline + 1 <= box[1]


def test_value_sits_on_the_first_label_line() -> None:
    placement = _place(every_row("de"), seed_box(L4737REV), SHEET_METRICS)
    two_line_rows = [r for c in placement.columns for r in c.rows if len(r.label) == 2]
    assert two_line_rows
    for row in two_line_rows:
        assert row.value_baselines[0] == row.baselines[0]


def test_values_start_at_the_column_tab_stop() -> None:
    spool = swatch(nozzle_c=(210, 230), bed_c=60, pressure_advance=0.025)
    calls: list[tuple[float, str]] = []
    original = ss.font.draw_glyphs

    def spy(draw: Any, x_hmm: float, baseline: int, text: str, **kw: Any) -> None:
        calls.append((x_hmm, text))
        original(draw, x_hmm, baseline, text, **kw)

    with patch.object(ss.font, "draw_glyphs", spy):
        _render(spool, seed_box(L4737REV), SHEET_METRICS, 300)
    widest = max(text_mm(t, 700, 1.6) for t in ("Nozzle", "Bed", "PA (K)"))
    tab = 0 + widest * 100 + 8.5 + 80
    values = {"210\u2013230 °C", "60 °C", "0.025"}
    starts = {x for x, text in calls if text in values}
    assert starts == {tab}


def _finder_top_left(image: Image.Image, x0: int, y0: int) -> tuple[int, int]:
    """Top-left corner of the first dark pixel in the QR area starting at (x0, y0)."""
    gray = image.convert("L")
    for y in range(y0, gray.height):
        for x in range(x0, gray.width):
            if gray.getpixel((x, y)) < 128:
                return x, y
    raise AssertionError("no QR ink")


@pytest.mark.parametrize(
    ("medium", "dpi", "box_px", "module", "ink"),
    [
        (L4737REV, 600, 302, 9, 261),
        (L4737REV, 300, 151, 4, 116),
    ],
)
def test_qr_ink_starts_two_modules_under_the_bar(
    medium: str, dpi: int, box_px: int, module: int, ink: int
) -> None:
    box, metrics = _box(medium)
    layout = layout_for_box(*box, metrics)
    x, y, edge = layout.qr_box
    assert to_px(edge, dpi) == box_px
    image, _ = _render(swatch(), box, metrics, dpi)
    left, top = _finder_top_left(image, to_px(x, dpi), to_px(y, dpi))
    assert top == to_px(y, dpi) + 2 * module
    assert left == to_px(x, dpi) + (box_px - ink) // 2
    symbol = swatch_symbol(SAMPLE_URL, box_px)
    assert symbol is not None
    assert symbol[0].size == (ink, ink)
    assert symbol[1] == module


def test_qr_quiet_zone_is_two_modules() -> None:
    box = seed_box(L4737REV)
    layout = layout_for_box(*box, SHEET_METRICS)
    x, y, edge = layout.qr_box
    dpi = 600
    image, _ = _render(swatch(), box, SHEET_METRICS, dpi)
    symbol, module = swatch_symbol(SAMPLE_URL, to_px(edge, dpi))  # type: ignore[misc]
    ink_left = to_px(x, dpi) + (to_px(edge, dpi) - symbol.width) // 2
    ink_top = to_px(y, dpi) + 2 * module
    zone = image.crop(
        (
            ink_left - 2 * module,
            ink_top - 2 * module,
            ink_left + symbol.width + 2 * module,
            ink_top + symbol.height + 2 * module,
        )
    )
    inner = (2 * module, 2 * module, 2 * module + symbol.width, 2 * module + symbol.height)
    gray = zone.convert("L")
    for yy in range(gray.height):
        for xx in range(gray.width):
            inside = inner[0] <= xx < inner[2] and inner[1] <= yy < inner[3]
            if not inside:
                assert gray.getpixel((xx, yy)) >= 128, (xx, yy)


@pytest.mark.parametrize(
    ("medium", "dpi", "ink"),
    [
        (L4737REV, 600, 261),
        (L4737REV, 300, 116),
        ("ql", 300, 145),
        (L4736REV, 600, 319),
        (L4736REV, 300, 145),
        (Z6121, 600, 319),
        (Z6121, 300, 145),
    ],
)
def test_qr_ink_size_per_medium(medium: str, dpi: int, ink: int) -> None:
    box, metrics = _box(medium)
    edge = layout_for_box(*box, metrics).qr_box[2]
    symbol = swatch_symbol(SAMPLE_URL, to_px(edge, dpi))
    assert symbol is not None
    assert symbol[0].size == (ink, ink)


@pytest.mark.parametrize("dpi", SHEET_DPIS)
def test_bar_and_vendor_are_full_width_above_the_qr(dpi: int) -> None:
    box = seed_box(L4737REV)
    layout = layout_for_box(*box, SHEET_METRICS)
    image, _ = _render(swatch(title=""), box, SHEET_METRICS, dpi)
    gray = image.convert("L")
    middle = to_px(480 + 170, dpi)
    assert all(gray.getpixel((x, middle)) < 128 for x in range(to_px(2000, dpi), gray.width))
    assert all(gray.getpixel((x, middle)) < 128 for x in range(to_px(50, dpi)))
    assert layout.bar == (0, 480, box[0], 340)
    x, y, _ = layout.qr_box
    assert y == 480 + 340
    above = image.crop((to_px(x, dpi), to_px(y, dpi), image.width, to_px(y, dpi) + 1))
    assert all(v >= 128 for v in above.convert("L").tobytes())


def _first_row_all_black(image: Image.Image, y: int, x0: int, x1: int) -> bool:
    gray = image.convert("L")
    return all(gray.getpixel((x, y)) < 128 for x in range(x0, x1))


@pytest.mark.parametrize("medium", [L4737REV, "ql"])
def test_accented_capitals_stay_inside(medium: str) -> None:
    box, metrics = _box(medium)
    spool = swatch(vendor="ÜBERSEE", title="GRÜN", color_name="Ölgrün", color_hexes=())
    v = metrics.vendor_block
    placement = place_swatch(spool, layout_for_box(*box, metrics), metrics)
    runs = {r.text: r for r in placement.runs}
    for dpi in metrics.test_dpis:
        # Each run drawn alone, shifted down by 25.4 mm (a whole number of pixels at every
        # test dpi), so ink above the label's top edge would show instead of being clipped.
        top, bottom = _run_rows(runs["ÜBERSEE"], dpi, 255)
        assert top >= 0 and bottom < to_px(v, dpi)
        top, bottom = _run_rows(runs["GRÜN"], dpi, 0)
        assert top >= to_px(v, dpi) and bottom < to_px(v + 340, dpi)
        top, bottom = _run_rows(runs["Ölgrün"], dpi, 255)
        # Under the bar: the accent never shares a pixel row with the bar (at 300 dpi the margin is
        # 0-1 px depending on the Pillow version, spec R-346-7).
        assert top >= to_px(v + 340, dpi)
        assert bottom < to_px(v + 660, dpi)


_PAD = 2540


def _run_rows(run: Any, dpi: int, background: int) -> tuple[int, int]:
    """First and last ink row of ``run`` drawn alone, in the label's pixel rows."""
    pad = to_px(_PAD, dpi)
    canvas = Image.new("L", (to_px(8000, dpi), to_px(4000 + _PAD, dpi)), background)
    ss.font.draw_glyphs(
        ImageDraw.Draw(canvas),
        run.x,
        run.baseline + _PAD,
        run.text,
        weight=run.weight,
        cap_mm=run.cap_mm,
        dpi=dpi,
        fill=run.fill,
    )
    ink = canvas.point(lambda p: 255 if p != background else 0).getbbox()
    assert ink is not None
    return ink[1] - pad, ink[3] - 1 - pad


def test_value_wraps_onto_a_free_line() -> None:
    spool = every_row("en", location="AMS slot 9 · upper shelf")
    placement = _place(spool, seed_box(L4737REV), SHEET_METRICS)
    column_2 = placement.columns[1]
    location = column_2.rows[-1]
    assert len(location.value) == 2
    assert column_2.lines == 6
    assert "…" not in "".join(location.value)
    assert not placement.truncated


def test_colour_line_wraps_when_the_left_part_has_a_free_row() -> None:
    colour = "Translucent Ocean Blue and Silver Sparks"
    assert text_mm("Translucent Ocean Blue and Silver", 400, 1.9) == pytest.approx(43.04, abs=0.01)
    assert text_mm("Translucent Ocean Blue and Silver", 700, 1.9) == pytest.approx(46.14, abs=0.01)
    box = seed_box(L4737REV)
    assert layout_for_box(*box, SHEET_METRICS).left_w == 4670
    placement = _place(swatch(color_name=colour), box, SHEET_METRICS)
    assert placement.colour.lines == ("Translucent Ocean Blue and Silver", "Sparks")
    assert placement.colour.cap_mm == 1.9
    first, second = placement.colour_baselines
    assert second - first == 300
    assert not placement.truncated
    crowded = _place(every_row("de", color_name=colour), box, SHEET_METRICS)
    assert len(crowded.colour.lines) == 1
    assert crowded.colour.lines[0].endswith("…")
    assert crowded.colour.cap_mm == 1.6
    assert crowded.truncated


def test_vendor_wraps_before_it_is_cut() -> None:
    assert text_mm(LONG_VENDOR, 700, 1.6) == pytest.approx(37.96, abs=0.01)
    spool = swatch(vendor=LONG_VENDOR, color_hexes=("FF5F00",))

    ql = _place(spool, QL_BOX, TAPE_METRICS)
    assert ql.vendor.lines == ("Shenzhen Example", "Filament Corp")
    assert ql.vendor.cap_mm == 2.9
    assert ql.layout.bar[1] == 960
    assert not ql.truncated
    assert text_mm("Shenzhen Example", 700, 2.9) == pytest.approx(38.58, abs=0.01)
    assert ql.vendor_slot == 5690 - round(text_mm("#FF5F00", 400, 1.25) * 100) - 100

    l4737 = _place(spool, seed_box(L4737REV), SHEET_METRICS)
    assert l4737.vendor.lines == ("Shenzhen Example", "Filament Corp")
    assert l4737.vendor.cap_mm == 1.6
    assert not l4737.truncated

    l4736 = _place(spool, seed_box(L4736REV), SHEET_METRICS)
    assert l4736.vendor.lines == ("Shenzhen Example", "Filament Corp")
    assert l4736.vendor.cap_mm == 1.6
    assert not l4736.truncated

    z6121 = _place(spool, seed_box(Z6121), SHEET_METRICS)
    assert z6121.vendor.lines == ("Shenzhen", "Example Filam…")
    assert text_mm("Example Filam…", 700, 1.6) == pytest.approx(18.587, abs=0.001)
    assert z6121.truncated


def test_one_word_vendor_shrinks_then_cuts() -> None:
    word = "Shenzhenexamplefilamentcorpora"
    assert len(word) == 30
    z6121 = _place(swatch(vendor=word), seed_box(Z6121), SHEET_METRICS)
    assert len(z6121.vendor.lines) == 1
    assert z6121.vendor.cap_mm == 1.6
    assert z6121.vendor.lines[0].endswith("…")
    assert z6121.truncated
    ql = _place(swatch(vendor=word, color_hexes=()), QL_BOX, TAPE_METRICS)
    assert len(ql.vendor.lines) == 1
    assert 1.25 <= ql.vendor.cap_mm < 2.9
    assert not ql.truncated
    longer = _place(swatch(vendor=word * 2, color_hexes=()), QL_BOX, TAPE_METRICS)
    assert len(longer.vendor.lines) == 1
    assert longer.vendor.cap_mm == 1.25
    assert longer.vendor.lines[0].endswith("…")
    assert longer.truncated


def test_title_shrinks_before_it_is_cut() -> None:
    box = seed_box(Z6121)
    short = _place(swatch(title="PETG"), box, SHEET_METRICS)
    assert short.title.cap_mm == 2.0
    medium = _place(swatch(title="PLA Matte Silk"), box, SHEET_METRICS)
    assert 1.6 <= medium.title.cap_mm < 2.0
    assert medium.title.lines == ("PLA Matte Silk",)
    assert not medium.truncated
    long = _place(swatch(title="Polyethylene Terephthalate Glycol"), box, SHEET_METRICS)
    assert long.title.cap_mm == 1.6
    assert long.title.lines[0].endswith("…")
    assert long.truncated


def test_last_resort_cut_sets_truncated() -> None:
    vendor = ("Shenzhen Example Filament Corporation International Holding " * 2)[:64]
    placement = _place(swatch(vendor=vendor), seed_box(Z6121), SHEET_METRICS)
    assert len(placement.vendor.lines) == 2
    assert placement.vendor.cap_mm == 1.6
    assert placement.vendor.lines[1].endswith("…")
    assert placement.truncated
    _, truncated = _render(swatch(vendor=vendor), seed_box(Z6121), SHEET_METRICS, 300)
    assert truncated


def test_value_cut_only_when_no_line_is_free() -> None:
    location = ("Shelf A2 upper row left behind the green box " * 3)[:64]
    placement = _place(every_row("de", location=location), seed_box(L4737REV), SHEET_METRICS)
    column_2 = placement.columns[1]
    assert column_2.lines == 6
    assert column_2.rows[-1].value[-1].endswith("…")
    assert placement.truncated


def test_hex_block_shows_every_code() -> None:
    codes = ("FF5F00", "C2C1C0", "000000", "1A1A1A")
    placement = _place(swatch(color_hexes=codes), seed_box(L4737REV), SHEET_METRICS)
    assert placement.hexes.lines == ("#FF5F00 · #C2C1C0 · #000000", "#1A1A1A")
    assert text_mm(placement.hexes.lines[0], 400, 1.6) == pytest.approx(34.78, abs=0.01)
    assert 6030 - 100 - 2000 == 3930
    assert placement.vendor_slot >= 2000
    assert not placement.truncated


def test_hex_plus_n_only_as_last_resort() -> None:
    codes = tuple(c * 6 for c in "0123456789ABCDEF")
    placement = _place(swatch(color_hexes=codes), seed_box(L4737REV), SHEET_METRICS)
    assert placement.hexes.lines == (
        "#000000 · #111111 · #222222",
        "#333333 · #444444 · +11",
    )
    assert text_mm(placement.hexes.lines[0], 400, 1.6) == pytest.approx(31.55, abs=0.01)
    assert text_mm(placement.hexes.lines[1], 400, 1.6) == pytest.approx(27.45, abs=0.01)
    assert placement.vendor_slot >= 2000
    assert placement.truncated


def test_tape_hex_block_counts_per_row() -> None:
    four = ("FF5F00", "C2C1C0", "000000", "1A1A1A")
    placement = _place(swatch(color_hexes=four), QL_BOX, TAPE_METRICS)
    assert placement.hexes.lines == ("#FF5F00 · #C2C1C0 · #000000 · #1A1A1A",)
    assert text_mm(placement.hexes.lines[0], 400, 1.25) == pytest.approx(35.68, abs=0.01)
    same = _place(swatch(color_hexes=("000000",) * 4), QL_BOX, TAPE_METRICS)
    assert same.hexes.lines == ("#000000 · #000000 · #000000", "#000000")
    assert text_mm("#000000 · " * 3 + "#000000", 400, 1.25) == pytest.approx(38.47, abs=0.01)


def test_core_hex_line_wraps() -> None:
    codes = ("FF5F00", "C2C1C0", "000000")
    placement = _place(swatch(color_hexes=codes), seed_box(L4736REV), SHEET_METRICS)
    assert placement.layout.left_w == 2620
    assert placement.hexes.lines == ("#FF5F00 · #C2C1C0", "#000000")
    assert not placement.truncated


def test_caption_may_use_the_gap() -> None:
    fits = _place(swatch(spool_id=8888888), seed_box(L4737REV), SHEET_METRICS)
    assert fits.caption.lines == ("#8888888",)
    assert not fits.truncated
    layout = swatch_layout(SwatchTier.CORE, 1980, 1380, SHEET_METRICS)
    assert layout.qr_box[2] == 700
    placement = place_swatch(
        swatch(spool_id=1234567890, vendor="", color_hexes=()), layout, SHEET_METRICS
    )
    assert placement.caption.lines[0].endswith("…")
    assert placement.truncated


def test_text_is_normalised() -> None:
    nfd = "Grün"
    nfc = "Grün"
    box = seed_box(L4737REV)
    a, _ = _render(swatch(color_name=nfd), box, SHEET_METRICS, 300)
    b, _ = _render(swatch(color_name=nfc), box, SHEET_METRICS, 300)
    assert a.tobytes() == b.tobytes()
    c, _ = _render(swatch(vendor="Tec​Bears"), box, SHEET_METRICS, 300)
    d, _ = _render(swatch(vendor="TecBears"), box, SHEET_METRICS, 300)
    assert c.tobytes() == d.tobytes()
    assert text_mm("Fluss­rate", 700, 1.6) == text_mm("Flussrate", 700, 1.6)
    wide = swatch_layout(SwatchTier.FULL, 9000, 4000, SHEET_METRICS)
    e, _ = render_swatch(
        swatch(color_name="Fluss­rate"),
        SAMPLE_URL,
        layout=wide,
        width_px=to_px(9000, 300),
        height_px=to_px(4000, 300),
        dpi=300,
        metrics=SHEET_METRICS,
    )
    f, _ = render_swatch(
        swatch(color_name="Flussrate"),
        SAMPLE_URL,
        layout=wide,
        width_px=to_px(9000, 300),
        height_px=to_px(4000, 300),
        dpi=300,
        metrics=SHEET_METRICS,
    )
    assert e.tobytes() == f.tobytes()


def _rule_rows(image: Image.Image) -> list[int]:
    """Rows that are black over the whole width."""
    gray = image.convert("L")
    return [
        y for y in range(gray.height) if all(gray.getpixel((x, y)) < 128 for x in range(gray.width))
    ]


def test_full_tier_draws_footer_rule() -> None:
    image, _ = _render(every_row(), QL_BOX, TAPE_METRICS, 300)
    rows = _rule_rows(image)
    bar = set(range(to_px(960, 300), to_px(1300, 300)))
    rule = [y for y in rows if y not in bar]
    assert rule
    assert min(rule) == to_px(3395 - 250, 300)


def test_no_footer_tier_has_no_rule() -> None:
    box = seed_box(L4737REV)
    for dpi in SHEET_DPIS:
        image, _ = _render(every_row(), box, SHEET_METRICS, dpi)
        bar = set(range(to_px(480, dpi), to_px(820, dpi)))
        assert [y for y in _rule_rows(image) if y not in bar] == []


def test_core_draws_no_column_text() -> None:
    calls: list[str] = []
    original = ss.font.draw_glyphs

    def spy(draw: Any, x_hmm: float, baseline: int, text: str, **kw: Any) -> None:
        calls.append(text)
        original(draw, x_hmm, baseline, text, **kw)

    with patch.object(ss.font, "draw_glyphs", spy):
        _render(every_row(), seed_box(L4736REV), SHEET_METRICS, 300)
    for word in ("Nozzle", "Bed", "Net", "Location", "AMS slot 9", "1000 g"):
        assert word not in calls
    assert "#FF5F00" in calls


def test_missing_rows_leave_no_gap_marks() -> None:
    calls: list[str] = []
    original = ss.font.draw_glyphs

    def spy(draw: Any, x_hmm: float, baseline: int, text: str, **kw: Any) -> None:
        calls.append(text)
        original(draw, x_hmm, baseline, text, **kw)

    spool = swatch(nozzle_c=(210, 230), location="Shelf A2")
    with patch.object(ss.font, "draw_glyphs", spy):
        _render(spool, seed_box(L4737REV), SHEET_METRICS, 300)
    assert "—" not in "".join(calls)
    assert "Bed" not in calls
    placement = _place(spool, seed_box(L4737REV), SHEET_METRICS)
    assert [len(c.rows) for c in placement.columns] == [1, 1]
    assert placement.columns[0].rows[0].baselines == placement.columns[1].rows[0].baselines


def test_below_core_is_refused_as_label_size() -> None:
    with pytest.raises(ContentTypeDataMismatchError) as exc:
        layout_for_box(*seed_box("avery-5167"), SHEET_METRICS)
    assert exc.value.missing_fields == ("label_size",)
    with pytest.raises(ContentTypeDataMismatchError):
        layout_for_box(2079, 1810, TAPE_METRICS)


def test_sheet_payload_too_long_is_qr_does_not_fit() -> None:
    payload = "https://x.example/" + "a" * 2400
    with pytest.raises(QrDoesNotFitError):
        _render(swatch(), seed_box(L4736REV), SHEET_METRICS, 300, payload)


def test_tape_payload_too_long_is_qr_payload_too_long() -> None:
    payload = "https://x.example/" + "a" * 2400
    with pytest.raises(QrPayloadTooLongError) as exc:
        _render(swatch(), QL_BOX, TAPE_METRICS, 300, payload)
    assert exc.value.length == len(payload.encode())
    assert 0 < exc.value.max_bytes < 2400


def test_value_wraps_after_its_separator() -> None:
    """Acceptance finding: „AMS 1 · slot 2“ broke as „AMS 1 · slot“ / „2“; the separator is the
    natural break of a value made of parts."""
    placement = _place(swatch(location="AMS 1 · slot 2"), seed_box(L4737REV), SHEET_METRICS)
    assert placement.columns[1].rows[-1].value == ("AMS 1 ·", "slot 2")


def test_tape_hex_block_sits_beside_the_first_vendor_line() -> None:
    """Acceptance finding: on tape the hex code sat at the bottom of the two-line vendor block,
    far from a one-line vendor; it is bottom-aligned to the first vendor line instead."""
    placement = _place(swatch(color_hexes=("FF5F00",)), QL_BOX, TAPE_METRICS)
    hex_run = next(r for r in placement.runs if r.text == "#FF5F00")
    vendor_run = next(r for r in placement.runs if r.text == "TecBears")
    assert hex_run.baseline == 480 - 55
    assert abs(hex_run.baseline - vendor_run.baseline) < 100
