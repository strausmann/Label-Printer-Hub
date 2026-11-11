"""The interactive API reference at ``/docs`` (Scalar, served by the hub itself).

Covers issue #171: the page shows the running release instead of the package
placeholder, uses the "Label Printer Hub API" title, loads Scalar from the hub
(no CDN) under a strict CSP.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import AsyncIterator
from html.parser import HTMLParser
from pathlib import Path

import app.models  # noqa: F401
import pytest
import pytest_asyncio
from app.config import get_settings
from httpx import ASGITransport, AsyncClient

BUNDLE_BODY = "/* fake scalar bundle for tests */ window.__scalar = true;"
INDEX_HTML = "<!doctype html><html><body>hub-app-shell</body></html>"


def _make_dist(root: Path, *, with_bundle: bool) -> Path:
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(INDEX_HTML)
    if with_bundle:
        (root / "scalar").mkdir()
        (root / "scalar" / "standalone.js").write_text(BUNDLE_BODY)
    return root


async def _client(dist_dir: Path, monkeypatch: pytest.MonkeyPatch, hub_version: str | None = None):
    import app.db.engine as _engine_module
    import app.db.session as _session_module
    import app.main as main_module
    from app.integrations import (  # type: ignore[attr-defined]
        IntegrationRegistry,
        _discover_plugins,
    )

    monkeypatch.setenv("LABELYARD_WEB_DIST_DIR", str(dist_dir))
    if hub_version is not None:
        monkeypatch.setattr(main_module, "HUB_VERSION", hub_version)
    get_settings.cache_clear()
    _session_module.async_session = _engine_module.async_session
    if not IntegrationRegistry.names():
        _discover_plugins()
    return main_module.create_app()


@pytest_asyncio.fixture
async def docs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    dist = _make_dist(tmp_path / "dist", with_bundle=True)
    app = await _client(dist, monkeypatch, hub_version="7.6.5")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def docs_no_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    dist = _make_dist(tmp_path / "dist", with_bundle=False)
    app = await _client(dist, monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c
    get_settings.cache_clear()


async def test_openapi_info_version_is_the_hub_version(docs: AsyncClient) -> None:
    info = (await docs.get("/openapi.json")).json()["info"]
    assert info["version"] == "7.6.5"
    # The OpenAPI *specification* version stays pinned (ADR 0011), unrelated to info.version.
    assert (await docs.get("/openapi.json")).json()["openapi"] == "3.1.0"


def test_hub_version_env_reaches_openapi_info_in_a_fresh_process() -> None:
    """HUB_VERSION is read at import time, so only a fresh interpreter proves the env path."""
    code = (
        "import json, app.main as m; "
        "print(json.dumps({'hub': m.HUB_VERSION, "
        "'info': m.app._app.openapi()['info']['version']}))"
    )
    env = {**os.environ, "HUB_VERSION": "9.8.7"}
    out = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
    )
    assert json.loads(out.stdout.strip().splitlines()[-1]) == {"hub": "9.8.7", "info": "9.8.7"}


async def test_openapi_title_and_description_have_no_backend_wording(docs: AsyncClient) -> None:
    info = (await docs.get("/openapi.json")).json()["info"]
    assert info["title"] == "Label Printer Hub API"
    assert "backend" not in info["description"].lower()
    assert "/docs" in info["description"]
    assert "Scalar" in info["description"]
    assert "/openapi.json" in info["description"]
    assert "swagger" not in info["description"].lower()


async def test_docs_page_is_scalar_from_the_hub(docs: AsyncClient) -> None:
    resp = await docs.get("/docs")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert resp.headers["cache-control"] == "no-cache"
    html = resp.text
    assert "<title>Label Printer Hub API</title>" in html
    assert 'data-url="/openapi.json"' in html
    assert 'src="/docs/scalar.js"' in html
    assert "swagger" not in html.lower()


class _ScriptCollector(HTMLParser):
    """Collect every <script> element as (attributes, text content)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.scripts: list[tuple[dict[str, str | None], str]] = []
        self._current: tuple[dict[str, str | None], list[str]] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            self._current = (dict(attrs), [])

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._current[1].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._current is not None:
            attrs, parts = self._current
            self.scripts.append((attrs, "".join(parts)))
            self._current = None


