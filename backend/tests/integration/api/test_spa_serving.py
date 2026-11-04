"""The backend serves the web UI (web UI foundation, Task 7).

Every test builds the full app against a temporary ``dist`` directory (or none),
so the routing order, the content negotiation of the legacy job route and the
security headers are checked end to end.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from pathlib import Path

import app.models  # noqa: F401
import pytest
import pytest_asyncio
from app.config import get_settings
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

INDEX_HTML = "<!doctype html><html><body>hub-app-shell</body></html>"
CSP = (
    "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self'; "
    "img-src 'self' data: blob:; connect-src 'self'; style-src 'self'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(INDEX_HTML)
    (root / "assets" / "app.js").write_text("console.log('x')")
    (root / "favicon.svg").write_text("<svg/>")
    return root


async def _client_for(dist_dir: Path, monkeypatch: pytest.MonkeyPatch):
    import app.db.engine as _engine_module
    import app.db.session as _session_module
    from app.integrations import (  # type: ignore[attr-defined]
        IntegrationRegistry,
        _discover_plugins,
    )
    from app.main import create_app

    monkeypatch.setenv("PRINTER_HUB_WEB_DIST_DIR", str(dist_dir))
    get_settings.cache_clear()
    _session_module.async_session = _engine_module.async_session
    if not IntegrationRegistry.names():
        _discover_plugins()
    return create_app()


@pytest_asyncio.fixture
async def spa(dist: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    app = await _client_for(dist, monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        c.app = app  # type: ignore[attr-defined]
        yield c
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def no_spa(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    app = await _client_for(tmp_path / "missing", monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c
    get_settings.cache_clear()


async def test_root_serves_index(spa: AsyncClient) -> None:
    resp = await spa.get("/")
    assert resp.status_code == 200
    assert resp.text == INDEX_HTML
    assert resp.headers["cache-control"] == "no-cache"
    assert resp.headers["content-type"].startswith("text/html")


async def test_client_route_falls_back_to_index(spa: AsyncClient) -> None:
    resp = await spa.get("/printers/abc")
    assert resp.status_code == 200
    assert resp.text == INDEX_HTML


async def test_unknown_api_path_is_json_404(spa: AsyncClient) -> None:
    for path in ("/api/definitely-not-there", "/api/v1/nope/deeper"):
        resp = await spa.get(path)
        assert resp.status_code == 404
        assert resp.headers["content-type"].startswith("application/json")
        assert "hub-app-shell" not in resp.text


async def test_assets_are_immutable(spa: AsyncClient) -> None:
    resp = await spa.get("/assets/app.js")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert resp.text == "console.log('x')"
    # a missing asset is a real 404, never the app shell
    missing = await spa.get("/assets/gone.js")
    assert missing.status_code == 404
    assert "hub-app-shell" not in missing.text


async def test_root_files_are_served_without_long_cache(spa: AsyncClient) -> None:
    resp = await spa.get("/favicon.svg")
    assert resp.status_code == 200
    assert resp.text == "<svg/>"
    assert resp.headers["cache-control"] == "no-cache"


async def test_path_traversal_never_leaves_dist(spa: AsyncClient, dist: Path) -> None:
    (dist.parent / "secret.txt").write_text("outside")
    for path in ("/..%2Fsecret.txt", "/assets/..%2F..%2Fsecret.txt", "/%2e%2e/secret.txt"):
        resp = await spa.get(path)
        assert "outside" not in resp.text


async def test_legacy_job_route_html_for_browser_json_for_client(spa: AsyncClient) -> None:
    from app.auth.dependencies import AuthContext
    from app.auth.scope_deps import require_read

    fake = AuthContext(source="api-key", scope="admin", api_key_id=None, ip="192.0.2.1")
    spa.app._app.dependency_overrides[require_read] = lambda: fake  # type: ignore[attr-defined]
    try:
        browser = await spa.get("/jobs/some-job", headers={"Accept": "text/html,*/*;q=0.8"})
        assert browser.status_code == 200
        assert browser.text == INDEX_HTML
        client = await spa.get("/jobs/some-job", headers={"Accept": "application/json"})
        assert client.status_code == 404
        assert client.headers["content-type"].startswith("application/json")
        assert "some-job" in client.json()["detail"]
        default = await spa.get("/jobs/some-job")  # httpx sends Accept: */*
        assert default.headers["content-type"].startswith("application/json")
    finally:
        spa.app._app.dependency_overrides.clear()  # type: ignore[attr-defined]


@pytest.mark.parametrize("prefix", ["loc", "asset", "spool", "product"])
async def test_qr_paths_serve_app(spa: AsyncClient, prefix: str) -> None:
    resp = await spa.get(f"/{prefix}/ABC-123")
    assert resp.status_code == 200
    assert resp.text == INDEX_HTML


async def test_no_dist_means_api_only(
    no_spa: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    assert (await no_spa.get("/healthz")).status_code == 200
    root = await no_spa.get("/")
    assert root.status_code == 404
    assert root.headers["content-type"].startswith("application/json")
    qr = await no_spa.get("/loc/ABC")
    assert qr.status_code == 404
    assert "content-security-policy" not in {k.lower() for k in qr.headers}


def test_missing_dist_logs_one_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    from app.web.spa import mount_spa

    app = FastAPI()
    with caplog.at_level(logging.WARNING, logger="app.web.spa"):
        mount_spa(app, tmp_path / "nothing")
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert not hasattr(app.state, "spa_index") or app.state.spa_index is None


async def test_spa_has_csp_docs_has_none(spa: AsyncClient) -> None:
    page = await spa.get("/")
    assert page.headers["content-security-policy"] == CSP
    assert page.headers["permissions-policy"] == "camera=(self)"
    assert page.headers["x-content-type-options"] == "nosniff"
    assert page.headers["referrer-policy"] == "same-origin"
    asset = await spa.get("/assets/app.js")
    assert asset.headers["content-security-policy"] == CSP
    for path in ("/docs", "/redoc", "/openapi.json", "/healthz"):
        resp = await spa.get(path)
        assert resp.status_code == 200, path
        assert "content-security-policy" not in {k.lower() for k in resp.headers}, path
        assert resp.headers["x-content-type-options"] == "nosniff", path
        assert resp.headers["referrer-policy"] == "same-origin", path


async def test_old_fragment_stream_gone(spa: AsyncClient, no_spa: AsyncClient) -> None:
    for client in (spa, no_spa):
        resp = await client.get(
            "/api/events", params={"printer_id": "00000000-0000-0000-0000-000000000000"}
        )
        assert resp.status_code == 404
        assert resp.headers["content-type"].startswith("application/json")
