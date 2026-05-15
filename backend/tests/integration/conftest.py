"""Pytest configuration for integration tests.

Integration tests run against the full FastAPI application (including the
lifespan) but without real hardware. We configure the app to use the in-memory
mock backend so that lifespan startup succeeds without a printer on the network.
"""

from __future__ import annotations

import pytest
from app.config import get_settings
from app.printer_backends import BackendRegistry
from app.printer_models.registry import ModelRegistry


@pytest.fixture(autouse=True)
def _mock_backend_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure integration tests use the mock backend and a known model.

    The FastAPI lifespan wires up printer infrastructure — without real hardware
    or this fixture, lifespan startup would fail and TestClient would raise before
    any test body executes.
    """
    monkeypatch.setenv("PRINTER_HUB_PRINTER_BACKEND", "mock")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_MODEL", "PT-P750W")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_DISCOVER_VIA_SNMP", "false")
    get_settings.cache_clear()
    # Reset registry state so each test gets a clean discovery cycle.
    BackendRegistry._factories.clear()
    BackendRegistry._discovered = False
    ModelRegistry._models.clear()
    ModelRegistry._discovered = False
    yield
    get_settings.cache_clear()
    BackendRegistry._factories.clear()
    BackendRegistry._discovered = False
    ModelRegistry._models.clear()
    ModelRegistry._discovered = False
