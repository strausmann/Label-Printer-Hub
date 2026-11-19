# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Sizes of the swatch label from design units (#346, R-346-7).

The layout is resolution-independent: font sizes come from the design cap height, extents from
the design advances, wraps are decided in mm. Text is drawn glyph by glyph and its ink stays
within the design width plus one pixel. The tests here are version-independent, except
``test_drawn_widths_match_the_reference`` (marked ``swatch_reference``), which pins the drawn
ink widths and runs only in the ``swatch-text-metrics`` CI job on Pillow 11.3 and 13.
"""

from __future__ import annotations

import inspect
import json
import math
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from app.services.spool_swatch import (
    SHEET_METRICS,
    SWATCH_REFERENCE_VALUES,
    SWATCH_TEXTS,
    TAPE_METRICS,
    SwatchMetrics,
    draw_glyphs,
    font_size,
    label_lines,
    label_slot,
    run_span_px,
    text_mm,
    to_px,
)
from app.services.spool_swatch.font import _glyph_units
from app.services.spool_swatch.text import COLUMN_1_KEYS, COLUMN_2_KEYS
from PIL import Image, ImageDraw, ImageFont

from tests.helpers.spool_swatch import ink_bbox

FIXTURE = Path(__file__).parents[2] / "fixtures" / "spool_swatch" / "drawn_widths.json"
METRICS = {"sheet": SHEET_METRICS, "tape": TAPE_METRICS}
MEDIA_DPIS = [(name, dpi) for name, m in METRICS.items() for dpi in m.test_dpis]
OFFSETS = [n * 50 for n in range(18)]  # 0 to 8.5 hmm in 0.5 hmm steps (here x100: hmm/100)
COLUMNS = ((1, COLUMN_1_KEYS), (2, COLUMN_2_KEYS))


def _offsets() -> list[float]:
    return [n * 0.5 for n in range(18)]  # 0.0 ... 8.5 hmm


def _advance_units(ch: str, weight: int) -> float:
    return _glyph_units(ch, weight)[0]  # type: ignore[arg-type]


def _label_lines_of(metrics: SwatchMetrics) -> list[str]:
    """Every label line the label prints, en and de, as wrapped in its column's slot."""
    lines: list[str] = []
    for column, keys in COLUMNS:
        for language in ("en", "de"):
            for key in keys:
                lines += label_lines(
                    SWATCH_TEXTS[language][key],
                    label_slot(metrics, column),
                    700,
                    metrics.row_cap_mm,
                )
    return sorted(set(lines))


def _reference_values() -> list[str]:
    return sorted({v for values in SWATCH_REFERENCE_VALUES.values() for v in values})


def _texts(metrics: SwatchMetrics) -> list[tuple[str, int]]:
    return [(t, 700) for t in _label_lines_of(metrics)] + [(v, 400) for v in _reference_values()]


def _draw(text: str, weight: int, metrics: SwatchMetrics, dpi: int, x_hmm: float) -> Image.Image:
    canvas = Image.new("L", (to_px(4000, dpi), to_px(800, dpi)), 255)
    draw_glyphs(
        ImageDraw.Draw(canvas),
        x_hmm,
        500,
        text,
        weight=weight,  # type: ignore[arg-type]
        cap_mm=metrics.row_cap_mm,
        dpi=dpi,
        fill=0,
    )
    return canvas


def test_font_size_from_the_design_cap_height() -> None:
    assert font_size(1.6, 300) == pytest.approx(28.290, abs=1e-3)
    assert font_size(1.6, 600) == pytest.approx(56.580, abs=1e-3)
    assert font_size(1.25, 300) == pytest.approx(22.101, abs=1e-3)
    assert font_size(1.6, 300) != round(font_size(1.6, 300))


def test_font_size_does_not_measure_glyph_bboxes() -> None:
    with patch.object(ImageFont.FreeTypeFont, "getbbox", side_effect=AssertionError):
        assert font_size(1.6, 300) == pytest.approx(28.290, abs=1e-3)


