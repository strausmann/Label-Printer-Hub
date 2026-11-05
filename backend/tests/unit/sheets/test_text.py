"""Plain-text sanitising for purposes and notes (Plan 1, Task 6)."""

from __future__ import annotations

import pytest
from app.sheets.text import sanitise_text


@pytest.mark.parametrize(
    "char",
    ["\x00", "\x07", "\n", "\t", "\x7f", "\x85", "؜", "‎", "‏"]
    + [chr(c) for c in range(0x202A, 0x202F)]
    + [chr(c) for c in range(0x2066, 0x206A)],
)
def test_removes_control_and_bidi_characters(char: str) -> None:
    assert sanitise_text(f"flour{char}1 kg", max_len=120) == "flour1 kg"


def test_keeps_other_format_characters() -> None:
    family = "\U0001f468‍\U0001f469‍\U0001f467"  # ZWJ emoji sequence
    assert sanitise_text(family, max_len=120) == family
    assert sanitise_text("a­b", max_len=120) == "a­b"  # soft hyphen (Cf) stays


def test_trims_after_removing() -> None:
    assert sanitise_text("  \x07 flour  ‮", max_len=120) == "flour"


def test_length_limit_applies_to_the_cleaned_text() -> None:
    assert sanitise_text("x" * 120, max_len=120) == "x" * 120
    assert sanitise_text("x" * 120 + "\x07\x07", max_len=120) == "x" * 120
    with pytest.raises(ValueError, match="120"):
        sanitise_text("x" * 121, max_len=120)


def test_empty_stays_empty() -> None:
    assert sanitise_text(" \x07 ", max_len=5) == ""
