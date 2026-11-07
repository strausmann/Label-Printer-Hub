"""Plain-text sanitising for purposes and notes (Plan 1, Task 6)."""

from __future__ import annotations

import pytest
from app.sheets.text import sanitise_text


@pytest.mark.parametrize(
    "char",
    ["\x00", "\x07", "\x7f", "\x85", "؜", "‎", "‏"]
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


@pytest.mark.parametrize("multiline", [False, True])
def test_other_control_characters_go_in_both_kinds(multiline: bool) -> None:
    assert sanitise_text("a\x07b\x1bc\u202ed", max_len=20, multiline=multiline) == "abcd"
    family = "\U0001f468\u200d\U0001f469"
    assert sanitise_text(family, max_len=20, multiline=multiline) == family


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("box\nlabels", "box labels"),
        ("a\r\nb", "a b"),
        ("a\rb", "a b"),
        ("a\tb\nc", "a b c"),
        ("a \n\n \t b", "a b"),  # a run that held a break or tab becomes one space
        ("a  b", "a  b"),  # plain spaces the author typed stay
        ("\nlead and trail\n", "lead and trail"),
    ],
)
def test_single_line_text_turns_breaks_and_tabs_into_one_space(raw: str, want: str) -> None:
    assert sanitise_text(raw, max_len=40) == want


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("line1\nline2", "line1\nline2"),
        ("line1\r\nline2", "line1\nline2"),
        ("line1\rline2", "line1\nline2"),
        ("a\tb", "a b"),
        ("\n\nbody\n", "body"),
    ],
)
def test_multiline_text_keeps_line_breaks_as_newline(raw: str, want: str) -> None:
    assert sanitise_text(raw, max_len=40, multiline=True) == want


def test_length_counts_the_normalised_text() -> None:
    assert sanitise_text("ab\r\ncd", max_len=5, multiline=True) == "ab\ncd"
    with pytest.raises(ValueError, match="4"):
        sanitise_text("ab\r\ncd", max_len=4, multiline=True)


def _seconds(fn) -> float:
    import time

    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


def test_long_whitespace_runs_are_linear_and_over_long_input_is_refused_early() -> None:
    # A run that fits the bound still has to be cheap: compare with a run ten times shorter.
    run = " \t" * 1000
    short = _seconds(lambda: sanitise_text("a" + run + "b", max_len=5000))
    long = _seconds(lambda: sanitise_text("a" + run * 10 + "b", max_len=50000))
    assert long < max(short, 0.0005) * 60  # linear would be ~10x; quadratic ~100x
    # Input far over the limit is refused before any normalising.
    huge = " \t" * 100_000

    def refuse() -> None:
        with pytest.raises(ValueError):
            sanitise_text(huge, max_len=120)

    started = _seconds(refuse)
    assert started < max(short, 0.0005) * 60
    with pytest.raises(ValueError, match="120"):
        sanitise_text(huge, max_len=120)
    with pytest.raises(ValueError, match="120"):
        sanitise_text("x" * 481, max_len=120, multiline=True)
    assert sanitise_text("  " + "x" * 118 + "\n\n\n", max_len=120) == "x" * 118


def test_log_value_removes_line_breaks() -> None:
    from app.sheets.text import log_value

    assert log_value("a\r\nb\nc\rd") == "abcd"
    assert log_value(42) == "42"


def test_log_value_removes_other_control_characters() -> None:
    from app.sheets.text import log_value

    assert log_value("a\x00b\x1bc\x7fd\x85e\u2028f\u2029g\th") == "abcdefgh"
    assert log_value("plain-slug_1") == "plain-slug_1"
    assert "\n" not in log_value("x\ny WARNING forged")
