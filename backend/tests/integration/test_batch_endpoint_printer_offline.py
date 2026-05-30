"""Offline-Printer → 409 für ganzen Batch, kein Job queued."""
from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_admin, require_print, require_read
from app.models.printer import Printer
from app.printer_backends.exceptions import PrinterOfflineError
from app.repositories import printers as printers_repo
from app.services.print_service import PrintService


@pytest_asyncio.fixture
async def offline_client():
    """AsyncClient mit gefakter Auth + korrekt gepatchter DB-Session."""
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
        yield c


@pytest_asyncio.fixture
async def offline_db_session():
    """DB-Session gegen die per-test temp-Engine."""
    import app.db.engine as eng_mod

    async with eng_mod.async_session() as s:
        yield s


@pytest.fixture
def offline_auth_headers() -> dict:
    return {}


@pytest.mark.asyncio
async def test_batch_rejects_when_printer_offline(
    offline_client: AsyncClient,
    offline_db_session,
    offline_auth_headers,
    monkeypatch,
):
    p = Printer(name="Brother PT-P750W", slug="brother-p750w",
                model="PT-P750W", backend="mock")
    await printers_repo.create(offline_db_session, p)

    async def _raise(self, req):
        raise PrinterOfflineError("printer is offline")

    monkeypatch.setattr(PrintService, "submit_print_job", _raise)

    body = {"items": [{"template_id": "hangar-furniture-24mm",
                       "data": {"title": "A", "primary_id": "A", "qr_payload": "q"}}]}
    resp = await offline_client.post(f"/api/print/{p.slug}/batch",
                                      json=body, headers=offline_auth_headers)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["error_code"] == "printer_offline"
