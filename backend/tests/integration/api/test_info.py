"""GET /api/info (public) and GET /api/v1/system/logs (admin)."""

from __future__ import annotations

import base64
import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import app.models  # noqa: F401
import bcrypt
import pytest
from app.config import get_settings
from app.models.api_key import ApiKey

FAKE_BOOTSTRAP = "fake-bootstrap-key-for-tests-0123456789ab"
FAKE_TRUST = "fake-trust-token-for-tests-0123456789abcdef"
FAKE_SECRET_KEY = base64.urlsafe_b64encode(b"k" * 32).decode()  # valid 32-byte fake key
FAKE_WEBHOOK = "fake-webhook-key-for-tests-0123456789abcdef"
FAKE_PAPERLESS = "fake-paperless-token-for-tests-xyz"

FEATURE_KEYS = {"jobs", "lookup", "scan", "parts", "sheets", "calibration", "asn", "kept"}


def _factory():
    import app.db.engine as _engine_module

    return _engine_module.async_session


async def _insert_admin_key(*, enabled: bool = True, expires_in: timedelta | None = None) -> None:
    plaintext = f"lh_pat_{uuid4().hex}"
    async with _factory()() as s:
        s.add(
            ApiKey(
                name=f"admin-{uuid4().hex[:6]}",
                key_hash=bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode(),
                key_prefix=plaintext[:16],
                scopes=["admin"],
                enabled=enabled,
                expires_at=(datetime.now(UTC) + expires_in) if expires_in else None,
            )
        )
        await s.commit()


async def test_info_shape(api_client_with_seed) -> None:
    resp = await api_client_with_seed.get("/api/info")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {
        "version",
        "revision",
        "build_date",
        "default_language",
        "display_name",
        "auth",
        "features",
    }
    assert set(body["auth"]) == {"sso_configured", "bootstrap_open"}
    assert set(body["features"]) == FEATURE_KEYS
    assert [k for k, v in body["features"].items() if v] == ["jobs", "lookup", "scan"]
    assert body["default_language"] == "en"
    assert body["display_name"] == "Label Printer Hub"
    assert body["auth"] == {"sso_configured": False, "bootstrap_open": False}


async def test_info_sso_configured_follows_trust_token(
    api_client_with_seed, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRINTER_HUB_SSO_TRUST_TOKEN", FAKE_TRUST)
    get_settings.cache_clear()
    body = (await api_client_with_seed.get("/api/info")).json()
    assert body["auth"]["sso_configured"] is True


async def test_bootstrap_open_reflects_admin_keys(
    api_client_with_seed, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def bootstrap_open() -> bool:
        resp = await api_client_with_seed.get("/api/info")
        return resp.json()["auth"]["bootstrap_open"]

    # No bootstrap key configured -> closed.
    assert await bootstrap_open() is False

    monkeypatch.setenv("PRINTER_HUB_BOOTSTRAP_ADMIN_KEY", FAKE_BOOTSTRAP)
    get_settings.cache_clear()
    assert await bootstrap_open() is True

    # A disabled admin key does not close it.
    await _insert_admin_key(enabled=False)
    assert await bootstrap_open() is True

    # An enabled admin key does.
    await _insert_admin_key()
    assert await bootstrap_open() is False


async def test_info_never_contains_secrets(
    api_client_with_seed, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in {
        "BOOTSTRAP_ADMIN_KEY": FAKE_BOOTSTRAP,
        "SSO_TRUST_TOKEN": FAKE_TRUST,
        "SECRET_KEY": FAKE_SECRET_KEY,
        "WEBHOOK_API_KEY": FAKE_WEBHOOK,
        "PAPERLESS_TOKEN": FAKE_PAPERLESS,
    }.items():
        monkeypatch.setenv(f"PRINTER_HUB_{name}", value)
    get_settings.cache_clear()
    resp = await api_client_with_seed.get("/api/info")
    assert resp.status_code == 200
    for value in (FAKE_BOOTSTRAP, FAKE_TRUST, FAKE_SECRET_KEY, FAKE_WEBHOOK, FAKE_PAPERLESS):
        assert value not in resp.text


async def test_system_logs_admin_only_and_capped(client, api_client_with_seed) -> None:
    from app.observability.log_buffer import LOG_BUFFER_CAPACITY

    # Without credentials the endpoint is closed.
    assert (await api_client_with_seed.get("/api/v1/system/logs")).status_code in (401, 403)

    log = logging.getLogger("app.test.logbuffer")
    log.warning("first %s", "warning")
    log.info("below threshold")
    for i in range(LOG_BUFFER_CAPACITY + 100):
        log.error("filler %d", i)

    resp = await client.get("/api/v1/system/logs?limit=200")
    assert resp.status_code == 200
    # Other loggers (e.g. session setup) may add records of their own; look at ours.
    items = [i for i in resp.json() if i["logger"] == "app.test.logbuffer"]
    assert len(resp.json()) == 200
    assert set(items[0]) == {"ts", "level", "logger", "message"}
    assert items[-1]["message"] == f"filler {LOG_BUFFER_CAPACITY + 99}"
    assert items[-1]["level"] == "ERROR"
    assert items[-1]["logger"] == "app.test.logbuffer"

    everything = (await client.get("/api/v1/system/logs?limit=100000")).json()
    assert len(everything) == LOG_BUFFER_CAPACITY
    assert all(item["message"] != "below threshold" for item in everything)
    assert all(item["message"] != "first warning" for item in everything)  # evicted