def test_text_mm_is_resolution_independent() -> None:
    assert "dpi" not in inspect.signature(text_mm).parameters
    assert text_mm("Nozzle", 700, 1.6) == pytest.approx(7.631, abs=0.005)
    assert text_mm("210\u2013230 °C", 400, 1.6) == pytest.approx(12.350, abs=0.005)
    assert text_mm("Location", 700, 1.6) == pytest.approx(9.612, abs=0.005)
    assert text_mm("60 °C · 6\u20138 h", 400, 1.6) == pytest.approx(14.060, abs=0.005)


def test_text_mm_counts_ink_past_the_advance() -> None:
    advance = _advance_units("q", 700) * 1.6 / 0.668 / 1000
    assert text_mm("q", 700, 1.6) > advance


def test_no_kerning_in_measure_and_draw() -> None:
    a = _advance_units("A", 700) * 1.6 / 0.668 / 1000
    assert text_mm("AV", 700, 1.6) == pytest.approx(a + text_mm("V", 700, 1.6), abs=1e-9)
    calls: list[tuple[int, int]] = []
    original = ImageDraw.ImageDraw.text

    def spy(self: ImageDraw.ImageDraw, xy: Any, text: str, *args: Any, **kw: Any) -> None:
        calls.append(xy)
        original(self, xy, text, *args, **kw)

    with patch.object(ImageDraw.ImageDraw, "text", spy):
        _draw("AV", 700, SHEET_METRICS, 600, 0)
    assert [x for x, _ in calls] == [0, to_px(a * 100, 600)]


@pytest.mark.parametrize(
    ("metrics", "widths"), [(SHEET_METRICS, (2100, 2470)), (TAPE_METRICS, (1660, 1950))]
)
def test_column_widths_from_design_units(metrics: SwatchMetrics, widths: tuple[int, int]) -> None:
    assert (metrics.column_1, metrics.column_2) == widths
    for (column, keys), width in zip(COLUMNS, widths, strict=True):
        label = max(
            text_mm(line, 700, metrics.row_cap_mm)
            for lang in ("en", "de")
            for key in keys
            for line in label_lines(
                SWATCH_TEXTS[lang][key], label_slot(metrics, column), 700, metrics.row_cap_mm
            )
        )
        value = max(
            text_mm(v, 400, metrics.row_cap_mm) for k in keys for v in SWATCH_REFERENCE_VALUES[k]
        )
        runs = label * 100 + metrics.run_margin + metrics.tab_gap + value * 100 + metrics.run_margin
        assert math.ceil(runs / 10) * 10 == width


@pytest.mark.parametrize("metrics", [SHEET_METRICS, TAPE_METRICS])
def test_long_labels_wrap_onto_a_second_line(metrics: SwatchMetrics) -> None:
    cap = metrics.row_cap_mm

    def lines(text: str, column: int) -> tuple[str, ...]:
        return label_lines(text, label_slot(metrics, column), 700, cap)

    assert lines("Flow ratio", 1) == ("Flow", "ratio")
    assert lines("Fluss­rate", 1) == ("Fluss-", "rate")
    assert lines("Empty spool", 2) == ("Empty", "spool")
    assert lines("Trock­nung", 2) == ("Trock-", "nung")
    assert lines("Leer­spule", 2) == ("Leer-", "spule")
    for text, column in (("Nozzle", 1), ("PA (K)", 1), ("Location", 2), ("Ort", 2)):
        assert lines(text, column) == (text,)


def test_label_slots_in_hmm() -> None:
    assert (label_slot(SHEET_METRICS, 1), label_slot(SHEET_METRICS, 2)) == (768, 967)
    assert (label_slot(TAPE_METRICS, 1), label_slot(TAPE_METRICS, 2)) == (598, 754)


