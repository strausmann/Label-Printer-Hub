# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Metric sets of the swatch label and the text rule (#346, R-346-7 and R-346-7a).

All lengths are hundredths of a millimetre (hmm), caps are millimetres. Two sets: the 62 mm QL
tape and sheet cells (the sheet set keeps the 1.6 mm minimum cap height of OC-27). Every fit
decision is taken in mm from the design units (``text_mm``), never at a render size, so it is
the same at every resolution.

Text that does not fit follows one order (maintainer ruling 2026-11-15): wrap onto a further
line where the element's slot has room, shrink the font down to the medium's row cap, and only
then cut with ``…`` and report ``truncated``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Final, Literal, NamedTuple

from app.services.spool_swatch.font import Weight, text_mm
from app.services.spool_swatch.text import (
    COLUMN_1_KEYS,
    COLUMN_2_KEYS,
    SOFT_HYPHEN,
    SWATCH_REFERENCE_VALUES,
    clean_text,
)

ELLIPSIS: Final = "…"
_JOIN: Final = " · "


class SwatchMetrics(NamedTuple):
    """One metric set (R-346-7); lengths in hmm, caps in mm."""

    name: Literal["tape", "sheet"]
    row_cap_mm: float
    """Rows, caption, hex codes and footer; also the minimum every shrink stops at."""
    row_pitch: int
    row_baseline: int
    """Baseline above the bottom of a row."""
    vendor_lines: int
    """Lines of the vendor block at the vendor cap (tape 2, sheet 1; ruling N2)."""
    vendor_block: int
    """V: height of the vendor block."""
    column_1: int
    column_2: int
    footer: int
    """F: rule + gap + one row."""
    q_min: int
    test_dpis: tuple[int, ...]
    """The resolutions the rendering tests run at."""
    vendor_cap_mm: float = 2.9
    vendor_line: int = 480
    vendor_baseline: int = 95
    bar_h: int = 340
    bar_cap_mm: float = 2.0
    bar_baseline: int = 75
    bar_inset: int = 60
    colour_gap: int = 20
    colour_h: int = 300
    colour_cap_mm: float = 1.9
    colour_baseline: int = 65
    run_margin: float = 8.5
    """Margin per glyph run: 1 px at 300 dpi, the coarsest rendered resolution."""
    tab_gap: int = 80
    """Between a column's label run and its value run (0.8 mm)."""
    column_gap: int = 100
    qr_gap: int = 80
    footer_rule: int = 20
    footer_gap: int = 40
    q_full: int = 1300
    q_max: int = 1550
    c_min: int = 1200
    hex_gap: int = 100
    """Between the vendor and the hex block (1.0 mm)."""
    vendor_min: int = 2000
    """The vendor keeps at least this much width beside the hex block."""
    lines_two_columns: int = 6
    lines_first_column: int = 5


TAPE_METRICS: Final = SwatchMetrics(
    name="tape",
    row_cap_mm=1.25,
    row_pitch=190,
    row_baseline=55,
    vendor_lines=2,
    vendor_block=960,
    column_1=1660,
    column_2=1950,
    footer=250,
    q_min=800,
    test_dpis=(300,),
)
SHEET_METRICS: Final = SwatchMetrics(
    name="sheet",
    row_cap_mm=1.6,
    row_pitch=240,
    row_baseline=75,
    vendor_lines=1,
    vendor_block=480,
    column_1=2100,
    column_2=2470,
    footer=300,
    q_min=700,
    test_dpis=(300, 600),
)


def label_slot(metrics: SwatchMetrics, column: Literal[1, 2]) -> int:
    """Width (hmm) a field label may take in ``column``: column width - 0.8 mm - the widest
    reference value's run - the label's run margin (R-346-7)."""
    keys = COLUMN_1_KEYS if column == 1 else COLUMN_2_KEYS
    width = metrics.column_1 if column == 1 else metrics.column_2
    value = max(
        text_mm(v, 400, metrics.row_cap_mm) for k in keys for v in SWATCH_REFERENCE_VALUES[k]
    )
    value_run = value * 100 + metrics.run_margin
    return math.floor(width - metrics.tab_gap - value_run - metrics.run_margin)


def _fits(text: str, weight: Weight, cap_mm: float, slot_hmm: float) -> bool:
    return text_mm(text, weight, cap_mm) * 100 <= slot_hmm


def _breaks(text: str) -> list[tuple[str, str]]:
    """Every (first line, rest) split of ``text`` at a space or a soft hyphen."""
    splits: list[tuple[str, str]] = []
    for i, ch in enumerate(text):
        if ch == " ":
            first, rest = text[:i].rstrip(), text[i + 1 :].lstrip()
        elif ch == SOFT_HYPHEN:
            first, rest = text[:i] + "-", text[i + 1 :]
        else:
            continue
        if first.strip("-") and rest:
            splits.append((first, rest))
    return splits


