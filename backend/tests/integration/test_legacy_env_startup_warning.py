# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The lifespan warns once, by name only, about variables that still use the old prefix."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

# Not a secret: a harmless marker proving that values never reach the log.
MARKER_VALUE = "marker-value-must-not-be-logged"


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == "app.main"
        and r.levelno == logging.WARNING
        and "PRINTER_HUB_" in r.getMessage()
    ]


def test_startup_warns_once_with_names_only(
    clean_legacy_env: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app.main import app

    monkeypatch.setenv("PRINTER_HUB_EXAMPLE_FLAG", MARKER_VALUE)
    with caplog.at_level(logging.WARNING, logger="app.main"), TestClient(app):
        pass
    messages = _warnings(caplog)
    assert len(messages) == 1
    assert "PRINTER_HUB_EXAMPLE_FLAG" in messages[0]
    assert MARKER_VALUE not in "\n".join(r.getMessage() for r in caplog.records)


def test_startup_is_silent_without_legacy_variables(
    clean_legacy_env: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app.main import app

    with caplog.at_level(logging.WARNING, logger="app.main"), TestClient(app):
        pass
    assert _warnings(caplog) == []
