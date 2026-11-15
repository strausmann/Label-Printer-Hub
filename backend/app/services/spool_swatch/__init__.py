# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The swatch-style Spoolman spool label (#346): texts, fonts, metrics, tiers, layout, drawing.

One package, split by concern; this module re-exports the public names, so callers import from
``app.services.spool_swatch``:

* ``text`` — words and numbers in the hub language (R-346-6);
* ``font`` — the font, text extent from design units and glyph-wise drawing (R-346-7);
"""

from __future__ import annotations

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
    "SWATCH_FONT_PATH",
    "SWATCH_REFERENCE_VALUES",
    "SWATCH_TEXTS",
    "SwatchText",
    "clean_text",
    "draw_glyphs",
    "font_size",
    "glyph_advances_mm",
    "run_span_px",
    "swatch_font",
    "swatch_text",
    "text_mm",
    "to_px",
]
