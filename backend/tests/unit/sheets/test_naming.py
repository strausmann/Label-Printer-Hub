# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from dataclasses import replace

import pytest
from app.sheets.geometry import Geometry
from app.sheets.naming import KEY_PATTERN, default_allow_qr, derive_key, derive_prefix

L4736 = Geometry("A4", 21000, 29700, 4570, 2120, 4, 12, 4820, 2120, 2130, 985, None, "rectangle")
L4731 = Geometry("A4", 21000, 29700, 2540, 1000, 7, 27, 2790, 1000, 1350, 860, 150, "rectangle")


@pytest.mark.parametrize(
    ("vendor", "code", "expected"),
    [
        ("Avery Zweckform", "L4731REV-25", "L4731"),
        ("Avery Zweckform", "L4736REV-25", "L4736"),
        ("Herma", "4097", "H4097"),
        ("Avery", "5160", "A5160"),
        ("Endisch", "6500040x", "E6500040X"),
        ("Herma", "10001", "H10001"),
    ],
)
def test_derive_prefix(vendor: str, code: str, expected: str) -> None:
    assert derive_prefix(vendor, code) == expected


def test_derive_prefix_too_long() -> None:
    with pytest.raises(ValueError, match="prefix"):
        derive_prefix("Herma", "ABCDEFGHIJKL")


def test_derive_key() -> None:
    assert derive_key("Avery Zweckform", "L4731REV-25") == "avery-zweckform-l4731rev"
    assert derive_key("Herma", "4097") == "herma-4097"
    assert KEY_PATTERN.match(derive_key("Herma", "4097"))


def test_default_allow_qr() -> None:
    assert default_allow_qr(L4736) is True
    assert default_allow_qr(L4731) is False
    assert default_allow_qr(replace(L4736, label_w=1500, label_h=3000)) is True
