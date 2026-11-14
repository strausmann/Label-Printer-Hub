# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Test isolation for printer-model registry tests."""

import pytest
from app.printer_models.registry import ModelRegistry


@pytest.fixture(autouse=True)
def _clear_model_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the class-level _models list before each test."""
    monkeypatch.setattr(ModelRegistry, "_models", [])