def _collect_scripts(html: str) -> list[tuple[dict[str, str | None], str]]:
    parser = _ScriptCollector()
    parser.feed(html)
    parser.close()
    return parser.scripts


async def test_docs_page_has_no_external_urls_and_no_inline_script(docs: AsyncClient) -> None:
    html = (await docs.get("/docs")).text
    assert not re.search(r"""(?:src|href)\s*=\s*["']?(?:https?:)?//""", html)
    # Every <script> must be an external file or an inert data block, never inline code.
    # Parsed with the stdlib HTML parser rather than a regex, so case and odd end tags
    # (`</SCRIPT >`, `</script\t\nfoo>`) are handled the way a browser handles them.
    scripts = _collect_scripts(html)
    assert scripts, "the docs page must load Scalar through a <script> element"
    for attrs, body in scripts:
        assert body.strip() == ""
        assert "src" in attrs or attrs.get("type") == "application/json"


async def test_docs_page_disables_third_party_features(docs: AsyncClient) -> None:
    html = (await docs.get("/docs")).text
    match = re.search(r"data-configuration='([^']*)'", html)
    assert match is not None
    cfg = json.loads(match.group(1).replace("&quot;", '"'))
    assert cfg["withDefaultFonts"] is False
    assert cfg["telemetry"] is False
    assert "proxyUrl" not in cfg
    assert cfg["agent"] == {"disabled": True}
    assert cfg["mcp"] == {"disabled": True}
    assert cfg["showDeveloperTools"] == "never"


async def test_docs_csp_allows_only_the_hub_and_inline_styles(docs: AsyncClient) -> None:
    csp = (await docs.get("/docs")).headers["content-security-policy"]
    directives = {d.split()[0]: d.split()[1:] for d in csp.split("; ") if d}
    assert directives["default-src"] == ["'self'"]
    assert directives["script-src"] == ["'self'"]
    assert directives["connect-src"] == ["'self'"]
    assert directives["frame-ancestors"] == ["'none'"]
    # Scalar injects <style> elements at runtime (needs unsafe-inline); scripts must never get it.
    assert "'unsafe-inline'" in directives["style-src"]
    assert "'unsafe-inline'" not in directives["script-src"]
    assert "'unsafe-eval'" not in csp
    assert "http" not in csp
    assert "nonce" not in csp


async def test_docs_bundle_is_served_by_the_hub(docs: AsyncClient) -> None:
    resp = await docs.get("/docs/scalar.js")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/javascript")
    assert resp.text == BUNDLE_BODY
    assert resp.headers["x-content-type-options"] == "nosniff"


async def test_docs_without_bundle_is_an_explicit_503_not_a_broken_page(
    docs_no_bundle: AsyncClient,
) -> None:
    page = await docs_no_bundle.get("/docs")
    assert page.status_code == 503
    assert "not available" in page.json()["detail"]
    assert (await docs_no_bundle.get("/docs/scalar.js")).status_code == 404
    # The API itself is unaffected.
    assert (await docs_no_bundle.get("/openapi.json")).status_code == 200


async def test_redoc_is_no_longer_a_docs_page(docs: AsyncClient) -> None:
    # Not reserved any more: it behaves like any unknown address (here: the web app shell).
    resp = await docs.get("/redoc", follow_redirects=False)
    assert resp.status_code == 200
    assert resp.text == INDEX_HTML


async def test_openapi_json_still_served_at_its_path(docs: AsyncClient) -> None:
    resp = await docs.get("/openapi.json")
    assert resp.status_code == 200
    assert "paths" in resp.json()


async def test_no_swagger_oauth_redirect_route_remains(docs: AsyncClient) -> None:
    resp = await docs.get("/docs/oauth2-redirect")
    assert resp.status_code == 404
