"""Browser sessions, CSRF, bootstrap key and proxy-header trust (spec 8.1, 8.2; D7, D10).

All keys and tokens below are obviously fake test values.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import app.models  # noqa: F401
import bcrypt
import pytest
from app.config import get_settings
from app.models.api_key import ApiKey
from app.models.printer import Printer
from app.models.ui_session import UiSession
from sqlalchemy import select

FAKE_TRUST_TOKEN = "fake-trust-token-for-tests-0123456789abcdef"
FAKE_BOOTSTRAP_KEY = "fake-bootstrap-key-for-tests-0123456789ab"
LOCAL_ORIGIN = "http://localhost:8000"


def _factory():
    import app.db.engine as _engine_module

    return _engine_module.async_session


@pytest.fixture(autouse=True)
def _fresh_sign_in_limiter():
    from app.services.rate_limiter import _sign_in_rate_limiter

    _sign_in_rate_limiter.clear()
    yield
    _sign_in_rate_limiter.clear()


def _set_env(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    for name, value in values.items():
        monkeypatch.setenv(f"PRINTER_HUB_{name.upper()}", value)
    get_settings.cache_clear()


async def _insert_key(
    scopes: list[str],
    *,
    allowed_printer_ids: list[str] | None = None,
    expires_at: datetime | None = None,
    rate_limit_per_minute: int = 60,
) -> tuple[str, UUID]:
    plaintext = f"lh_pat_{uuid4().hex}"
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    async with _factory()() as s:
        key = ApiKey(
            name=f"test-{scopes[0]}-{uuid4().hex[:6]}",
            key_hash=hashed,
            key_prefix=plaintext[:16],
            scopes=scopes,
            allowed_printer_ids=allowed_printer_ids or [],
            enabled=True,
            expires_at=expires_at,
            rate_limit_per_minute=rate_limit_per_minute,
        )
        s.add(key)
        await s.commit()
        return plaintext, key.id


async def _insert_printer(name: str) -> UUID:
    async with _factory()() as s:
        printer = Printer(
            name=name,
            slug=name,
            model="PT-P750W",
            backend="ptouch",
            connection={"host": "192.0.2.30", "port": 9100},
        )
        s.add(printer)
        await s.commit()
        await s.refresh(printer)
        return printer.id


async def _sign_in(client, key: str):
    return await client.post("/api/v1/auth/session", json={"key": key})


def _set_cookie_headers(resp) -> list[str]:
    return resp.headers.get_list("set-cookie")


def _cookie_header(resp, name: str) -> str:
    for header in _set_cookie_headers(resp):
        if header.startswith(f"{name}="):
            return header
    raise AssertionError(f"cookie {name} not set; got {_set_cookie_headers(resp)}")


def _basic(user: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:fake-password".encode()).decode()


# --------------------------------------------------------------------------
# Sign-in and cookies
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sign_in_with_print_key_sets_cookies(api_client_with_seed):
    key, _ = await _insert_key(["print"])
    resp = await _sign_in(api_client_with_seed, key)
    assert resp.status_code == 204, resp.text
    session_cookie = _cookie_header(resp, "lph_session")
    csrf_cookie = _cookie_header(resp, "lph_csrf")
    assert "HttpOnly" in session_cookie
    assert "samesite=strict" in session_cookie.lower()
    assert "HttpOnly" not in csrf_cookie
    assert "samesite=strict" in csrf_cookie.lower()


@pytest.mark.asyncio
async def test_secure_flag_off_only_on_localhost(api_client_with_seed, monkeypatch):
    _set_env(monkeypatch, public_url="https://hub.example.invalid")
    key, _ = await _insert_key(["admin"])
    resp = await _sign_in(api_client_with_seed, key)
    assert resp.status_code == 204, resp.text
    assert "Secure" in _cookie_header(resp, "__Host-lph_session")


@pytest.mark.asyncio
async def test_http_public_url_cookies_without_secure(api_client_with_seed):
    key, _ = await _insert_key(["print"])
    resp = await _sign_in(api_client_with_seed, key)
    for header in _set_cookie_headers(resp):
        assert "secure" not in header.lower(), header
    assert not any(h.startswith("__Host-") for h in _set_cookie_headers(resp))


@pytest.mark.asyncio
async def test_https_uses_host_prefix(api_client_with_seed, monkeypatch):
    _set_env(monkeypatch, public_url="https://hub.example.invalid")
    key, _ = await _insert_key(["print"])
    resp = await _sign_in(api_client_with_seed, key)
    for name in ("__Host-lph_session", "__Host-lph_csrf"):
        header = _cookie_header(resp, name)
        assert "Secure" in header
        assert "Path=/" in header
        assert "domain=" not in header.lower()
        assert "samesite=strict" in header.lower()
    assert "HttpOnly" in _cookie_header(resp, "__Host-lph_session")
    assert "HttpOnly" not in _cookie_header(resp, "__Host-lph_csrf")


@pytest.mark.asyncio
async def test_read_key_cannot_sign_in(api_client_with_seed):
    key, _ = await _insert_key(["read"])
    resp = await _sign_in(api_client_with_seed, key)
    assert resp.status_code == 403
    assert resp.json()["detail"]["error_code"] == "scope_too_low"
    assert not _set_cookie_headers(resp)


@pytest.mark.asyncio
async def test_invalid_key_sign_in_401(api_client_with_seed):
    resp = await _sign_in(api_client_with_seed, "lh_pat_this_key_does_not_exist_0000")
    assert resp.status_code == 401
    assert not _set_cookie_headers(resp)


@pytest.mark.asyncio
async def test_session_cookie_authenticates_get(api_client_with_seed):
    key, _ = await _insert_key(["print"])
    assert (await _sign_in(api_client_with_seed, key)).status_code == 204
    resp = await api_client_with_seed.get("/api/printers")
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_get_session_reports_signed_in_state(api_client_with_seed):
    resp = await api_client_with_seed.get("/api/v1/auth/session")
    assert resp.status_code == 200
    assert resp.json()["signed_in"] is False
    assert resp.json()["csrf_token"] is None

    key, _ = await _insert_key(["admin"])
    await _sign_in(api_client_with_seed, key)
    body = (await api_client_with_seed.get("/api/v1/auth/session")).json()
    assert body["signed_in"] is True
    assert body["scope"] == "admin"
    assert body["source"] == "api-key"
    assert body["bootstrap"] is False
    assert body["csrf_token"] == api_client_with_seed.cookies.get("lph_csrf")


# --------------------------------------------------------------------------
# CSRF
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_without_csrf_header_403(api_client_with_seed):
    printer_id = await _insert_printer("csrf-printer-a")
    key, _ = await _insert_key(["print"])
    await _sign_in(api_client_with_seed, key)
    resp = await api_client_with_seed.post(f"/api/printers/{printer_id}/pause")
    assert resp.status_code == 403
    assert resp.json()["detail"]["error_code"] == "csrf_failed"


@pytest.mark.asyncio
async def test_post_with_wrong_csrf_header_403(api_client_with_seed):
    printer_id = await _insert_printer("csrf-printer-b")
    key, _ = await _insert_key(["print"])
    await _sign_in(api_client_with_seed, key)
    resp = await api_client_with_seed.post(
        f"/api/printers/{printer_id}/pause", headers={"X-CSRF-Token": "not-the-token"}
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["error_code"] == "csrf_failed"


@pytest.mark.asyncio
async def test_post_with_csrf_header_ok(api_client_with_seed):
    printer_id = await _insert_printer("csrf-printer-c")
    key, _ = await _insert_key(["print"])
    await _sign_in(api_client_with_seed, key)
    csrf = api_client_with_seed.cookies.get("lph_csrf")
    resp = await api_client_with_seed.post(
        f"/api/printers/{printer_id}/pause", headers={"X-CSRF-Token": csrf}
    )
    assert resp.status_code == 204, resp.text


@pytest.mark.asyncio
async def test_api_key_header_post_needs_no_csrf(api_client_with_seed):
    printer_id = await _insert_printer("csrf-printer-d")
    key, _ = await _insert_key(["print"])
    resp = await api_client_with_seed.post(
        f"/api/printers/{printer_id}/pause", headers={"X-Label-Hub-Key": key}
    )
    assert resp.status_code == 204, resp.text


# --------------------------------------------------------------------------
# Session lifetime and revocation
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoking_key_revokes_its_sessions(api_client_with_seed):
    key, key_id = await _insert_key(["print"])
    admin_key, _ = await _insert_key(["admin"])
    await _sign_in(api_client_with_seed, key)
    assert (await api_client_with_seed.get("/api/printers")).status_code == 200

    resp = await api_client_with_seed.delete(
        f"/api/admin/api-keys/{key_id}", headers={"X-Label-Hub-Key": admin_key}
    )
    assert resp.status_code == 204, resp.text

    async with _factory()() as s:
        rows = list(
            (await s.execute(select(UiSession).where(UiSession.api_key_id == key_id))).scalars()
        )
    assert rows and all(r.revoked_at is not None for r in rows)
    assert (await api_client_with_seed.get("/api/printers")).status_code == 401


@pytest.mark.asyncio
async def test_expired_session_401(api_client_with_seed, monkeypatch):
    import app.auth.sessions as sessions_module

    key, _ = await _insert_key(["print"])
    await _sign_in(api_client_with_seed, key)
    later = datetime.now(UTC) + timedelta(hours=12, seconds=1)
    monkeypatch.setattr(sessions_module, "_now", lambda: later)
    assert (await api_client_with_seed.get("/api/printers")).status_code == 401


@pytest.mark.asyncio
async def test_session_still_valid_before_expiry(api_client_with_seed, monkeypatch):
    import app.auth.sessions as sessions_module

    key, _ = await _insert_key(["print"])
    await _sign_in(api_client_with_seed, key)
    later = datetime.now(UTC) + timedelta(hours=11, minutes=59)
    monkeypatch.setattr(sessions_module, "_now", lambda: later)
    assert (await api_client_with_seed.get("/api/printers")).status_code == 200


@pytest.mark.asyncio
async def test_sign_out_revokes_session(api_client_with_seed):
    key, _ = await _insert_key(["print"])
    await _sign_in(api_client_with_seed, key)
    session_cookie = api_client_with_seed.cookies.get("lph_session")
    csrf = api_client_with_seed.cookies.get("lph_csrf")
    resp = await api_client_with_seed.delete("/api/v1/auth/session", headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 204, resp.text
    cleared = _cookie_header(resp, "lph_session")
    assert "max-age=0" in cleared.lower() or "expires=" in cleared.lower()
    # Replaying the old cookie must not work after sign-out.
    api_client_with_seed.cookies.set("lph_session", session_cookie)
    assert (await api_client_with_seed.get("/api/printers")).status_code == 401


@pytest.mark.asyncio
async def test_disabled_key_kills_session(api_client_with_seed):
    key, key_id = await _insert_key(["print"])
    admin_key, _ = await _insert_key(["admin"])
    await _sign_in(api_client_with_seed, key)
    resp = await api_client_with_seed.patch(
        f"/api/admin/api-keys/{key_id}",
        json={"enabled": False},
        headers={"X-Label-Hub-Key": admin_key},
    )
    assert resp.status_code == 200, resp.text
    assert (await api_client_with_seed.get("/api/printers")).status_code == 401


@pytest.mark.asyncio
async def test_expired_key_kills_session(api_client_with_seed):
    key, key_id = await _insert_key(["print"], expires_at=datetime.now(UTC) + timedelta(hours=1))
    await _sign_in(api_client_with_seed, key)
    assert (await api_client_with_seed.get("/api/printers")).status_code == 200
    async with _factory()() as s:
        row = await s.get(ApiKey, key_id)
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        s.add(row)
        await s.commit()
    assert (await api_client_with_seed.get("/api/printers")).status_code == 401


@pytest.mark.asyncio
async def test_session_keeps_printer_restriction(api_client_with_seed):
    printer_a = await _insert_printer("acl-session-a")
    printer_b = await _insert_printer("acl-session-b")
    key, _ = await _insert_key(["print"], allowed_printer_ids=[str(printer_a)])
    await _sign_in(api_client_with_seed, key)
    csrf = {"X-CSRF-Token": api_client_with_seed.cookies.get("lph_csrf")}
    resp_b = await api_client_with_seed.post(f"/api/printers/{printer_b}/pause", headers=csrf)
    assert resp_b.status_code == 403, resp_b.text
    assert resp_b.json()["detail"]["error_code"] == "printer_not_allowed"
    resp_a = await api_client_with_seed.post(f"/api/printers/{printer_a}/pause", headers=csrf)
    assert resp_a.status_code == 204, resp_a.text


# --------------------------------------------------------------------------
# Bootstrap key (D7)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bootstrap_only_until_admin_key_exists(api_client_with_seed, monkeypatch):
    _set_env(monkeypatch, bootstrap_admin_key=FAKE_BOOTSTRAP_KEY)
    client = api_client_with_seed

    resp = await _sign_in(client, FAKE_BOOTSTRAP_KEY)
    assert resp.status_code == 204, resp.text
    body = (await client.get("/api/v1/auth/session")).json()
    assert body["source"] == "bootstrap"
    assert body["bootstrap"] is True
    assert body["scope"] == "admin"

    resp = await client.get("/api/printers")
    assert resp.status_code == 403
    assert resp.json()["detail"]["error_code"] == "bootstrap_only"

    csrf = client.cookies.get("lph_csrf")
    resp = await client.post(
        "/api/admin/api-keys",
        json={"name": "first-admin", "scopes": ["admin"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 201, resp.text

    client.cookies.clear()
    resp = await _sign_in(client, FAKE_BOOTSTRAP_KEY)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_bootstrap_key_rejected_when_not_configured(api_client_with_seed):
    resp = await _sign_in(api_client_with_seed, FAKE_BOOTSTRAP_KEY)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_bootstrap_session_dies_when_admin_key_exists(api_client_with_seed, monkeypatch):
    _set_env(monkeypatch, bootstrap_admin_key=FAKE_BOOTSTRAP_KEY)
    client = api_client_with_seed
    assert (await _sign_in(client, FAKE_BOOTSTRAP_KEY)).status_code == 204
    await _insert_key(["admin"])
    resp = await client.post(
        "/api/admin/api-keys",
        json={"name": "late", "scopes": ["admin"]},
        headers={"X-CSRF-Token": client.cookies.get("lph_csrf")},
    )
    assert resp.status_code == 401, resp.text


# --------------------------------------------------------------------------
# Proxy-header trust (D10)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sso_get_session_creates_cookie(api_client_with_seed, monkeypatch):
    _set_env(monkeypatch, sso_trust_token=FAKE_TRUST_TOKEN)
    client = api_client_with_seed
    resp = await client.get(
        "/api/v1/auth/session",
        headers={"Remote-User": "alice", "X-Pangolin-Token": FAKE_TRUST_TOKEN},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["signed_in"] is True
    assert body["user"] == "alice"
    assert body["source"] == "pangolin-sso"
    assert body["scope"] == "admin"
    assert body["csrf_token"]
    _cookie_header(resp, "lph_session")
    # The cookie alone now authenticates.
    assert (await client.get("/api/printers")).status_code == 200


@pytest.mark.asyncio
async def test_sso_wrong_trust_token_no_session(api_client_with_seed, monkeypatch):
    _set_env(monkeypatch, sso_trust_token=FAKE_TRUST_TOKEN)
    resp = await api_client_with_seed.get(
        "/api/v1/auth/session",
        headers={"Remote-User": "alice", "X-Pangolin-Token": "wrong-token"},
    )
    assert resp.status_code == 200
    assert resp.json()["signed_in"] is False
    assert not _set_cookie_headers(resp)
    resp = await api_client_with_seed.get(
        "/api/printers", headers={"Remote-User": "alice", "X-Pangolin-Token": "wrong-token"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_sso_without_configured_token_no_session(api_client_with_seed):
    resp = await api_client_with_seed.get(
        "/api/v1/auth/session", headers={"Remote-User": "alice", "X-Pangolin-Token": ""}
    )
    assert resp.json()["signed_in"] is False
    assert not _set_cookie_headers(resp)


@pytest.mark.asyncio
async def test_legacy_pangolin_user_header_rejected_by_default(api_client_with_seed):
    resp = await api_client_with_seed.get("/api/printers", headers={"X-Pangolin-User": "mallory"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_legacy_pangolin_user_header_accepted_with_opt_in(api_client_with_seed, monkeypatch):
    _set_env(monkeypatch, trust_legacy_pangolin_user="true")
    resp = await api_client_with_seed.get("/api/printers", headers={"X-Pangolin-User": "alice"})
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_legacy_header_never_mints_session(api_client_with_seed, monkeypatch):
    _set_env(monkeypatch, trust_legacy_pangolin_user="true")
    resp = await api_client_with_seed.get(
        "/api/v1/auth/session", headers={"X-Pangolin-User": "alice"}
    )
    assert resp.json()["signed_in"] is False
    assert not _set_cookie_headers(resp)


@pytest.mark.asyncio
async def test_basic_bypass_rejected_by_default(api_client_with_seed):
    resp = await api_client_with_seed.get(
        "/api/printers", headers={"Authorization": _basic("claude-automation")}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_basic_bypass_accepted_with_opt_in(api_client_with_seed, monkeypatch):
    _set_env(monkeypatch, trust_pangolin_basic_bypass="true")
    resp = await api_client_with_seed.get(
        "/api/admin/api-keys", headers={"Authorization": _basic("claude-automation")}
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_bypass_downgraded_to_read_when_flag_set(api_client_with_seed, monkeypatch):
    _set_env(
        monkeypatch, trust_pangolin_basic_bypass="true", pangolin_bypass_scope_downgrade="true"
    )
    headers = {"Authorization": _basic("claude-automation")}
    assert (await api_client_with_seed.get("/api/printers", headers=headers)).status_code == 200
    resp = await api_client_with_seed.get("/api/admin/api-keys", headers=headers)
    assert resp.status_code == 403
    assert resp.json()["detail"]["error_code"] == "insufficient_scope"


@pytest.mark.asyncio
async def test_sso_header_post_without_origin_403(api_client_with_seed, monkeypatch):
    _set_env(monkeypatch, sso_trust_token=FAKE_TRUST_TOKEN)
    printer_id = await _insert_printer("origin-printer")
    sso = {"Remote-User": "alice", "X-Pangolin-Token": FAKE_TRUST_TOKEN}
    resp = await api_client_with_seed.post(f"/api/printers/{printer_id}/pause", headers=sso)
    assert resp.status_code == 403
    assert resp.json()["detail"]["error_code"] == "origin_mismatch"
    resp = await api_client_with_seed.post(
        f"/api/printers/{printer_id}/pause",
        headers={**sso, "Origin": "https://evil.example.invalid"},
    )
    assert resp.status_code == 403
    resp = await api_client_with_seed.post(
        f"/api/printers/{printer_id}/pause", headers={**sso, "Origin": LOCAL_ORIGIN}
    )
    assert resp.status_code == 204, resp.text


# --------------------------------------------------------------------------
# Rate limit
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sign_in_rate_limited(api_client_with_seed):
    for attempt in range(10):
        resp = await _sign_in(api_client_with_seed, f"lh_pat_wrong_key_attempt_{attempt:04d}")
        assert resp.status_code == 401, (attempt, resp.text)
    resp = await _sign_in(api_client_with_seed, "lh_pat_wrong_key_attempt_last")
    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) >= 1


# --------------------------------------------------------------------------
# Security review follow-ups
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_respects_key_rate_limit(api_client_with_seed):
    # Sign-in consumes one token of the key's bucket, so 3/min leaves two requests.
    key, _ = await _insert_key(["print"], rate_limit_per_minute=3)
    assert (await _sign_in(api_client_with_seed, key)).status_code == 204
    for _ in range(2):
        assert (await api_client_with_seed.get("/api/printers")).status_code == 200
    resp = await api_client_with_seed.get("/api/printers")
    assert resp.status_code == 429, resp.text
    assert resp.json()["detail"]["error_code"] == "rate_limit_exceeded"
    assert int(resp.headers["Retry-After"]) >= 1


async def _mint_sso_session(client) -> None:
    resp = await client.get(
        "/api/v1/auth/session",
        headers={"Remote-User": "alice", "X-Pangolin-Token": FAKE_TRUST_TOKEN},
    )
    assert resp.json()["signed_in"] is True
    assert (await client.get("/api/printers")).status_code == 200


@pytest.mark.asyncio
async def test_sso_session_dies_when_trust_token_rotated(api_client_with_seed, monkeypatch):
    _set_env(monkeypatch, sso_trust_token=FAKE_TRUST_TOKEN)
    await _mint_sso_session(api_client_with_seed)
    _set_env(monkeypatch, sso_trust_token="fake-rotated-trust-token-0123456789")
    assert (await api_client_with_seed.get("/api/printers")).status_code == 401


@pytest.mark.asyncio
async def test_sso_session_dies_when_trust_token_cleared(api_client_with_seed, monkeypatch):
    _set_env(monkeypatch, sso_trust_token=FAKE_TRUST_TOKEN)
    await _mint_sso_session(api_client_with_seed)
    _set_env(monkeypatch, sso_trust_token="")
    assert (await api_client_with_seed.get("/api/printers")).status_code == 401


@pytest.mark.asyncio
async def test_sso_session_stores_fingerprint_not_token(api_client_with_seed, monkeypatch):
    _set_env(monkeypatch, sso_trust_token=FAKE_TRUST_TOKEN)
    await _mint_sso_session(api_client_with_seed)
    async with _factory()() as s:
        row = (
            await s.execute(select(UiSession).where(UiSession.source == "pangolin-sso"))
        ).scalar_one()
    assert row.sso_trust_fingerprint
    assert FAKE_TRUST_TOKEN not in row.sso_trust_fingerprint


@pytest.mark.asyncio
async def test_basic_bypass_post_needs_origin(api_client_with_seed, monkeypatch):
    _set_env(monkeypatch, trust_pangolin_basic_bypass="true")
    printer_id = await _insert_printer("bypass-origin-printer")
    basic = {"Authorization": _basic("claude-automation")}
    resp = await api_client_with_seed.post(f"/api/printers/{printer_id}/pause", headers=basic)
    assert resp.status_code == 403
    assert resp.json()["detail"]["error_code"] == "origin_mismatch"
    resp = await api_client_with_seed.post(
        f"/api/printers/{printer_id}/pause",
        headers={**basic, "Origin": "https://evil.example.invalid"},
    )
    assert resp.status_code == 403
    resp = await api_client_with_seed.post(
        f"/api/printers/{printer_id}/pause", headers={**basic, "Origin": LOCAL_ORIGIN}
    )
    assert resp.status_code == 204, resp.text
