# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The one page-printer discriminator (#208)."""

from __future__ import annotations

import pytest
from app.models.printer import IPP_BACKEND, Printer, is_page_backend, is_page_printer


@pytest.mark.parametrize(
    ("backend", "expected"),
    [("ipp", True), ("ptouch", False), ("brother_ql", False), ("mock", False)],
)
def test_is_page_backend(backend: str, expected: bool) -> None:
    assert is_page_backend(backend) is expected


@pytest.mark.parametrize(
    ("backend", "expected"),
    [("ipp", True), ("ptouch", False), ("brother_ql", False), ("mock", False)],
)
def test_is_page_printer(backend: str, expected: bool) -> None:
    printer = Printer(name="p", slug="p", model="m", backend=backend)
    assert is_page_printer(printer) is expected


def test_ipp_backend_constant() -> None:
    assert IPP_BACKEND == "ipp"
