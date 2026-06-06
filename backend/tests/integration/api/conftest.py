"""Shared fixtures for API integration tests.

Phase 1k.1a (Task 25): Removed template_loader and seed_templates references.
Templates are deleted in Phase 1k.1a — the fixture now creates a plain app
client without template seeding.
"""

from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient


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
