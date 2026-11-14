"""The webhook quantity line: wording, rounding, range and language (#284)."""

from __future__ import annotations

import logging
from collections.abc import Callable

import pytest
from app.services.webhook_quantity import grocy_quantity_line, spoolman_quantity_line

Fn = Callable[[float | None, str], str | None]


@pytest.mark.parametrize(
    ("fn", "quantity", "language", "expected"),
    [
        (spoolman_quantity_line, 850.5, "en", "851g remaining"),
        (spoolman_quantity_line, 850.49, "en", "850g remaining"),
        (spoolman_quantity_line, 850.5, "de", "851 g übrig"),
        (spoolman_quantity_line, 0, "en", "0g remaining"),
        (spoolman_quantity_line, 1_000_000, "en", "1000000g remaining"),
        (spoolman_quantity_line, -0.0, "en", "0g remaining"),
        (spoolman_quantity_line, -0.4, "en", "0g remaining"),
        (spoolman_quantity_line, -0.5, "en", None),
        (spoolman_quantity_line, -1, "en", None),
        (spoolman_quantity_line, 1_000_001, "en", None),
        (spoolman_quantity_line, None, "en", None),
        (spoolman_quantity_line, float("nan"), "en", None),
        (grocy_quantity_line, 2, "en", "Stock change: +2"),
        (grocy_quantity_line, -1.5, "en", "Stock change: -1.5"),
        (grocy_quantity_line, -1.5, "de", "Bestandsänderung: -1,5"),
        (grocy_quantity_line, 0.125, "en", "Stock change: +0.13"),
        (grocy_quantity_line, 2.10, "de", "Bestandsänderung: +2,1"),
        (grocy_quantity_line, 0, "en", "Stock change: 0"),
        (grocy_quantity_line, -0.001, "en", "Stock change: 0"),
        (grocy_quantity_line, 100, "en", "Stock change: +100"),
        (grocy_quantity_line, -1_000_001, "en", None),
        (grocy_quantity_line, 1_000_001, "en", None),
        (grocy_quantity_line, None, "en", None),
        (grocy_quantity_line, 2, "fr", "Stock change: +2"),
        (spoolman_quantity_line, 5, "fr", "5g remaining"),
    ],
)
def test_quantity_line(fn: Fn, quantity: float | None, language: str, expected: str | None) -> None:
    assert fn(quantity, language) == expected


def test_out_of_range_is_logged_with_the_source_and_not_the_value(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="app.services.webhook_quantity"):
        assert spoolman_quantity_line(1_000_001, "en") is None
    assert "spoolman" in caplog.text
    assert "1000001" not in caplog.text
    assert "1000001" not in str(caplog.records[0].args)