def test_wrapping_does_not_depend_on_the_resolution() -> None:
    params = set(inspect.signature(label_lines).parameters)
    assert params == {"label", "slot_hmm", "weight", "cap_mm"}
    expected = label_lines("Fluss­rate", 768, 700, 1.6)
    original = ImageFont.FreeTypeFont.getlength

    def guarded(self: ImageFont.FreeTypeFont, *args: Any, **kw: Any) -> float:
        if self.size < 1000:
            raise AssertionError("measured at render size")
        return original(self, *args, **kw)

    _glyph_units.cache_clear()
    with patch.object(ImageFont.FreeTypeFont, "getlength", guarded):
        assert label_lines("Fluss­rate", 768, 700, 1.6) == expected
        assert label_lines("Empty spool", 967, 700, 1.6) == ("Empty", "spool")


@pytest.mark.parametrize("metrics", [SHEET_METRICS, TAPE_METRICS])
def test_no_shipped_label_lacks_a_break_point_it_needs(metrics: SwatchMetrics) -> None:
    for column, keys in COLUMNS:
        slot = label_slot(metrics, column)
        for language in ("en", "de"):
            for key in keys:
                label = SWATCH_TEXTS[language][key]
                lines = label_lines(label, slot, 700, metrics.row_cap_mm)
                assert 1 <= len(lines) <= 2
                for line in lines:
                    assert text_mm(line, 700, metrics.row_cap_mm) * 100 <= slot, (label, line)


@pytest.mark.parametrize(("medium", "dpi"), MEDIA_DPIS)
@pytest.mark.parametrize("offset", _offsets())
def test_glyphwise_text_stays_within_design_plus_one_px(
    medium: str, dpi: int, offset: float
) -> None:
    metrics = METRICS[medium]
    for text, weight in _texts(metrics):
        box = ink_bbox(_draw(text, weight, metrics, dpi, offset))
        assert box is not None
        _, end = run_span_px(offset, text_mm(text, weight, metrics.row_cap_mm), dpi)  # type: ignore[arg-type]
        assert box[2] <= end, (text, offset, box[2], end)


def test_pen_origin_is_the_computed_position() -> None:
    calls: list[tuple[int, int]] = []
    original = ImageDraw.ImageDraw.text

    def spy(self: ImageDraw.ImageDraw, xy: Any, text: str, *args: Any, **kw: Any) -> None:
        calls.append(xy)
        original(self, xy, text, *args, **kw)

    start = 123.4
    with patch.object(ImageDraw.ImageDraw, "text", spy):
        _draw("Düse", 700, SHEET_METRICS, 300, start)
    advances = [_advance_units(ch, 700) * 1.6 / 0.668 / 1000 * 100 for ch in "Düse"]
    expected = [to_px(start + sum(advances[:i]), 300) for i in range(4)]
    assert [x for x, _ in calls] == expected


@pytest.mark.parametrize(("medium", "dpi"), MEDIA_DPIS)
@pytest.mark.parametrize("offset", _offsets())
def test_ink_lies_between_origin_and_run_end(medium: str, dpi: int, offset: float) -> None:
    metrics = METRICS[medium]
    for text, weight in _texts(metrics):
        box = ink_bbox(_draw(text, weight, metrics, dpi, offset))
        assert box is not None
        start, end = run_span_px(offset, text_mm(text, weight, metrics.row_cap_mm), dpi)  # type: ignore[arg-type]
        assert box[0] >= start, (text, offset)
        assert box[2] <= end, (text, offset)


