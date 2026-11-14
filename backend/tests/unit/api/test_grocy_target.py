# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""``resolve_grocy_target``: the printer a Grocy label goes to (#281, maintainer ruling 2026-11-14).

The type's printer when set, else the default target, else ``None`` (the first enabled tape
printer).
"""

from __future__ import annotations

from typing import Any

import pytest
from app.api.routes.grocy_label import resolve_grocy_sheet_type, resolve_grocy_target

DEFAULT = "integrations.grocy.label.printer"
PRODUCT = "integrations.grocy.label.product.printer"


class _Settings:
    def __init__(self, values: dict[str, Any]) -> None:
        self._values = values

    def get(self, key: str) -> Any:
        return self._values.get(key, "")


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({}, None),  # both empty: the first enabled tape printer
        ({DEFAULT: "tape-2"}, "tape-2"),  # the default when the type has none
        ({DEFAULT: "tape-2", PRODUCT: "tape-1"}, "tape-1"),  # the type's printer wins
        ({PRODUCT: "tape-1"}, "tape-1"),
        ({DEFAULT: "  ", PRODUCT: " "}, None),  # blanks count as unset
    ],
)
def test_resolution_order(values: dict[str, Any], expected: str | None) -> None:
    assert resolve_grocy_target(_Settings(values), "product") == expected


def test_another_types_printer_is_not_used() -> None:
    settings = _Settings({PRODUCT: "tape-1", DEFAULT: "tape-2"})
    assert resolve_grocy_target(settings, "chore") == "tape-2"


# --- the sheet type of a page target (R-281-13) ---------------------------------------------

DEFAULT_SHEET = "integrations.grocy.label.sheet_type"
BATTERY = "integrations.grocy.label.battery.printer"
BATTERY_SHEET = "integrations.grocy.label.battery.sheet_type"


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        # The battery uses the default target: printer and sheet type of the default.
        ({DEFAULT: "laser", DEFAULT_SHEET: "avery-zweckform-l4736rev"}, "avery-zweckform-l4736rev"),
        # Its own printer: its own sheet type, never the default's.
        (
            {DEFAULT: "laser", DEFAULT_SHEET: "avery-zweckform-l4736rev", BATTERY: "laser2"}
            | {BATTERY_SHEET: "t2"},
            "t2",
        ),
        ({DEFAULT: "laser", DEFAULT_SHEET: "avery-zweckform-l4736rev", BATTERY: "laser2"}, None),
        ({DEFAULT_SHEET: " ", DEFAULT: "laser"}, None),  # blank counts as unset
    ],
)
def test_sheet_type_follows_the_target_unit(values: dict[str, Any], expected: str | None) -> None:
    assert resolve_grocy_sheet_type(_Settings(values), "battery") == expected
