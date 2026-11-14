"""``resolve_grocy_target``: the printer a Grocy label goes to (#281, maintainer ruling 2026-11-14).

The type's printer when set, else the default target, else ``None`` (the first enabled tape
printer).
"""

from __future__ import annotations

from typing import Any

import pytest
from app.api.routes.grocy_label import resolve_grocy_target

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
