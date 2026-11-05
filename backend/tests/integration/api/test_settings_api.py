"""Integration tests for /api/v1/settings (admin scope)."""

from __future__ import annotations

from uuid import uuid4

import app.models  # noqa: F401
import bcrypt
import httpx
import pytest
import respx
from app.config import get_settings
from app.models.api_key import ApiKey
from sqlalchemy import select

FAKE_TOKEN = "fake-token-value-for-tests"
GROCY = "https://grocy.example.invalid"
SECRET_KEY = "integrations.grocy.api_key"
URL_KEY = "integrations.grocy.url"


def _by_key(resp: httpx.Response) -> dict[str, dict]:
    return {item["key"]: item for item in resp.json()}


async def _put(client, values):
    return await client.put("/api/v1/settings", json={"values": values})


async def test_list_has_all_settings(client) -> None:
    resp = await client.get("/api/v1/settings")
    assert resp.status_code == 200
    by_key = _by_key(resp)
    assert "jobs.retention_days" in by_key
    assert by_key["general.public_url"]["locked"] is True
    assert by_key["general.language"]["choices"] == ["en", "de"]


async def test_put_updates_and_returns_list(client) -> None:
    resp = await _put(client, {"general.display_name": "Hub 1", "jobs.retention_days": 7})
    assert resp.status_code == 200
    by_key = _by_key(resp)
    assert by_key["general.display_name"]["value"] == "Hub 1"
    assert by_key["jobs.retention_days"]["value"] == 7


