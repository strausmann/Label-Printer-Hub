"""The backend serves the web UI (web UI foundation, Task 7).

Every test builds the full app against a temporary ``dist`` directory (or none),
so the routing order and the security headers are checked end to end.
"""

from __future__ import annotations

import logging
from pathlib import Path

import app.models  # noqa: F401
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from tests.integration.api.conftest import INDEX_HTML

CSP = (
    "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self'; "
    "img-src 'self' data: blob:; connect-src 'self'; "
    "style-src 'self' 'sha256-38RhXrc7EdReTKsOm23ZPOCUgniTUUcjky8QOOrQx6o=' "
    "'sha256-gYiS/BvZvRcK27JIXTuwhZ3hs2+VJ1X+2gUlE+farlg='; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


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


async def test_spa_has_csp_api_endpoints_have_none(spa: AsyncClient) -> None:
    page = await spa.get("/")
    assert page.headers["content-security-policy"] == CSP
    assert page.headers["permissions-policy"] == "camera=(self)"
    assert page.headers["x-content-type-options"] == "nosniff"
    assert page.headers["referrer-policy"] == "same-origin"
    asset = await spa.get("/assets/app.js")
    assert asset.headers["content-security-policy"] == CSP
    for path in ("/openapi.json", "/healthz"):
        resp = await spa.get(path)
        assert resp.status_code == 200, path
        assert "content-security-policy" not in {k.lower() for k in resp.headers}, path
        assert resp.headers["x-content-type-options"] == "nosniff", path
        assert resp.headers["referrer-policy"] == "same-origin", path


async def test_docs_has_its_own_csp_not_the_spa_one(spa: AsyncClient) -> None:
    resp = await spa.get("/docs")
    assert resp.status_code == 200
    assert "hub-app-shell" not in resp.text
    csp = resp.headers["content-security-policy"]
    assert csp != CSP
    assert "'wasm-unsafe-eval'" not in csp
    assert resp.headers["x-content-type-options"] == "nosniff"


async def test_redoc_behaves_like_any_unknown_address(
    spa: AsyncClient, no_spa: AsyncClient
) -> None:
    # Not reserved any more: the web app answers it like /nothing-here, API-only mode 404s.
    redoc = await spa.get("/redoc", follow_redirects=False)
    other = await spa.get("/nothing-here", follow_redirects=False)
    assert (redoc.status_code, redoc.text) == (other.status_code, other.text) == (200, INDEX_HTML)
    assert (await no_spa.get("/redoc")).status_code == 404


async def test_old_fragment_stream_gone(spa: AsyncClient, no_spa: AsyncClient) -> None:
    for client in (spa, no_spa):
        resp = await client.get(
            "/api/events", params={"printer_id": "00000000-0000-0000-0000-000000000000"}
        )
        assert resp.status_code == 404
        assert resp.headers["content-type"].startswith("application/json")


async def test_unknown_licence_page_is_404(spa: AsyncClient) -> None:
    for path in ("/licenses/does-not-exist.txt", "/licenses/", "/licenses/deeper/nope"):
        resp = await spa.get(path)
        assert resp.status_code == 404, path
        assert "hub-app-shell" not in resp.text, path


async def test_known_licence_file_is_served(spa: AsyncClient, dist: Path) -> None:
    (dist / "licenses").mkdir()
    (dist / "licenses" / "agpl-3.0.txt").write_text("GNU AFFERO GENERAL PUBLIC LICENSE")
    resp = await spa.get("/licenses/agpl-3.0.txt")
    assert resp.status_code == 200
    assert resp.text == "GNU AFFERO GENERAL PUBLIC LICENSE"
    assert resp.headers["cache-control"] == "no-cache"
    assert "hub-app-shell" not in resp.text