@pytest.mark.parametrize(("medium", "dpi"), MEDIA_DPIS)
def test_runs_fit_the_columns(medium: str, dpi: int) -> None:
    metrics = METRICS[medium]
    x = 0
    for (column, keys), width in zip(COLUMNS, (metrics.column_1, metrics.column_2), strict=True):
        cap = metrics.row_cap_mm
        label = max(
            text_mm(line, 700, cap)
            for lang in ("en", "de")
            for key in keys
            for line in label_lines(SWATCH_TEXTS[lang][key], label_slot(metrics, column), 700, cap)
        )
        value = max(text_mm(v, 400, cap) for k in keys for v in SWATCH_REFERENCE_VALUES[k])
        label_start, label_end = run_span_px(x, label, dpi)
        tab = x + label * 100 + metrics.run_margin + metrics.tab_gap
        value_start, value_end = run_span_px(tab, value, dpi)
        column_start, column_end = to_px(x, dpi), to_px(x + width, dpi)
        assert column_start <= label_start
        assert label_end <= value_start
        assert value_end <= column_end
        x += width + metrics.column_gap


@pytest.mark.swatch_reference
def test_drawn_widths_match_the_reference() -> None:
    """Drawn ink widths within 1 px of the committed reference.

    Refresh after a change of the texts, the reference values, the caps or the font file:
    ``SWATCH_WIDTHS_WRITE=1 pytest -m swatch_reference tests/unit/services/
    test_spool_swatch_metrics.py`` on the newest Pillow of the CI matrix, then commit the file.
    """
    measured: dict[str, int] = {}
    for medium, dpi in MEDIA_DPIS:
        metrics = METRICS[medium]
        for text, weight in _texts(metrics):
            box = ink_bbox(_draw(text, weight, metrics, dpi, 0))
            assert box is not None
            measured[f"{medium}/{dpi}/{weight}/{text}"] = box[2] - box[0]
    if os.environ.get("SWATCH_WIDTHS_WRITE") == "1":
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(
            json.dumps(measured, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    reference = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert set(reference) == set(measured)
    off = {k: (reference[k], v) for k, v in measured.items() if abs(reference[k] - v) > 1}
    assert not off


def _line_extent(text: str, weight: int, cap: float, baseline: int, dpi: int) -> tuple[int, int]:
    canvas = Image.new("L", (to_px(6000, dpi), to_px(1200, dpi)), 255)
    draw_glyphs(
        ImageDraw.Draw(canvas),
        0,
        baseline,
        text,
        weight=weight,  # type: ignore[arg-type]
        cap_mm=cap,
        dpi=dpi,
        fill=0,
    )
    box = ink_bbox(canvas)
    assert box is not None
    return box[1], box[3] - 1


@pytest.mark.parametrize(("medium", "dpi"), MEDIA_DPIS)
def test_baselines_leave_room_for_descenders_and_accents(medium: str, dpi: int) -> None:
    m = METRICS[medium]
    top = 400  # every line is placed with its top at 4.0 mm
    # Rows: a capital with an accent is taller than the row pitch less the descender room
    # (Ü 866 units = 2.07 mm at cap 1.6 against a 2.4 mm pitch), so a row's accent reaches into
    # the descender room of the row above; it must stay below that row's baseline.
    baseline = top + m.row_pitch - m.row_baseline
    accent_top, _ = _line_extent("Ü", 700, m.row_cap_mm, baseline, dpi)
    _, descender_bottom = _line_extent("gpyqj", 700, m.row_cap_mm, baseline, dpi)
    assert accent_top > to_px(top - m.row_baseline, dpi)
    assert descender_bottom < to_px(top + m.row_pitch, dpi)
    lines = [  # (cap, weight, line height, baseline above the line bottom)
        (m.vendor_cap_mm, 700, m.vendor_line, m.vendor_baseline),
        (m.bar_cap_mm, 700, m.bar_h, m.bar_baseline),
        (m.colour_cap_mm, 700, m.colour_gap + m.colour_h, m.colour_baseline),
    ]
    for cap, weight, height, above in lines:
        baseline = top + height - above
        accent_top, _ = _line_extent("Ü", weight, cap, baseline, dpi)
        _, descender_bottom = _line_extent("gpyqj", weight, cap, baseline, dpi)
        assert accent_top >= to_px(top, dpi), (cap, dpi)
        assert descender_bottom < to_px(top + height, dpi), (cap, dpi)
