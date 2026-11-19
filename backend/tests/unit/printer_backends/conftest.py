# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Fixtures for the backend tests.

#389: ``BrotherQLBackend`` checks the loaded roll over SNMP before it sends. The tests of the
conversion (orientation, fit, mapping) are not about that check, so it is switched off for them;
a test that asks for the ``real_ql_media_check`` fixture keeps it.
"""

from __future__ import annotations

import pytest
from app.printer_backends.brother_ql_backend import BrotherQLBackend


@pytest.fixture
def real_ql_media_check() -> None:
    """Request this fixture to run ``BrotherQLBackend``'s media check for real."""


@pytest.fixture(autouse=True)
def _skip_ql_media_check(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if "real_ql_media_check" in request.fixturenames:
        return

    async def no_check(self: BrotherQLBackend, tape_spec: object) -> None:
        return None

    monkeypatch.setattr(BrotherQLBackend, "_check_loaded_media", no_check)