async def test_put_locked_key_returns_409_and_writes_nothing(client, monkeypatch) -> None:
    monkeypatch.setenv("PRINTER_HUB_SNIPEIT_URL", "https://snipeit.example.invalid")
    get_settings.cache_clear()
    resp = await _put(
        client,
        {
            "general.display_name": "should-not-persist",
            "integrations.snipeit.url": "https://x.example.invalid",
        },
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["error_code"] == "setting_locked"
    by_key = _by_key(await client.get("/api/v1/settings"))
    assert by_key["general.display_name"]["value"] == "Label Printer Hub"
    assert by_key["integrations.snipeit.url"]["locked"] is True


async def test_secret_never_returned(client) -> None:
    resp = await _put(client, {URL_KEY: GROCY, SECRET_KEY: FAKE_TOKEN})
    assert resp.status_code == 200
    assert FAKE_TOKEN not in resp.text
    listed = await client.get("/api/v1/settings")
    assert FAKE_TOKEN not in listed.text
    item = _by_key(listed)[SECRET_KEY]
    assert item["value"] is None
    assert item["is_set"] is True
    export = await client.get("/api/v1/settings/export")
    assert FAKE_TOKEN not in export.text


async def test_secret_stored_encrypted(client, db_session) -> None:
    from app.models.app_setting import AppSetting

    await _put(client, {URL_KEY: GROCY, SECRET_KEY: FAKE_TOKEN})
    row = (
        await db_session.execute(select(AppSetting).where(AppSetting.key == SECRET_KEY))
    ).scalar_one()
    assert FAKE_TOKEN not in (row.secret_token or "")
    assert row.secret_token.startswith("v1.")


async def test_undecryptable_secret_reported(client, db_session) -> None:
    from app.models.app_setting import AppSetting
    from app.security.secret_box import SecretBox

    # A row sealed with a different key, as after a key change.
    foreign = SecretBox(b"other-secret-key-0123456789abcde")
    db_session.add(
        AppSetting(
            key=SECRET_KEY,
            secret_token=foreign.seal("x", aad=SECRET_KEY),
            value_json='{"bound_url": ""}',
        )
    )
    await db_session.commit()
    # The store loads at startup; building a fresh app reloads it.
    from app.main import create_app
    from httpx import ASGITransport, AsyncClient

    app = create_app()
    inner = app._app
    from app.auth.dependencies import AuthContext
    from app.auth.scope_deps import require_admin

    inner.dependency_overrides[require_admin] = lambda: AuthContext(
        source="api-key", scope="admin", api_key_id=uuid4(), ip="127.0.0.1"
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        item = _by_key(await c.get("/api/v1/settings"))[SECRET_KEY]
        assert item["state"] == "undecryptable"
        assert (await c.get("/healthz")).status_code == 200


async def test_unknown_key_422(client) -> None:
    resp = await _put(client, {"nope.nothing": 1})
    assert resp.status_code == 422
    assert resp.json()["detail"]["error_code"] == "unknown_setting"


async def test_wrong_type_422(client) -> None:
    resp = await _put(client, {"jobs.retention_days": "x"})
    assert resp.status_code == 422
    assert resp.json()["detail"]["error_code"] == "invalid_value"


async def test_validation_error_never_echoes_secret(client) -> None:
    secret = "do-not-echo-this-secret-value"
    resp = await _put(client, {"integrations.grocy.api_key": [secret]})
    assert resp.status_code == 422
    assert secret not in resp.text
    assert "input" not in resp.text
    # malformed envelope: the secret sits in a wrongly shaped body
    resp = await client.put("/api/v1/settings", json={"values": [secret]})
    assert resp.status_code == 422
    assert secret not in resp.text
    resp = await client.put(
        "/api/v1/settings", content=f"{{{secret}", headers={"content-type": "application/json"}
    )
    assert resp.status_code == 422
    assert secret not in resp.text


async def test_url_with_userinfo_rejected(client) -> None:
    resp = await _put(client, {URL_KEY: "https://u:p@grocy.example.invalid"})
    assert resp.status_code == 422
    assert "u:p" not in resp.text


async def test_changing_url_requires_secret(client) -> None:
    assert (await _put(client, {URL_KEY: GROCY, SECRET_KEY: FAKE_TOKEN})).status_code == 200
    with respx.mock(assert_all_called=False) as router:
        evil = router.get(url__regex=r"https://evil\.example\.invalid/.*").respond(200)
        resp = await _put(client, {URL_KEY: "https://evil.example.invalid"})
        assert resp.status_code == 422
        assert resp.json()["detail"]["error_code"] == "secret_required_for_new_url"
        test = await client.post(
            "/api/v1/settings/integrations/grocy/test",
            json={"values": {URL_KEY: "https://evil.example.invalid"}},
        )
        assert test.status_code == 422
        assert test.json()["detail"]["error_code"] == "secret_required_for_new_url"
        assert evil.call_count == 0
    # same URL without token uses the stored token
    with respx.mock() as router:
        route = router.get(f"{GROCY}/api/system/info").respond(200)
        ok = await client.post(
            "/api/v1/settings/integrations/grocy/test", json={"values": {URL_KEY: GROCY}}
        )
        assert ok.json()["ok"] is True
        assert route.calls.last.request.headers["GROCY-API-KEY"] == FAKE_TOKEN


async def test_integration_test_uses_unsaved_values(client) -> None:
    body = {"values": {URL_KEY: GROCY, SECRET_KEY: FAKE_TOKEN}}
    url = "/api/v1/settings/integrations/grocy/test"
    with respx.mock() as router:
        route = router.get(f"{GROCY}/api/system/info").respond(200, json={})
        resp = await client.post(url, json=body)
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "status": 200, "detail": "ok"}
        assert route.calls.last.request.headers["GROCY-API-KEY"] == FAKE_TOKEN
        assert FAKE_TOKEN not in resp.text

        router.get(f"{GROCY}/api/system/info").respond(401)
        resp = await client.post(url, json=body)
        assert resp.json()["ok"] is False and resp.json()["status"] == 401
        assert FAKE_TOKEN not in resp.text

        router.get(f"{GROCY}/api/system/info").mock(side_effect=httpx.ConnectError("boom"))
        resp = await client.post(url, json=body)
        assert resp.json()["ok"] is False and resp.json()["status"] is None
        assert FAKE_TOKEN not in resp.text


@pytest.mark.parametrize(
    ("name", "url_path", "auth_header"),
    [
        ("snipeit", "/api/v1/hardware?limit=1", ("authorization", f"Bearer {FAKE_TOKEN}")),
        ("grocy", "/api/system/info", ("grocy-api-key", FAKE_TOKEN)),
        ("spoolman", "/api/v1/info", None),
        ("paperless", "/api/documents/?page_size=1", ("authorization", f"Token {FAKE_TOKEN}")),
    ],
)
async def test_integration_probe_shapes(client, name, url_path, auth_header) -> None:
    base = f"https://{name}.example.invalid"
    values = {f"integrations.{name}.url": base}
    sec = {"snipeit": "api_key", "grocy": "api_key", "paperless": "token"}.get(name)
    if sec:
        values[f"integrations.{name}.{sec}"] = FAKE_TOKEN
    with respx.mock() as router:
        route = router.get(base + url_path).respond(200)
        resp = await client.post(
            f"/api/v1/settings/integrations/{name}/test", json={"values": values}
        )
        assert resp.json()["ok"] is True
        headers = route.calls.last.request.headers
        if auth_header:
            assert headers[auth_header[0]] == auth_header[1]
        else:
            assert "authorization" not in headers


async def test_integration_test_without_url_and_unknown_name(client) -> None:
    resp = await client.post("/api/v1/settings/integrations/grocy/test", json={})
    assert resp.status_code == 200
    assert resp.json()["ok"] is False
    resp = await client.post("/api/v1/settings/integrations/nope/test", json={})
    assert resp.status_code == 404


async def test_integration_test_does_not_follow_redirects(client) -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{GROCY}/api/system/info").respond(
            302, headers={"location": "https://evil.example.invalid/x"}
        )
        evil = router.get("https://evil.example.invalid/x").respond(200)
        resp = await client.post(
            "/api/v1/settings/integrations/grocy/test",
            json={"values": {URL_KEY: GROCY, SECRET_KEY: FAKE_TOKEN}},
        )
        assert resp.json()["ok"] is False
        assert evil.call_count == 0


