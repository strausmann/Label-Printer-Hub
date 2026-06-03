"""Phase 1i C-Fix: printer_slug Konsistenz-Check in der Batch-Route."""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_admin, require_print, require_read
from app.models.printer import Printer
from app.repositories import printers as printers_repo
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def slug_check_client():
    """AsyncClient mit gefakter Auth für printer_slug Konsistenz-Tests."""
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
        await c.get("/healthz")
        yield c, inner


@pytest_asyncio.fixture
async def slug_check_db_session():
    """DB-Session gegen die per-test temp-Engine."""
    import app.db.engine as eng_mod

    async with eng_mod.async_session() as s:
        yield s


@pytest.mark.asyncio
async def test_batch_route_rejects_mismatched_printer_slug(
    slug_check_client, slug_check_db_session
):
    """body.printer_slug != URL slug → 400 printer_slug_mismatch."""
    client, inner_app = slug_check_client
    p = Printer(name="Brother PT-P750W", slug="brother-p750w", model="PT-P750W", backend="mock")
    await printers_repo.create(slug_check_db_session, p)
    inner_app.state.printer_id = p.id

    body = {
        "items": [
            {
                "template_id": "hangar-furniture-24mm",
                "data": {"title": "A", "primary_id": "A", "qr_payload": "q"},
            }
        ],
        "printer_slug": "wrong-slug",  # mismatch with URL "brother-p750w"
    }
    resp = await client.post(f"/api/print/{p.slug}/batch", json=body)
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["error_code"] == "printer_slug_mismatch"


@pytest.mark.asyncio
async def test_batch_route_accepts_matching_printer_slug(
    slug_check_client, slug_check_db_session
):
    """body.printer_slug == URL slug → 202 accepted."""
    client, inner_app = slug_check_client
    p = Printer(name="Brother PT-P750W", slug="brother-p750w", model="PT-P750W", backend="mock")
    await printers_repo.create(slug_check_db_session, p)
    inner_app.state.printer_id = p.id

    body = {
        "items": [
            {
                "template_id": "hangar-furniture-24mm",
                "data": {"title": "A", "primary_id": "A", "qr_payload": "q"},
            }
        ],
        "printer_slug": "brother-p750w",  # matches URL slug
    }
    resp = await client.post(f"/api/print/{p.slug}/batch", json=body)
    assert resp.status_code == 202, resp.text


@pytest.mark.asyncio
async def test_batch_route_accepts_none_printer_slug(
    slug_check_client, slug_check_db_session
):
    """body.printer_slug=None (default) → kein Konsistenz-Check, 202 accepted."""
    client, inner_app = slug_check_client
    p = Printer(name="Brother PT-P750W", slug="brother-p750w", model="PT-P750W", backend="mock")
    await printers_repo.create(slug_check_db_session, p)
    inner_app.state.printer_id = p.id

    body = {
        "items": [
            {
                "template_id": "hangar-furniture-24mm",
                "data": {"title": "A", "primary_id": "A", "qr_payload": "q"},
            }
        ],
        # printer_slug not set (defaults to None) — no check
    }
    resp = await client.post(f"/api/print/{p.slug}/batch", json=body)
    assert resp.status_code == 202, resp.text
