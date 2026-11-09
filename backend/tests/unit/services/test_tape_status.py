"""The one status-cache schema for tape printers and its only reader (#229)."""

from __future__ import annotations

from app.services.tape_status import read_tape_status


def test_reads_the_full_schema() -> None:
    parsed = {
        "online": True,
        "loaded_tape_mm": 62,
        "media_raw": '62mm(2.44")',
        "hr_printer_status": "idle",
        "error_flags": ["doorOpen"],
        "last_error": "boom",
    }
    assert read_tape_status(parsed) == parsed


def test_no_tape_is_none_not_zero() -> None:
    assert read_tape_status({"online": True, "loaded_tape_mm": None})["loaded_tape_mm"] is None
    assert read_tape_status({"online": True, "loaded_tape_mm": 0})["loaded_tape_mm"] is None


def test_the_old_block_key_is_not_read() -> None:
    # ``media_width_mm`` came from the 32-byte status block, which no producer writes any more.
    assert "loaded_tape_mm" not in read_tape_status({"media_width_mm": 12})


def test_malformed_values_are_dropped() -> None:
    out = read_tape_status(
        {
            "online": "yes",
            "loaded_tape_mm": True,
            "media_raw": 5,
            "hr_printer_status": None,
            "error_flags": "doorOpen",
            "last_error": 3,
        }
    )
    assert out == {}


def test_media_raw_is_trimmed_and_empty_is_none() -> None:
    assert read_tape_status({"media_raw": "  12mm  "})["media_raw"] == "12mm"
    assert read_tape_status({"media_raw": "   "})["media_raw"] is None


def test_non_string_error_flags_are_dropped() -> None:
    assert read_tape_status({"error_flags": ["a", 1, None]})["error_flags"] == ["a"]
