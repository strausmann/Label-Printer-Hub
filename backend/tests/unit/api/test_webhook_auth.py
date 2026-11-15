# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for app.api.dependencies.webhook_auth.require_webhook_key.

Three scenarios are tested:

1. ``LABELYARD_WEBHOOK_API_KEY`` is unset (or empty) → 503
2. ``LABELYARD_WEBHOOK_API_KEY`` is set but caller sends a wrong key → 401
3. Caller sends the correct key → dependency passes (route returns 200)

We build a minimal FastAPI app with a single GET ``/guarded`` route that
depends on ``require_webhook_key``.  Because ``get_settings`` is
the key now lives in the runtime settings store, each test puts a stub store on
``app.state.settings_store`` rather than mutating the environment.
"""

from __future__ import annotations

import pytest
from app.api.dependencies.webhook_auth import enforce_webhook_rate_limit, require_webhook_key
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

_VALID_KEY = "a" * 32  # 32-char key — passes the Settings validator


class _StubStore:
    """Minimal SettingsStore stand-in: only ``get`` is used by the dependency."""

    def __init__(self, key: str) -> None:
        self._key = key

    def get(self, key: str) -> str:
        assert key == "access.webhook_api_key"
        return self._key


def _make_app(key: str) -> FastAPI:
    """Return a tiny FastAPI app whose single route is guarded by require_webhook_key."""
    app = FastAPI()
    app.state.settings_store = _StubStore(key)

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
    assert "LABELYARD_WEBHOOK_API_KEY" in r.json()["detail"]


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


# ---------------------------------------------------------------------------
# Test: non-ASCII key → 401, never 500 (#301)
# ---------------------------------------------------------------------------

# Sent as raw UTF-8 bytes, the way a real client would; the server decodes the header
# to a ``str`` that holds non-ASCII characters (``hmac.compare_digest`` rejects those).
_NON_ASCII_KEYS = [
    pytest.param("ключ-é-" + "a" * 32, id="cyrillic-latin1-mix"),
    pytest.param("é" * 32, id="latin1-only"),
    pytest.param("🔑" * 8, id="emoji"),
]


def _make_chained_app(key: str) -> FastAPI:
    """App guarded by both webhook dependencies, in the order the real routes use."""
    app = FastAPI()
    app.state.settings_store = _StubStore(key)

    @app.get(
        "/chained",
        dependencies=[Depends(require_webhook_key), Depends(enforce_webhook_rate_limit)],
    )
    async def chained() -> dict[str, str]:
        return {"ok": "true"}

    return app


@pytest.mark.parametrize("bad_key", _NON_ASCII_KEYS)
def test_non_ascii_key_returns_401_on_require_webhook_key(bad_key: str) -> None:
    """A key with non-ASCII characters is just a wrong key: 401 with the normal message."""
    client = TestClient(_make_app(_VALID_KEY), raise_server_exceptions=False)
    r = client.get("/guarded", headers={"X-API-Key": bad_key.encode()})
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid API key"


@pytest.mark.parametrize("bad_key", _NON_ASCII_KEYS)
def test_non_ascii_key_returns_401_through_both_dependencies(bad_key: str) -> None:
    """The real route chain (key check, then rate limit) also answers 401, not 500."""
    client = TestClient(_make_chained_app(_VALID_KEY), raise_server_exceptions=False)
    r = client.get("/chained", headers={"X-API-Key": bad_key.encode()})
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid API key"


@pytest.mark.parametrize("bad_key", _NON_ASCII_KEYS)
def test_non_ascii_key_does_not_crash_enforce_webhook_rate_limit(bad_key: str) -> None:
    """The rate-limit dependency alone must not raise on a non-ASCII key (it hashes the key)."""
    app = FastAPI()

    @app.get("/limited", dependencies=[Depends(enforce_webhook_rate_limit)])
    async def limited() -> dict[str, str]:
        return {"ok": "true"}

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/limited", headers={"X-API-Key": bad_key.encode()})
    assert r.status_code == 200


def test_valid_key_still_passes_both_dependencies() -> None:
    """The correct key still gets through the whole chain after the encoding change."""
    client = TestClient(_make_chained_app(_VALID_KEY), raise_server_exceptions=False)
    r = client.get("/chained", headers={"X-API-Key": _VALID_KEY})
    assert r.status_code == 200


def test_wrong_ascii_key_still_returns_401_through_both_dependencies() -> None:
    """A wrong ASCII key of the right length keeps answering 401 through the chain."""
    client = TestClient(_make_chained_app(_VALID_KEY), raise_server_exceptions=False)
    r = client.get("/chained", headers={"X-API-Key": "b" * 32})
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid API key"