async def test_settings_export_has_no_secrets(client, monkeypatch) -> None:
    monkeypatch.setenv("PRINTER_HUB_SNIPEIT_URL", "https://snipeit.example.invalid")
    get_settings.cache_clear()
    await _put(client, {URL_KEY: GROCY, SECRET_KEY: FAKE_TOKEN, "general.display_name": "Hub 1"})
    resp = await client.get("/api/v1/settings/export")
    assert resp.status_code == 200
    assert "attachment" in resp.headers["content-disposition"]
    data = resp.json()
    assert data["general.display_name"] == "Hub 1"
    assert SECRET_KEY not in data
    assert "access.webhook_api_key" not in data
    assert "integrations.snipeit.url" not in data  # locked
    assert "general.public_url" not in data  # locked
    assert FAKE_TOKEN not in resp.text


async def test_settings_routes_require_admin(api_client_with_seed) -> None:
    import app.db.engine as engine_module

    plaintext = f"lh_pat_set_t_{uuid4().hex[:16]}"
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    async with engine_module.async_session() as s:
        s.add(
            ApiKey(
                name="settings-test-key",
                key_hash=hashed,
                key_prefix=plaintext[:16],
                scopes=["print"],
                allowed_printer_ids=[],
                enabled=True,
                rate_limit_per_minute=60,
            )
        )
        await s.commit()
    headers = {"X-Label-Hub-Key": plaintext}
    for method, path in [
        ("GET", "/api/v1/settings"),
        ("PUT", "/api/v1/settings"),
        ("GET", "/api/v1/settings/export"),
        ("POST", "/api/v1/settings/integrations/grocy/test"),
    ]:
        resp = await api_client_with_seed.request(
            method, path, headers=headers, json={"values": {}}
        )
        assert resp.status_code == 403, (method, path, resp.status_code)


async def test_secret_without_url_422(client) -> None:
    resp = await _put(client, {SECRET_KEY: FAKE_TOKEN})
    assert resp.status_code == 422
    assert resp.json()["detail"]["error_code"] == "url_required_for_secret"
    assert FAKE_TOKEN not in resp.text


async def test_non_ascii_secret_422_and_probe_survives(client, monkeypatch) -> None:
    resp = await _put(client, {URL_KEY: GROCY, SECRET_KEY: "tëst-token"})
    assert resp.status_code == 422
    assert "tëst" not in resp.text
    # env secret with a non-ASCII value must not crash the probe (500)
    monkeypatch.setenv("PRINTER_HUB_GROCY_URL", GROCY)
    monkeypatch.setenv("PRINTER_HUB_GROCY_API_KEY", "tëst-token")
    get_settings.cache_clear()
    with respx.mock(assert_all_called=False):
        test = await client.post("/api/v1/settings/integrations/grocy/test", json={})
    assert test.status_code == 200
    assert test.json()["ok"] is False and test.json()["status"] is None
    assert "tëst" not in test.text


async def test_env_secret_with_ui_url_sends_nothing(client, monkeypatch) -> None:
    """S1: env secret + UI-changed URL -> no request leaves."""
    monkeypatch.setenv("PRINTER_HUB_GROCY_API_KEY", FAKE_TOKEN)
    get_settings.cache_clear()
    assert (await _put(client, {URL_KEY: GROCY})).status_code == 200
    item = _by_key(await client.get("/api/v1/settings"))[SECRET_KEY]
    assert item["state"] == "env_secret_needs_env_url"
    with respx.mock(assert_all_called=False) as router:
        any_call = router.route().respond(200)
        for body in ({}, {"values": {URL_KEY: "https://evil.example.invalid"}}):
            resp = await client.post("/api/v1/settings/integrations/grocy/test", json=body)
            assert resp.status_code == 422
            assert resp.json()["detail"]["error_code"] == "secret_required_for_new_url"
        assert any_call.call_count == 0


