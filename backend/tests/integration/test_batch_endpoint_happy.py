"""Happy-Path: 3 valide Items, alle queued, 0 errors."""
from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_admin, require_print, require_read
from app.models.printer import Printer
from app.repositories import printers as printers_repo


@pytest_asyncio.fixture
async def batch_client():
    """AsyncClient mit gefakter Auth + korrekt gepatchter DB-Session.

    Propagiert den _temp_db_engine-Patch (autouse) in app.db.session.
    Analoges Muster zu test_printers_filter_by_slug.py::slug_client.
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
        yield c


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
async def test_batch_happy_path(batch_client: AsyncClient, batch_db_session, batch_auth_headers):
    p = Printer(name="Brother PT-P750W", slug="brother-p750w",
                model="PT-P750W", backend="mock")
    await printers_repo.create(batch_db_session, p)

    # Mock backend defaults to 24mm loaded tape → use 24mm template to avoid mismatch
    body = {
        "items": [
            {"template_id": "hangar-furniture-24mm",
             "data": {"title": f"Item {i}", "primary_id": f"HH-AK-KX10-F{i:04d}",
                      "qr_payload": f"https://hangar.test/loc/HH-AK-KX10-F{i:04d}"},
             "options": {"copies": 1, "auto_cut": True}}
            for i in range(3)
        ]
    }
    resp = await batch_client.post(f"/api/print/{p.slug}/batch",
                                    json=body, headers=batch_auth_headers)
    assert resp.status_code == 202, resp.text
    data = resp.json()
    assert "batch_id" in data
    assert data["printer_id"] == str(p.id)
    assert len(data["job_ids"]) == 3
    assert data["errors"] == []
