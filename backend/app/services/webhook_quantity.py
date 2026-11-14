# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The event quantity of a Spoolman or Grocy webhook as the label's third line (#284).

The line follows the hub's language (``general.language``), not the caller's. A value that is
absent, not finite or outside the range of the source prints no line: the label stays the
two-line label it was before the quantity was read. An out-of-range value is logged at INFO with
the source only, never with the value.
"""

from __future__ import annotations

import logging
import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

_log = logging.getLogger(__name__)

QUANTITY_TEXTS: Final[dict[str, dict[str, str]]] = {
    "en": {"spoolman": "{n}g remaining", "grocy": "Stock change: {n}"},
    "de": {"spoolman": "{n} g übrig", "grocy": "Bestandsänderung: {n}"},
}
"""The wording per language and source; ``{n}`` is the formatted number."""

DEFAULT_LANGUAGE: Final = "en"
SPOOLMAN_QUANTITY_MAX: Final = 1_000_000
"""Grams; a spool holds between 0 and this many."""
GROCY_QUANTITY_LIMIT: Final = 1_000_000
"""A Grocy stock change is accepted between minus and plus this value."""

_ONE: Final = Decimal(1)
_HUNDREDTH: Final = Decimal("0.01")


def _template(source: str, language: str) -> str:
    texts = QUANTITY_TEXTS.get(language) or QUANTITY_TEXTS[DEFAULT_LANGUAGE]
    return texts[source]


def _in_range(source: str, quantity: float | None, low: float, high: float) -> bool:
    if quantity is None or not math.isfinite(quantity):
        return False
    if low <= quantity <= high:
        return True
    _log.info("Ignoring an out-of-range %s webhook quantity", source)
    return False


def _plain(value: Decimal) -> str:
    """The number without an exponent and without trailing zeros."""
    return format(value.normalize(), "f")


def spoolman_quantity_line(quantity: float | None, language: str) -> str | None:
    """The remaining grams of a spool, rounded half up to whole grams."""
    # The range is judged on the rounded value: -0.4 rounds to 0 and is in range.
    if not _in_range("spoolman", quantity, -0.5, SPOOLMAN_QUANTITY_MAX):
        return None
    assert quantity is not None
    grams = Decimal(str(quantity)).quantize(_ONE, rounding=ROUND_HALF_UP)
    if grams < 0:  # -0.5 rounds half up to -1
        _log.info("Ignoring an out-of-range spoolman webhook quantity")
        return None
    # A rounded zero has no sign: -0.0 and -0.4 print as 0.
    text = "0" if grams == 0 else _plain(grams)
    return _template("spoolman", language).format(n=text)


def grocy_quantity_line(quantity: float | None, language: str) -> str | None:
    """A stock change with its sign, rounded half up to two decimals; zero has no sign."""
    if not _in_range("grocy", quantity, -GROCY_QUANTITY_LIMIT, GROCY_QUANTITY_LIMIT):
        return None
    assert quantity is not None
    change = Decimal(str(quantity)).quantize(_HUNDREDTH, rounding=ROUND_HALF_UP)
    text = _plain(change)
    if change > 0:
        text = f"+{text}"
    elif change == 0:
        text = "0"
    if language == "de":
        text = text.replace(".", ",")
    return _template("grocy", language).format(n=text)
