"""Unit tests for app.config — Pydantic Settings."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.config import Settings


def test_settings_load_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PRINTER_HUB_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("PRINTER_HUB_QL820_HOST", "192.0.2.10")
    monkeypatch.setenv("PRINTER_HUB_PT750W_HOST", "192.0.2.11")
    monkeypatch.setenv("PRINTER_HUB_WEBHOOK_API_KEY", "test-key-32-bytes-long-enough-here")
    monkeypatch.setenv("PRINTER_HUB_SNIPEIT_URL", "https://snipe-it.example")
    monkeypatch.setenv("PRINTER_HUB_SNIPEIT_API_KEY", "snipeit-key")
    monkeypatch.setenv("PRINTER_HUB_GROCY_URL", "https://grocy.example")
    monkeypatch.setenv("PRINTER_HUB_GROCY_API_KEY", "grocy-key")
    monkeypatch.setenv("PRINTER_HUB_SPOOLMAN_URL", "https://spoolman.example")

    settings = Settings(_env_file=None)

    assert settings.database_url == f"sqlite:///{tmp_path}/test.db"
    assert settings.ql820_host == "192.0.2.10"
    assert settings.pt750w_host == "192.0.2.11"
    assert settings.webhook_api_key.get_secret_value() == "test-key-32-bytes-long-enough-here"
    assert settings.snipeit_url == "https://snipe-it.example"
    assert settings.snipeit_api_key.get_secret_value() == "snipeit-key"
    assert settings.grocy_url == "https://grocy.example"
    assert settings.grocy_api_key.get_secret_value() == "grocy-key"
    assert settings.spoolman_url == "https://spoolman.example"


def test_settings_rejects_short_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRINTER_HUB_WEBHOOK_API_KEY", "too-short")
    with pytest.raises(ValueError, match="at least 32"):
        Settings(_env_file=None)


def test_sse_settings_defaults() -> None:
    """SSE settings must have documented defaults when env vars are absent."""
    s = Settings(_env_file=None)
    assert s.sse_queue_size == 32
    assert s.sse_idle_timeout_s == 300.0
    assert s.sse_max_subscribers == 100
    assert s.sse_heartbeat_s == 30.0
    assert s.sse_probe_interval_s == 30.0
