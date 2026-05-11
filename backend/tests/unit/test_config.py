"""Unit tests for app.config — Pydantic Settings."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.config import Settings


def test_settings_load_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PRINTER_HUB_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("PRINTER_HUB_QL820_HOST", "192.168.1.10")
    monkeypatch.setenv("PRINTER_HUB_PT750W_HOST", "192.168.1.11")
    monkeypatch.setenv("PRINTER_HUB_WEBHOOK_API_KEY", "test-key-32-bytes-long-enough-here")
    monkeypatch.setenv("PRINTER_HUB_SNIPEIT_URL", "https://snipe-it.example")
    monkeypatch.setenv("PRINTER_HUB_SNIPEIT_API_KEY", "snipeit-key")
    monkeypatch.setenv("PRINTER_HUB_GROCY_URL", "https://grocy.example")
    monkeypatch.setenv("PRINTER_HUB_GROCY_API_KEY", "grocy-key")
    monkeypatch.setenv("PRINTER_HUB_SPOOLMAN_URL", "https://spoolman.example")

    settings = Settings()

    assert settings.ql820_host == "192.168.1.10"
    assert settings.pt750w_host == "192.168.1.11"
    assert settings.webhook_api_key.get_secret_value() == "test-key-32-bytes-long-enough-here"


def test_settings_rejects_short_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRINTER_HUB_WEBHOOK_API_KEY", "too-short")
    with pytest.raises(ValueError, match="at least 32"):
        Settings()
