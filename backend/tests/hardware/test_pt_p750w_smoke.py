"""Hardware-in-the-loop smoke test. Skipped by default — opt in with --hardware."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.hardware


@pytest.mark.skipif(
    not os.environ.get("PRINTER_HUB_PT750W_HOST"),
    reason="PRINTER_HUB_PT750W_HOST not set",
)
async def test_smoke_first_print_succeeds() -> None:
    """End-to-end hardware test: real printer prints a QR-only label."""
    from scripts.smoke_first_print import main

    rc = await main()
    assert rc == 0
