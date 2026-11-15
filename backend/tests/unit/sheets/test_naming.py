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
    # 25.4 x 10 mm: a QR code with a short number beside it prints and scans (issue #330).
    assert default_allow_qr(L4731) is True
    assert default_allow_qr(replace(L4736, label_w=1500, label_h=3000)) is True


@pytest.mark.parametrize(
    ("label_w", "label_h", "expected"),
    [
        (2540, 990, False),  # 9.9 mm: below the threshold
        (2540, 1000, True),  # 10 mm: the threshold itself
        (990, 2540, False),  # the shorter side counts, whichever it is
        (1000, 2540, True),
        (2540, 1270, True),  # 12.7 mm (Avery 5167): off under the former 15 mm rule
        (2540, 1499, True),  # just below the former 15 mm threshold
    ],
)
def test_default_allow_qr_threshold_is_10_mm(label_w: int, label_h: int, expected: bool) -> None:
    g = replace(L4731, label_w=label_w, label_h=label_h)
    assert default_allow_qr(g) is expected
