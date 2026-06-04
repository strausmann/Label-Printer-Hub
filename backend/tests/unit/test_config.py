"""Unit tests for app.config — Pydantic Settings."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.config import Settings


def test_settings_load_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Phase 1i CA-1: Drucker-spezifische Felder entfernt; printers_config hinzugefügt."""
    monkeypatch.setenv("PRINTER_HUB_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("PRINTER_HUB_PRINTERS_CONFIG", "/tmp/test-printers.yaml")
    monkeypatch.setenv("PRINTER_HUB_WEBHOOK_API_KEY", "test-key-32-bytes-long-enough-here")
    monkeypatch.setenv("PRINTER_HUB_SNIPEIT_URL", "https://snipe-it.example")
    monkeypatch.setenv("PRINTER_HUB_SNIPEIT_API_KEY", "snipeit-key")
    monkeypatch.setenv("PRINTER_HUB_GROCY_URL", "https://grocy.example")
    monkeypatch.setenv("PRINTER_HUB_GROCY_API_KEY", "grocy-key")
    monkeypatch.setenv("PRINTER_HUB_SPOOLMAN_URL", "https://spoolman.example")

    settings = Settings(_env_file=None)

    assert settings.database_url == f"sqlite:///{tmp_path}/test.db"
    assert settings.printers_config == "/tmp/test-printers.yaml"
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


# ---------------------------------------------------------------------------
# F3 — SSE Settings must reject zero/negative values (Finding F3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("sse_queue_size", 0),
        ("sse_queue_size", -1),
        ("sse_heartbeat_s", 0),
        ("sse_heartbeat_s", -0.5),
        ("sse_idle_timeout_s", 0),
        ("sse_idle_timeout_s", -10),
        ("sse_max_subscribers", 0),
        ("sse_max_subscribers", -1),
        ("sse_probe_interval_s", 0),
        ("sse_probe_interval_s", -5.0),
    ],
)
def test_sse_settings_reject_non_positive(field: str, value: float | int) -> None:
    """All five SSE settings must reject 0 and negative values (Finding F3).

    asyncio.Queue(maxsize=0) is unbounded; heartbeat_s=0 creates a tight
    loop; all other zero/negative values are nonsensical resource limits.
    Field(gt=0) on each setting provides the guard.
    """
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(**{field: value}, _env_file=None)  # type: ignore[arg-type]


def test_sse_settings_accept_positive_one() -> None:
    """Boundary: value=1 must be accepted for all five SSE settings."""
    s = Settings(
        sse_queue_size=1,
        sse_heartbeat_s=1.0,
        sse_idle_timeout_s=1.0,
        sse_max_subscribers=1,
        sse_probe_interval_s=1.0,
        _env_file=None,  # type: ignore[call-arg]
    )
    assert s.sse_queue_size == 1
    assert s.sse_heartbeat_s == 1.0
    assert s.sse_idle_timeout_s == 1.0
    assert s.sse_max_subscribers == 1
    assert s.sse_probe_interval_s == 1.0


# ---------------------------------------------------------------------------
# F5 — .env.example must document all SSE env vars (Finding F5)
# ---------------------------------------------------------------------------

_SSE_ENV_VARS = [
    "PRINTER_HUB_SSE_QUEUE_SIZE",
    "PRINTER_HUB_SSE_HEARTBEAT_S",
    "PRINTER_HUB_SSE_IDLE_TIMEOUT_S",
    "PRINTER_HUB_SSE_MAX_SUBSCRIBERS",
    "PRINTER_HUB_SSE_PROBE_INTERVAL_S",
]


def test_env_example_contains_all_sse_vars() -> None:
    """backend/.env.example must document every PRINTER_HUB_SSE_* variable.

    Finding F5: the five SSE settings added in Phase 6b were missing from
    .env.example which claimed to list all supported variables.  Operators
    who use .env.example as a reference would be unaware of these knobs.
    """
    env_example = Path(__file__).parent.parent.parent / ".env.example"
    assert env_example.exists(), ".env.example not found at expected path"
    content = env_example.read_text()
    missing = [var for var in _SSE_ENV_VARS if var not in content]
    assert not missing, (
        f"Missing SSE env vars in .env.example: {missing!r}. "
        "Add them so operators know these settings exist."
    )


# ---------------------------------------------------------------------------
# Phase 1i CA-1 — extra="forbid" + printers_config Feld
# ---------------------------------------------------------------------------


def test_settings_extra_forbid_rejects_old_kwargs() -> None:
    """CA-1: alte Settings-Kwargs schlagen mit extra=forbid fehl.

    Hinweis: pydantic-settings ignoriert unbekannte Env-Vars silently.
    extra=forbid greift nur bei direkten Konstruktor-Kwargs.
    """
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="extra_forbidden"):
        Settings(printer_model="PT-P750W", _env_file=None)  # type: ignore[call-arg]


def test_settings_extra_forbid_rejects_pt750w_host_kwarg() -> None:
    """CA-1: pt750w_host als Kwarg → ValidationError (Feld ist entfernt)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="extra_forbidden"):
        Settings(pt750w_host="1.2.3.4", _env_file=None)  # type: ignore[call-arg]


def test_settings_printers_config_default() -> None:
    """CA-1: printers_config hat den korrekten Default."""
    s = Settings(_env_file=None)
    assert s.printers_config == "/etc/hub/printers.yaml"


def test_settings_printers_config_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """CA-1: PRINTER_HUB_PRINTERS_CONFIG überschreibt den Default."""
    monkeypatch.setenv("PRINTER_HUB_PRINTERS_CONFIG", "/custom/path/printers.yaml")
    s = Settings(_env_file=None)
    assert s.printers_config == "/custom/path/printers.yaml"