async def test_env_url_userinfo_not_shown(client, monkeypatch) -> None:
    monkeypatch.setenv("PRINTER_HUB_SNIPEIT_URL", "https://user:pw-secret@snipeit.example.invalid")
    get_settings.cache_clear()
    resp = await client.get("/api/v1/settings")
    assert "pw-secret" not in resp.text
    assert _by_key(resp)["integrations.snipeit.url"]["value"] == "https://snipeit.example.invalid"


PAPERLESS = "https://paperless.example.invalid"
PAPERLESS_DOCS = "/api/documents/"


def _mock_paperless(router, base: str = PAPERLESS):
    """Like a real Paperless-ngx: /api/ redirects, /api/documents/ needs the token."""
    router.get(base + "/api/").respond(302, headers={"location": base + "/api/schema/view/"})

    def docs(request):
        if request.headers.get("authorization") == f"Token {FAKE_TOKEN}":
            return httpx.Response(200, json={"count": 0, "results": []})
        return httpx.Response(401, json={"detail": "Authentication credentials were not provided."})

    return router.get(base + PAPERLESS_DOCS).mock(side_effect=docs)


async def _test_paperless(client, url: str, token: str = FAKE_TOKEN):
    values = {"integrations.paperless.url": url, "integrations.paperless.token": token}
    return await client.post(
        "/api/v1/settings/integrations/paperless/test", json={"values": values}
    )


async def test_paperless_probe_ok_with_valid_token_despite_api_root_redirect(client) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = _mock_paperless(router)
        resp = await _test_paperless(client, PAPERLESS)
        body = resp.json()
        assert body["ok"] is True and body["status"] == 200
        assert route.calls.last.request.url.query == b"page_size=1"
        assert FAKE_TOKEN not in resp.text


async def test_paperless_probe_rejects_wrong_token(client) -> None:
    with respx.mock(assert_all_called=False) as router:
        _mock_paperless(router)
        resp = await _test_paperless(client, PAPERLESS, token="another-token-value-for-tests")
        body = resp.json()
        assert body["ok"] is False and body["status"] == 401
        assert "another-token-value-for-tests" not in resp.text


@pytest.mark.parametrize(
    "typed",
    [
        PAPERLESS,
        PAPERLESS + "/",
        PAPERLESS + "/api",
        PAPERLESS + "/api/",
    ],
)
async def test_paperless_probe_normalises_typed_url(client, typed) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = _mock_paperless(router)
        body = (await _test_paperless(client, typed)).json()
        assert body["ok"] is True
        assert route.call_count == 1  # exactly /api/documents/, never /api/api/...


async def test_paperless_probe_keeps_subpath(client) -> None:
    base = PAPERLESS + "/paperless"
    with respx.mock(assert_all_called=False) as router:
        route = _mock_paperless(router, base)
        for typed in (base, base + "/", base + "/api/"):
            body = (await _test_paperless(client, typed)).json()
            assert body["ok"] is True
        assert route.call_count == 3


async def test_paperless_probe_ignores_query_in_typed_url(client) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = _mock_paperless(router)
        body = (await _test_paperless(client, PAPERLESS + "/?next=/x")).json()
        assert body["ok"] is True
        assert route.calls.last.request.url.query == b"page_size=1"


async def test_paperless_probe_does_not_follow_redirect_with_secret(client) -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(PAPERLESS + PAPERLESS_DOCS).respond(
            302, headers={"location": "https://evil.example.invalid/x"}
        )
        evil = router.get("https://evil.example.invalid/x").respond(200)
        resp = await _test_paperless(client, PAPERLESS)
        assert resp.json()["ok"] is False and resp.json()["status"] == 302
        assert evil.call_count == 0
        assert FAKE_TOKEN not in resp.text


async def test_integration_probe_reports_invalid_url_instead_of_crashing(
    client, monkeypatch
) -> None:
    monkeypatch.setenv("PRINTER_HUB_GROCY_URL", "http://[::1")
    get_settings.cache_clear()
    resp = await client.post("/api/v1/settings/integrations/grocy/test", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False and body["status"] is None
    assert body["detail"] == "invalid URL"
