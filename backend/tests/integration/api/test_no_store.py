# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""``Cache-Control: no-store`` on the real app's API responses (#160).

All keys are obviously fake test values.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.config import get_settings
from httpx import ASGITransport, AsyncClient

from tests.integration.api.conftest import _client_for
from tests.integration.api.test_auth_session import _insert_key
from tests.integration.api.test_events_v1 import STREAM_PATH, _key_header, _open


async def _app_client(dist: Path, monkeypatch: pytest.MonkeyPatch):
    app = await _client_for(dist, monkeypatch)
    return app, AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def test_api_response_is_no_store(dist: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _app, client = await _app_client(dist, monkeypatch)
    key, _ = await _insert_key(["read"])
    async with client:
        resp = await client.get("/api/v1/printers", headers=_key_header(key))
    get_settings.cache_clear()
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"


async def test_export_download_is_no_store(dist: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _app, client = await _app_client(dist, monkeypatch)
    key, _ = await _insert_key(["admin"])
    async with client:
        resp = await client.get("/api/v1/settings/export", headers=_key_header(key))
    get_settings.cache_clear()
    assert resp.status_code == 200
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.headers["cache-control"] == "no-store"


async def test_readiness_is_no_store(dist: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _app, client = await _app_client(dist, monkeypatch)
    key, _ = await _insert_key(["read"])
    async with client:
        resp = await client.get("/readiness", headers=_key_header(key))
    get_settings.cache_clear()
    assert resp.status_code in (200, 503)
    assert resp.headers["cache-control"] == "no-store"


async def test_sse_keeps_no_cache(dist: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app, client = await _app_client(dist, monkeypatch)
    key, _ = await _insert_key(["admin"])
    async with client:
        assert (await client.get("/healthz")).status_code == 200  # starts the lifespan
        stream = await _open(app, _key_header(key))
        try:
            assert await stream.wait_started() == 200
            assert stream.headers["cache-control"] == "no-cache"
        finally:
            await stream.close()
    get_settings.cache_clear()
    assert STREAM_PATH.startswith("/api/v1/")


async def test_spa_index_unchanged(dist: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _app, client = await _app_client(dist, monkeypatch)
    async with client:
        resp = await client.get("/")
    get_settings.cache_clear()
    assert resp.headers["cache-control"] == "no-cache"


async def test_static_asset_keeps_its_own_cache_control(
    dist: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _app, client = await _app_client(dist, monkeypatch)
    async with client:
        resp = await client.get("/assets/app.js")
    get_settings.cache_clear()
    assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"