def _last_fit(text: str, weight: Weight, cap_mm: float, slot: float) -> tuple[str, str] | None:
    """The split at the last break whose first line fits ``slot``."""
    fitting = [s for s in _breaks(text) if _fits(s[0], weight, cap_mm, slot)]
    return fitting[-1] if fitting else None


def label_lines(label: str, slot_hmm: int, weight: Weight, cap_mm: float) -> tuple[str, ...]:
    """A field label as one or two lines, decided with ``text_mm`` (never at render size).

    One line if it fits the slot, else two, broken at the last space or soft hyphen that lets
    the first line fit (a soft hyphen is drawn as ``-``); never more than two. A label without a
    usable break point stays one line and follows ``fit_text``.
    """
    text = clean_text(label)
    if _fits(text, weight, cap_mm, slot_hmm):
        return (text.replace(SOFT_HYPHEN, ""),)
    split = _last_fit(text, weight, cap_mm, slot_hmm)
    if split is None:
        return (text.replace(SOFT_HYPHEN, ""),)
    return (split[0].replace(SOFT_HYPHEN, ""), split[1].replace(SOFT_HYPHEN, ""))


class FittedText(NamedTuple):
    lines: tuple[str, ...]
    cap_mm: float
    truncated: bool


Element = Literal[
    "label", "value", "vendor", "title", "colour", "hex_block", "hex_line", "footer", "caption"
]

_WEIGHT: Final[dict[str, Weight]] = {
    "label": 700,
    "value": 400,
    "vendor": 700,
    "title": 700,
    "colour": 700,
    "hex_block": 400,
    "hex_line": 400,
    "footer": 400,
    "caption": 400,
}


def cut(text: str, weight: Weight, cap_mm: float, slot: float) -> str:
    """The longest prefix of ``text`` with ``…`` that fits ``slot``; ``""`` if not even ``…``."""
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _fits(text[:mid].rstrip() + ELLIPSIS, weight, cap_mm, slot):
            lo = mid
        else:
            hi = mid - 1
    shortened = text[:lo].rstrip() + ELLIPSIS
    return shortened if _fits(shortened, weight, cap_mm, slot) else ""


def _shrunk_cap(texts: Sequence[str], weight: Weight, start: float, slot: float) -> float:
    """The largest cap <= ``start`` at which every text fits ``slot`` (extent is linear in the
    cap), rounded down to 0.001 mm."""
    widest = max(text_mm(t, weight, 1.0) for t in texts) * 100
    if widest <= 0:
        return start
    return min(start, math.floor(slot / widest * 1000) / 1000)


def _one_line(text: str, weight: Weight, start: float, minimum: float, slot: float) -> FittedText:
    """Shrink from ``start`` down to ``minimum``, then cut."""
    if _fits(text, weight, start, slot):
        return FittedText((text,), start, False)
    cap = _shrunk_cap([text], weight, start, slot)
    if cap >= minimum:
        return FittedText((text,), cap, False)
    return FittedText((cut(text, weight, minimum, slot),), minimum, True)


def _value_split(text: str, weight: Weight, cap: float, slot: float) -> tuple[str, str] | None:
    """A value's break: after the last ``·`` that lets the first line fit (it separates the
    value's parts, „AMS 1 · slot 2“), else at the last fitting space."""
    fitting = [s for s in _breaks(text) if _fits(s[0], weight, cap, slot)]
    at_separator = [s for s in fitting if s[0].endswith("·")]
    if at_separator:
        return at_separator[-1]
    return fitting[-1] if fitting else None


def _wrap_words(
    text: str, weight: Weight, cap: float, slot: float, max_lines: int
) -> tuple[tuple[str, ...], bool]:
    """Greedy word wrap into at most ``max_lines``; the last line is cut if text is left."""
    lines: list[str] = []
    rest = text
    while rest and len(lines) < max_lines - 1:
        if _fits(rest, weight, cap, slot):
            break
        split = _value_split(rest.replace(SOFT_HYPHEN, ""), weight, cap, slot)
        if split is None:
            break
        lines.append(split[0])
        rest = split[1]
    if _fits(rest, weight, cap, slot):
        return (*lines, rest), False
    return (*lines, cut(rest, weight, cap, slot)), True


def _vendor(text: str, slot: float, m: SwatchMetrics) -> FittedText:
    weight: Weight = 700
    cap = m.vendor_cap_mm
    if _fits(text, weight, cap, slot):
        return FittedText((text,), cap, False)
    splits = _breaks(text.replace(SOFT_HYPHEN, ""))
    if not splits:  # one word: shrink one line to the row cap, then cut
        return _one_line(text, weight, cap, m.row_cap_mm, slot)
    # Two lines: at the vendor cap on tape (the reserved second line), as two rows at the row
    # cap inside the one block on sheets. The most balanced split whose lines both fit.
    two_cap = cap if m.vendor_lines >= 2 else m.row_cap_mm

    def widest(split: tuple[str, str], at: float) -> float:
        return max(text_mm(split[0], weight, at), text_mm(split[1], weight, at))

    both = [s for s in splits if widest(s, two_cap) * 100 <= slot]
    if both:
        best = min(both, key=lambda s: widest(s, two_cap))
        return FittedText(best, two_cap, False)
    if m.vendor_lines >= 2:  # tape: shrink both lines together toward the row cap
        best = min(splits, key=lambda s: widest(s, 1.0))
        shrunk = _shrunk_cap(best, weight, cap, slot)
        if shrunk >= m.row_cap_mm:
            return FittedText(best, shrunk, False)
        two_cap = m.row_cap_mm
    split = _last_fit(text, weight, two_cap, slot)
    if split is None:  # not even the first word fits: one line, shrunk and cut
        return _one_line(text, weight, cap, m.row_cap_mm, slot)
    second = split[1]
    if not _fits(second, weight, two_cap, slot):
        second = cut(second, weight, two_cap, slot)
    return FittedText((split[0], second), two_cap, second != split[1])


