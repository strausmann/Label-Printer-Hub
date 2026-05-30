"""Mix 12mm + 24mm, eingelegt 24mm: 24mm queued, 12mm failed per-item."""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_admin, require_print, require_read
from app.models.printer import Printer
from app.printer_backends.exceptions import TapeMismatchError
from app.repositories import printers as printers_repo
from app.services.print_service import PrintService
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def tape_client():
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
async def tape_db_session():
    """DB-Session gegen die per-test temp-Engine."""
    import app.db.engine as eng_mod

    async with eng_mod.async_session() as s:
        yield s


@pytest.fixture
def tape_auth_headers() -> dict:
    return {}


@pytest.mark.asyncio
async def test_batch_tape_mismatch_per_item(
    tape_client,
    tape_db_session,
    tape_auth_headers,
    monkeypatch,
):
    client, inner_app = tape_client
    p = Printer(name="Brother PT-P750W", slug="brother-p750w", model="PT-P750W", backend="mock")
    await printers_repo.create(tape_db_session, p)
    # Align app state with our test printer (single-printer-binding check)
    inner_app.state.printer_id = p.id

    # Simulate: 24mm loaded, 12mm items fail with tape_mismatch, 24mm items succeed
    async def _maybe_raise(self, req):
        if req.template_id == "hangar-furniture-12mm":
            raise TapeMismatchError(expected_mm=12, loaded_mm=24)
        return str(uuid4())

    monkeypatch.setattr(PrintService, "submit_print_job", _maybe_raise)

    body = {
        "items": [
            {
                "template_id": "hangar-furniture-24mm",
                "data": {"title": "A", "primary_id": "A", "qr_payload": "q"},
                "on_tape_mismatch": "fail",
            },
            {
                "template_id": "hangar-furniture-12mm",
                "data": {"title": "B", "primary_id": "B", "qr_payload": "q"},
                "on_tape_mismatch": "fail",
            },
            {
                "template_id": "hangar-furniture-24mm",
                "data": {"title": "C", "primary_id": "C", "qr_payload": "q"},
                "on_tape_mismatch": "fail",
            },
        ]
    }
    resp = await client.post(f"/api/print/{p.slug}/batch", json=body, headers=tape_auth_headers)
    assert resp.status_code == 202, resp.text
    data = resp.json()
    assert len(data["job_ids"]) == 2
    assert len(data["errors"]) == 1
    assert data["errors"][0]["index"] == 1
    assert data["errors"][0]["error_code"] == "tape_mismatch"
    assert data["errors"][0]["error_detail"] == {"expected_mm": 12, "loaded_mm": 24}
