"""Happy-Path: 3 valide Items, alle queued, 0 errors."""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_admin, require_print, require_read
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def batch_client():
    """AsyncClient mit gefakter Auth + korrekt gepatchter DB-Session.

    Propagiert den _temp_db_engine-Patch (autouse) in app.db.session.
    Analoges Muster zu test_printers_filter_by_slug.py::slug_client.

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

    # Propagate the monkeypatched engine into session.py's name binding
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
async def batch_db_session():
    """DB-Session gegen die per-test temp-Engine (analog zu conftest.db_session)."""
    import app.db.engine as eng_mod

    async with eng_mod.async_session() as s:
        yield s


@pytest.fixture
def batch_auth_headers() -> dict:
    """Leere Dict — Auth ist via dependency_overrides gefakt."""
    return {}


@pytest.mark.asyncio
async def test_batch_happy_path(batch_client, batch_db_session, batch_auth_headers):
    client, inner_app = batch_client
    # Phase 1i H (Task 7b): Multi-Printer-Wiring — Drucker kommt aus Lifespan (BackendRouter).
    # Die Lifespan legt 'mock-pt-p750w' via printers.yaml an und registriert es in BackendRouter.
    # Wir lesen Slug und ID aus app.state statt einen eigenen Printer zu erstellen.
    printer_id = inner_app.state.printer_id
    printer_slug = inner_app.state.backend_router.slugs()[0]

    # Mock backend defaults to 24mm loaded tape → use 24mm template to avoid mismatch
    body = {
        "items": [
            {
                "template_id": "hangar-furniture-24mm",
                "data": {
                    "title": f"Item {i}",
                    "primary_id": f"HH-AK-KX10-F{i:04d}",
                    "qr_payload": f"https://hangar.test/loc/HH-AK-KX10-F{i:04d}",
                },
                "options": {"copies": 1, "auto_cut": True},
            }
            for i in range(3)
        ]
    }
    resp = await client.post(
        f"/api/print/{printer_slug}/batch", json=body, headers=batch_auth_headers
    )
    assert resp.status_code == 202, resp.text
    data = resp.json()
    assert "batch_id" in data
    assert data["printer_id"] == str(printer_id)
    assert len(data["job_ids"]) == 3
    assert data["errors"] == []