def _colour(text: str, slot: float, free_lines: int, m: SwatchMetrics) -> FittedText:
    weight: Weight = 700
    cap = m.colour_cap_mm
    if _fits(text, weight, cap, slot):
        return FittedText((text,), cap, False)
    if free_lines >= 2:
        split = _last_fit(text, weight, cap, slot)
        if split is not None:
            second = split[1]
            if not _fits(second, weight, cap, slot):
                second = cut(second, weight, cap, slot)
            return FittedText((split[0], second), cap, second != split[1])
    return _one_line(text, weight, cap, m.row_cap_mm, slot)


def _codes(codes: Sequence[str], slot: float, max_rows: int, m: SwatchMetrics) -> FittedText:
    """Hex codes, as many per row as fit ``slot``, in at most ``max_rows``; ``+N`` last."""
    weight: Weight = 400
    cap = m.row_cap_mm
    rows: list[list[str]] = []
    for code in codes:
        if rows and _fits(_JOIN.join([*rows[-1], code]), weight, cap, slot):
            rows[-1].append(code)
        else:
            rows.append([code])
    if len(rows) <= max_rows:
        return FittedText(tuple(_JOIN.join(r) for r in rows), cap, False)
    kept = rows[: max_rows - 1]
    last = rows[max_rows - 1]
    before = sum(len(r) for r in kept)
    # The last slot of the last row becomes "+N" for every code not shown.
    for keep in range(len(last) - 1, -1, -1):
        candidate = _JOIN.join([*last[:keep], f"+{len(codes) - before - keep}"])
        if keep == 0 or _fits(candidate, weight, cap, slot):
            return FittedText((*(_JOIN.join(r) for r in kept), candidate), cap, True)
    raise AssertionError("unreachable")  # pragma: no cover


def fit_text(
    element: Element,
    text: str | Sequence[str],
    *,
    slot_hmm: int,
    free_lines: int,
    metrics: SwatchMetrics,
    language: str,
) -> FittedText:
    """Fit ``text`` (hex elements: the codes) into ``slot_hmm`` and at most ``free_lines``.

    R-346-7a in this order: wrap, shrink (down to the row cap), cut with ``…`` (hex: ``+N``) and
    ``truncated=True``. Decided in mm. ``language`` is part of the call for symmetry with the
    texts; the rules themselves are language-neutral.
    """
    del language
    m = metrics
    if element in ("hex_block", "hex_line"):
        codes = [text] if isinstance(text, str) else list(text)
        if not codes:
            return FittedText((), m.row_cap_mm, False)
        return _codes(codes, slot_hmm, max(1, free_lines), m)
    assert isinstance(text, str)
    clean = clean_text(text)
    weight = _WEIGHT[element]
    if not clean.replace(SOFT_HYPHEN, ""):
        return FittedText((), m.row_cap_mm, False)
    match element:
        case "vendor":
            return _vendor(clean, slot_hmm, m)
        case "title":
            return _one_line(clean, weight, m.bar_cap_mm, m.row_cap_mm, slot_hmm)
        case "colour":
            return _colour(clean, slot_hmm, free_lines, m)
        case "label":
            lines = label_lines(clean, slot_hmm, weight, m.row_cap_mm)[: max(1, free_lines)]
            shown = tuple(
                line
                if _fits(line, weight, m.row_cap_mm, slot_hmm)
                else cut(line, weight, m.row_cap_mm, slot_hmm)
                for line in lines
            )
            return FittedText(shown, m.row_cap_mm, shown != lines)
        case "value":
            lines, cut_off = _wrap_words(
                clean.replace(SOFT_HYPHEN, ""), weight, m.row_cap_mm, slot_hmm, max(1, free_lines)
            )
            return FittedText(lines, m.row_cap_mm, cut_off)
        case _:  # footer, caption: one line at the row cap
            plain = clean.replace(SOFT_HYPHEN, "")
            if _fits(plain, weight, m.row_cap_mm, slot_hmm):
                return FittedText((plain,), m.row_cap_mm, False)
            return FittedText((cut(plain, weight, m.row_cap_mm, slot_hmm),), m.row_cap_mm, True)
