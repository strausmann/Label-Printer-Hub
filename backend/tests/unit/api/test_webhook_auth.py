"""Unit tests for app.api.dependencies.webhook_auth.require_webhook_key.

Three scenarios are tested:

1. ``PRINTER_HUB_WEBHOOK_API_KEY`` is unset (or empty) → 503
2. ``PRINTER_HUB_WEBHOOK_API_KEY`` is set but caller sends a wrong key → 401
3. Caller sends the correct key → dependency passes (route returns 200)

We build a minimal FastAPI app with a single GET ``/guarded`` route that
depends on ``require_webhook_key``.  Because ``get_settings`` is
``@lru_cache``-decorated, every test overrides the dependency via FastAPI's
:meth:`~fastapi.FastAPI.dependency_overrides` rather than mutating the
environment, so the cache is never a problem.
"""

from __future__ import annotations

from app.api.dependencies.webhook_auth import require_webhook_key
from app.config import Settings, get_settings
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

_VALID_KEY = "a" * 32  # 32-char key — passes the Settings validator


def _make_settings(key: str) -> Settings:
    """Return a Settings instance with the given webhook_api_key.

    Passes ``_env_file=None`` so no local ``.env`` file is read.
    """
    return Settings(_env_file=None, webhook_api_key=SecretStr(key))  # type: ignore[call-arg]


def _make_app(key: str) -> FastAPI:
    """Return a tiny FastAPI app whose single route is guarded by require_webhook_key."""
    app = FastAPI()
    settings_instance = _make_settings(key)
    app.dependency_overrides[get_settings] = lambda: settings_instance

    @app.get("/guarded", dependencies=[Depends(require_webhook_key)])
    async def guarded() -> dict[str, str]:
        return {"ok": "true"}

    return app


# ---------------------------------------------------------------------------
# Test: missing / unconfigured key → 503
# ---------------------------------------------------------------------------


def test_missing_key_returns_503_when_unconfigured() -> None:
    """When the webhook key env var is empty/unset the dependency returns 503."""
    # Empty string is accepted by Settings (startup still works), but the
    # dependency rejects it at request time with 503.
    app = _make_app("")
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/guarded", headers={"X-API-Key": "anything"})
    assert r.status_code == 503
    assert "PRINTER_HUB_WEBHOOK_API_KEY" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Test: wrong key → 401
# ---------------------------------------------------------------------------


def test_wrong_key_returns_401() -> None:
    """A key that doesn't match the configured value yields 401."""
    app = _make_app(_VALID_KEY)
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/guarded", headers={"X-API-Key": "b" * 32})
    assert r.status_code == 401
    assert "Invalid" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Test: correct key → 200 (dependency does not raise)
# ---------------------------------------------------------------------------


def test_correct_key_passes_through() -> None:
    """When the caller presents the correct key the route executes normally."""
    app = _make_app(_VALID_KEY)
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/guarded", headers={"X-API-Key": _VALID_KEY})
    assert r.status_code == 200
    assert r.json() == {"ok": "true"}
