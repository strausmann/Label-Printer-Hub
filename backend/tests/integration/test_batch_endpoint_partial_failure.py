"""Partial: 3 Items, 1 mit unbekanntem template_id → 2 queued, 1 error."""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_admin, require_print, require_read
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def partial_client():
    """AsyncClient mit gefakter Auth + korrekt gepatchter DB-Session.

    Yields (client, inner_app) so tests can set inner_app.state.printer_id
    to align with the single-printer-binding check in batch.py.
    """
    import app.db.engine as _eng
    import app.db.session as _sess
    from app.integrations import (  # type: ignore[attr-defined]
        IntegrationRegistry,
        _discover_plugins,
    )
    from app.main import create_app

    _sess.async_session = _eng.async_session

    if not IntegrationRegistry.names():
        _discover_plugins()

    fake = AuthContext(source="api-key", scope="admin", api_key_id=uuid4(), ip="127.0.0.1")
    app = create_app()
    inner = app._app
    for dep in (require_read, require_print, require_admin):
        inner.dependency_overrides[dep] = lambda _c=fake: _c

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        # Touch the app once so lifespan runs and state is populated
        await c.get("/healthz")
        yield c, inner


@pytest_asyncio.fixture
async def partial_db_session():
    """DB-Session gegen die per-test temp-Engine."""
    import app.db.engine as eng_mod

    async with eng_mod.async_session() as s:
        yield s


@pytest.fixture
def partial_auth_headers() -> dict:
    return {}


@pytest.mark.asyncio
async def test_batch_partial_failure(partial_client, partial_db_session, partial_auth_headers):
    client, inner_app = partial_client
    # Phase 1i H (Task 7b): Lifespan-Drucker verwenden statt manuell erstellten.
    printer_slug = inner_app.state.backend_router.slugs()[0]

    # Mock backend loads 24mm → use 24mm for valid items, unknown ID for the failing one
    body = {
        "items": [
            {
                "template_id": "hangar-furniture-24mm",
                "data": {"title": "A", "primary_id": "A", "qr_payload": "qA"},
            },
            {
                "template_id": "does-not-exist",
                "data": {"title": "B", "primary_id": "B", "qr_payload": "qB"},
            },
            {
                "template_id": "hangar-furniture-24mm",
                "data": {"title": "C", "primary_id": "C", "qr_payload": "qC"},
            },
        ]
    }
    resp = await client.post(f"/api/print/{printer_slug}/batch", json=body, headers=partial_auth_headers)
    assert resp.status_code == 202, resp.text
    data = resp.json()
    assert len(data["job_ids"]) == 2
    assert len(data["errors"]) == 1
    assert data["errors"][0]["index"] == 1
    assert data["errors"][0]["error_code"] == "template_not_found"
