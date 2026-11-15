# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The swatch-style Spoolman spool label (#346): texts, fonts, metrics, tiers, layout, drawing.

One package, split by concern; this module re-exports the public names, so callers import from
``app.services.spool_swatch``:

* ``text`` — words and numbers in the hub language (R-346-6);
* ``font`` — the font, text extent from design units and glyph-wise drawing (R-346-7);
* ``metrics`` — the two metric sets and the text rule (R-346-7, R-346-7a);
* ``layout`` — tiers, thresholds and the data-independent positions (R-346-8);
* ``draw`` — the QR symbol and the one function that draws the label (R-346-2, R-346-11).
"""

from __future__ import annotations

from app.services.spool_swatch import font
from app.services.spool_swatch.draw import (
    SWATCH_TAPE_MARGIN_PX,
    SWATCH_TAPE_PX,
    PlacedColumn,
    PlacedRow,
    Run,
    SwatchPlacement,
    place_swatch,
    render_swatch,
    render_tape_swatch,
    swatch_for_batch,
    swatch_symbol,
    tape_box_hmm,
)
from app.services.spool_swatch.font import (
    ATKINSON_CAP_RATIO,
    SWATCH_FONT_PATH,
    draw_glyphs,
    font_size,
    glyph_advances_mm,
    run_span_px,
    swatch_font,
    text_mm,
    to_px,
)
from app.services.spool_swatch.layout import (
    SwatchLayout,
    SwatchTier,
    layout_for_box,
    swatch_layout,
    swatch_tier,
    tier_thresholds,
)
from app.services.spool_swatch.metrics import (
    ELLIPSIS,
    SHEET_METRICS,
    TAPE_METRICS,
    FittedText,
    SwatchMetrics,
    fit_text,
    label_lines,
    label_slot,
)
from app.services.spool_swatch.text import (
    COLUMN_1_KEYS,
    COLUMN_2_KEYS,
    SWATCH_REFERENCE_VALUES,
    SWATCH_TEXTS,
    SwatchText,
    clean_text,
    swatch_text,
)

__all__ = [
    "ATKINSON_CAP_RATIO",
    "COLUMN_1_KEYS",
    "COLUMN_2_KEYS",
    "ELLIPSIS",
    "SHEET_METRICS",
    "SWATCH_FONT_PATH",
    "SWATCH_REFERENCE_VALUES",
    "SWATCH_TAPE_MARGIN_PX",
    "SWATCH_TAPE_PX",
    "SWATCH_TEXTS",
    "TAPE_METRICS",
    "FittedText",
    "PlacedColumn",
    "PlacedRow",
    "Run",
    "SwatchLayout",
    "SwatchMetrics",
    "SwatchPlacement",
    "SwatchText",
    "SwatchTier",
    "clean_text",
    "draw_glyphs",
    "fit_text",
    "font",
    "font_size",
    "glyph_advances_mm",
    "label_lines",
    "label_slot",
    "layout_for_box",
    "place_swatch",
    "render_swatch",
    "render_tape_swatch",
    "run_span_px",
    "swatch_font",
    "swatch_for_batch",
    "swatch_layout",
    "swatch_symbol",
    "swatch_text",
    "swatch_tier",
    "tape_box_hmm",
    "text_mm",
    "tier_thresholds",
    "to_px",
]
