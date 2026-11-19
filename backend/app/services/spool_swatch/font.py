# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Font, text extent and glyph-wise drawing of the swatch label (#346, R-346-7).

Every size comes from the font's design units, never from a rendered bounding box: the font
size from the design cap height (``OS/2.sCapHeight`` 668 of 1000 units), the extent of a text
from the glyphs' design advances. The font loads with the BASIC layout engine everywhere (the
shipped image has no ``libfribidi``; a host with it would pick RAQM and kern), and text is drawn
glyph by glyph at the positions the design units give, converted to pixels once per glyph. A
whole-string ``draw.text`` would add up hinted, rounded advances and run past the design width.
The font has no ``kern`` table and BASIC applies no ``GPOS``, so there is no kerning in
measurement or drawing.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Final, Literal

from PIL import ImageDraw, ImageFont

from app.services.spool_swatch.text import drawable

_FONT_DIR: Final = Path(__file__).resolve().parents[2] / "page_render" / "fonts"
SWATCH_FONT_PATH: Final = _FONT_DIR / "AtkinsonHyperlegibleNext-Variable.ttf"
ATKINSON_CAP_RATIO: Final = 0.668
"""``OS/2.sCapHeight`` / ``unitsPerEm`` of Atkinson Hyperlegible Next."""
_UNITS_PER_EM: Final = 1000

Weight = Literal[400, 700]


@lru_cache(maxsize=256)
def swatch_font(weight: Weight, size: float) -> ImageFont.FreeTypeFont:
    """Atkinson Hyperlegible Next at ``weight`` and the (float) ``size`` in px, BASIC engine."""
    font = ImageFont.truetype(str(SWATCH_FONT_PATH), size, layout_engine=ImageFont.Layout.BASIC)
    font.set_variation_by_axes([weight])
    return font


def font_size(cap_mm: float, dpi: int) -> float:
    """Font size in px whose design cap height is ``cap_mm`` at ``dpi``; not rounded."""
    return cap_mm * dpi / 25.4 / ATKINSON_CAP_RATIO


def to_px(hmm: float, dpi: int) -> int:
    """Hundredths of a millimetre to device pixels: ``round`` (half to even), once per element."""
    return round(hmm * dpi / 2540)


@lru_cache(maxsize=4096)
def _glyph_units(ch: str, weight: Weight) -> tuple[float, float]:
    """(design advance, max(advance, ink right edge)) of one glyph, in font units."""
    font = swatch_font(weight, _UNITS_PER_EM)
    advance = float(font.getlength(ch))
    right = float(font.getbbox(ch)[2])
    return advance, max(advance, right)


def _mm_per_unit(cap_mm: float) -> float:
    return cap_mm / ATKINSON_CAP_RATIO / _UNITS_PER_EM


def glyph_advances_mm(text: str, weight: Weight, cap_mm: float) -> tuple[float, ...]:
    """The design advance of each glyph of ``text`` (as drawn) in mm; no kerning."""
    scale = _mm_per_unit(cap_mm)
    return tuple(_glyph_units(ch, weight)[0] * scale for ch in drawable(text))


def text_mm(text: str, weight: Weight, cap_mm: float) -> float:
    """Extent of ``text`` in mm: the advances up to the last glyph plus max(advance, ink right)
    of the last glyph. Independent of any resolution."""
    shown = drawable(text)
    if not shown:
        return 0.0
    units = sum(_glyph_units(ch, weight)[0] for ch in shown[:-1])
    units += _glyph_units(shown[-1], weight)[1]
    return units * _mm_per_unit(cap_mm)


def draw_glyphs(
    draw: ImageDraw.ImageDraw,
    x_hmm: float,
    baseline_hmm: int,
    text: str,
    *,
    weight: Weight,
    cap_mm: float,
    dpi: int,
    fill: int,
) -> None:
    """Draw ``text`` glyph by glyph: each at ``to_px`` of its design position, baseline-anchored."""
    shown = drawable(text)
    if not shown:
        return
    font = swatch_font(weight, font_size(cap_mm, dpi))
    y = to_px(baseline_hmm, dpi)
    pen_mm = 0.0
    for ch, advance in zip(shown, glyph_advances_mm(shown, weight, cap_mm), strict=True):
        if not ch.isspace():
            draw.text((to_px(x_hmm + pen_mm * 100, dpi), y), ch, font=font, fill=fill, anchor="ls")
        pen_mm += advance


def run_span_px(start_hmm: float, text_mm_: float, dpi: int) -> tuple[int, int]:
    """Pixel span a glyph run may use: ``(to_px(start), to_px(start + text) + 1)``."""
    return to_px(start_hmm, dpi), to_px(start_hmm + text_mm_ * 100, dpi) + 1
