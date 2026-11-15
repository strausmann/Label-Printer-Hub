# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Words and numbers of the swatch label, in the hub language (#346, R-346-6).

Field labels are written out (no abbreviations); a label may break only at a space or at a
soft hyphen (U+00AD). Numbers use a decimal point in English and a comma in German, never a
thousands separator. A row without a value is left out; nothing prints "—".
"""

from __future__ import annotations

import datetime as dt
import math
import unicodedata
from typing import Final, NamedTuple

from app.schemas.spool_swatch import SpoolSwatch

SOFT_HYPHEN: Final = "­"

SWATCH_TEXTS: Final[dict[str, dict[str, str]]] = {
    "en": {
        "nozzle": "Nozzle",
        "bed": "Bed",
        "pressure_advance": "PA (K)",
        "flow_ratio": "Flow ratio",
        "drying": "Drying",
        "empty_spool": "Empty spool",
        "net": "Net",
        "location": "Location",
        "lot": "Lot {v}",
        "opened": "opened {v}",
    },
    "de": {
        "nozzle": "Düse",
        "bed": "Bett",
        "pressure_advance": "PA (K)",
        "flow_ratio": "Fluss­rate",
        "drying": "Trock­nung",
        "empty_spool": "Leer­spule",
        "net": "Netto",
        "location": "Ort",
        "lot": "Charge {v}",
        "opened": "geöffnet {v}",
    },
}
"""Field labels and footer templates per language (R-346-6)."""

COLUMN_1_KEYS: Final = ("nozzle", "bed", "pressure_advance", "flow_ratio")
"""Column 1: print settings."""
COLUMN_2_KEYS: Final = ("drying", "empty_spool", "net", "location")
"""Column 2: the spool."""

SWATCH_REFERENCE_VALUES: Final[dict[str, tuple[str, ...]]] = {
    "nozzle": ("210\u2013230 °C",),
    "bed": ("60 °C",),
    "pressure_advance": ("0.025", "0,025"),
    "flow_ratio": ("0.96", "0,96"),
    "drying": ("60 °C · 6\u20138 h",),
    "empty_spool": ("140 g",),
    "net": ("1000 g",),
    "location": ("AMS slot 9",),
}
"""The widest value each row is designed for (en and de); the column widths come from these."""

_JOIN: Final = " · "

# Unicode default-ignorable code points (DerivedCoreProperties) the font would draw as boxes or
# BASIC would place wrongly. The soft hyphen is kept by ``clean_text`` (a break point) and
# dropped only where a line is drawn or measured.
_IGNORABLE_RANGES: Final = (
    (0x00AD, 0x00AD),
    (0x034F, 0x034F),
    (0x061C, 0x061C),
    (0x115F, 0x1160),
    (0x17B4, 0x17B5),
    (0x180B, 0x180F),
    (0x200B, 0x200F),
    (0x202A, 0x202E),
    (0x2060, 0x206F),
    (0x3164, 0x3164),
    (0xFE00, 0xFE0F),
    (0xFEFF, 0xFEFF),
    (0xFFA0, 0xFFA0),
    (0xFFF0, 0xFFF8),
    (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A),
    (0xE0000, 0xE0FFF),
)


def _ignorable(ch: str) -> bool:
    code = ord(ch)
    return any(lo <= code <= hi for lo, hi in _IGNORABLE_RANGES)


def clean_text(text: str) -> str:
    """NFC, default-ignorable code points dropped, soft hyphens kept (they are break points)."""
    nfc = unicodedata.normalize("NFC", text)
    return "".join(ch for ch in nfc if ch == SOFT_HYPHEN or not _ignorable(ch))


def drawable(text: str) -> str:
    """The text as it is measured and drawn: ``clean_text`` without the soft hyphens."""
    return clean_text(text).replace(SOFT_HYPHEN, "")


class SwatchText(NamedTuple):
    """Everything the label prints, as text; rows are (label, value)."""

    vendor: str
    title: str
    color_name: str
    hexes: tuple[str, ...]
    hex_line: str
    column_1: tuple[tuple[str, str], ...]
    column_2: tuple[tuple[str, str], ...]
    footer: str
    caption: str


def _decimal(value: float, places: int, language: str) -> str:
    """At most ``places`` decimals, trailing zeros removed, the language's decimal mark."""
    text = f"{value:.{places}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("-0", ""):
        text = "0"
    return text.replace(".", ",") if language == "de" else text


def _span(low: float, high: float, places: int, language: str, unit: str) -> str:
    lo, hi = _decimal(low, places, language), _decimal(high, places, language)
    return f"{lo} {unit}" if lo == hi else f"{lo}\u2013{hi} {unit}"


def _grams(value: float) -> str:
    return f"{math.floor(value + 0.5)} g"  # half up; round() would print 140 for 140.5


def _drying(swatch: SpoolSwatch, language: str) -> str | None:
    parts: list[str] = []
    if swatch.drying_c is not None:
        parts.append(f"{swatch.drying_c} °C")
    if swatch.drying_h is not None:
        parts.append(_span(swatch.drying_h[0], swatch.drying_h[1], 1, language, "h"))
    return _JOIN.join(parts) if parts else None


def _values(swatch: SpoolSwatch) -> dict[str, str | None]:
    lang = swatch.language
    nozzle = swatch.nozzle_c
    return {
        "nozzle": None if nozzle is None else _span(nozzle[0], nozzle[1], 0, lang, "°C"),
        "bed": None if swatch.bed_c is None else f"{swatch.bed_c} °C",
        "pressure_advance": (
            None if swatch.pressure_advance is None else _decimal(swatch.pressure_advance, 3, lang)
        ),
        "flow_ratio": None if swatch.flow_ratio is None else _decimal(swatch.flow_ratio, 3, lang),
        "drying": _drying(swatch, lang),
        "empty_spool": None if swatch.spool_weight_g is None else _grams(swatch.spool_weight_g),
        "net": None if swatch.net_weight_g is None else _grams(swatch.net_weight_g),
        "location": swatch.location or None,
    }


def _footer(swatch: SpoolSwatch) -> str:
    lang = swatch.language
    texts = SWATCH_TEXTS[lang]
    parts: list[str] = []
    if swatch.diameter_mm is not None:
        parts.append(f"Ø {_decimal(swatch.diameter_mm, 2, lang)} mm")
    if swatch.density_g_cm3 is not None:
        parts.append(f"{_decimal(swatch.density_g_cm3, 2, lang)} g/cm³")
    if swatch.lot:
        parts.append(texts["lot"].format(v=swatch.lot))
    if swatch.opened:
        day = dt.date.fromisoformat(swatch.opened)
        shown = day.strftime("%d.%m.%Y") if lang == "de" else day.isoformat()
        parts.append(texts["opened"].format(v=shown))
    return _JOIN.join(parts)


def swatch_text(swatch: SpoolSwatch) -> SwatchText:
    """The label's texts for ``swatch`` in its stored language."""
    texts = SWATCH_TEXTS[swatch.language]
    values = _values(swatch)

    def column(keys: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
        return tuple((texts[k], v) for k in keys if (v := values[k]) is not None)

    hexes = tuple(f"#{code}" for code in swatch.color_hexes)
    return SwatchText(
        vendor=swatch.vendor or "",
        title=swatch.title or f"#{swatch.spool_id}",
        color_name=swatch.color_name or "",
        hexes=hexes,
        hex_line=_JOIN.join(hexes),
        column_1=column(COLUMN_1_KEYS),
        column_2=column(COLUMN_2_KEYS),
        footer=_footer(swatch),
        caption=f"#{swatch.spool_id}",
    )
