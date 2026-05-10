"""Pytest configuration shared across all tests.

Hardware tests are skipped by default — pass `--hardware` to opt in.
"""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--hardware",
        action="store_true",
        default=False,
        help="run hardware-in-the-loop tests against real Brother printers",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--hardware"):
        return
    skip_hardware = pytest.mark.skip(reason="hardware tests need --hardware flag")
    for item in items:
        if "hardware" in item.keywords:
            item.add_marker(skip_hardware)
