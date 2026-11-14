# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The graceful-shutdown wait covers every worker's queue timeout, tape and page."""

from __future__ import annotations

from app.main import shutdown_wait_s


def test_tape_only_deployment_is_unchanged() -> None:
    assert shutdown_wait_s([10, 45, 30], []) == 45.0


def test_ipp_only_deployment_uses_the_page_timeout() -> None:
    assert shutdown_wait_s([], [120]) == 120.0  # was the flat default of 30


def test_mixed_deployment_takes_the_larger_page_timeout() -> None:
    assert shutdown_wait_s([30, 20], [90]) == 90.0


def test_mixed_deployment_takes_the_larger_tape_timeout() -> None:
    assert shutdown_wait_s([60], [30]) == 60.0


def test_no_printer_keeps_the_default() -> None:
    assert shutdown_wait_s([], []) == 30.0
