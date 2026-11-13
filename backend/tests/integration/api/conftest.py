"""Shared fixtures for API integration tests.

Phase 1k.1a (Task 25): Removed template_loader and seed_templates references.
Templates are deleted in Phase 1k.1a — the fixture now creates a plain app
client without template seeding.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from app.config import get_settings
from httpx import ASGITransport, AsyncClient

from tests.helpers.spa import INDEX_HTML


@pytest_asyncio.fixture
async def api_client_with_seed():
    """AsyncClient against the full app.

    Propagates the autouse _temp_db_engine patch from
    tests/integration/conftest.py into app.db.session (which holds a
    name-bound `async_session` snapshot taken at import time and is NOT
    updated automatically when engine.py's namespace gets monkey-patched).

    Phase 1k.1a: Template seeding removed (templates table dropped).
    """
    import app.db.engine as _engine_module
    import app.db.session as _session_module
    from app.main import create_app

    _session_module.async_session = _engine_module.async_session

    from app.integrations import (  # type: ignore[attr-defined]
        IntegrationRegistry,
        _discover_plugins,
    )

    if not IntegrationRegistry.names():
        _discover_plugins()

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(INDEX_HTML)
    (root / "assets" / "app.js").write_text("console.log('x')")
    (root / "favicon.svg").write_text("<svg/>")
    (root / "scalar").mkdir()
    (root / "scalar" / "standalone.js").write_text("/* scalar */")
    return root


async def _client_for(dist_dir: Path, monkeypatch: pytest.MonkeyPatch):
    import app.db.engine as _engine_module
    import app.db.session as _session_module
    from app.integrations import (  # type: ignore[attr-defined]
        IntegrationRegistry,
        _discover_plugins,
    )
    from app.main import create_app

    monkeypatch.setenv("LABELYARD_WEB_DIST_DIR", str(dist_dir))
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
