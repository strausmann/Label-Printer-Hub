"""Shared fixtures for API integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# TODO(#22): simplify this fixture once Phase 7b Task D2 lands —
# the lifespan re-order (load_dir BEFORE seed_templates) will let us drop
# the manual TemplateLoader.load_dir() + seed_templates() pre-seeding here.

_SEED_DIR = Path(__file__).parents[3] / "app" / "seed" / "templates"


@pytest_asyncio.fixture
async def api_client_with_seed():
    """AsyncClient against the full app with templates seeded.

    Propagates the autouse _temp_db_engine patch from
    tests/integration/conftest.py into app.db.session (which holds a
    name-bound `async_session` snapshot taken at import time and is NOT
    updated automatically when engine.py's namespace gets monkey-patched).
    """
    import app.db.engine as _engine_module
    import app.db.session as _session_module
    from app.db.lifespan import seed_templates
    from app.main import create_app
    from app.services.template_loader import TemplateLoader

    _session_module.async_session = _engine_module.async_session

    # Re-run integration plugin discovery when the lifespan from a previous
    # test has cleared IntegrationRegistry (see main.py lifespan shutdown).
    # TemplateLoader.load_dir validates template.app against IntegrationRegistry,
    # so we must ensure the registry is populated before calling load_dir.
    from app.integrations import (  # type: ignore[attr-defined]
        IntegrationRegistry,
        _discover_plugins,
    )

    if not IntegrationRegistry.names():
        _discover_plugins()

    original_cache = dict(TemplateLoader._cache)
    TemplateLoader.load_dir(_SEED_DIR)
    try:
        async with _engine_module.async_session() as s:
            await seed_templates(s, TemplateLoader)

        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            yield c
    finally:
        TemplateLoader._cache = original_cache
