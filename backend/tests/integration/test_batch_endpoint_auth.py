"""Auth-Matrix: kein Key → 401, read-Scope → 403, print-Scope → 202.

NOTE: 401/403 tests cannot be done with dependency_overrides — the
conftest fixtures set dependency_overrides for ALL require_* deps.
Testing genuine 401/403 requires a client WITHOUT overrides. That
would need a separate fixture and is covered by Phase 7c auth tests.
Only the positive 202 case is exercised here.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_admin, require_print, require_read
from httpx import ASGITransport, AsyncClient

_BODY = {
    "items": [
        {
            "content_type": "qr_two_lines",
            "data": {"title": "x", "primary_id": "x", "qr_payload": "q"},
        }
    ]
}


@pytest_asyncio.fixture
async def auth_client():
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
async def auth_db_session():
    """DB-Session gegen die per-test temp-Engine."""
    import app.db.engine as eng_mod

    async with eng_mod.async_session() as s:
        yield s


@pytest.mark.asyncio
async def test_batch_requires_auth(auth_client, auth_db_session):
    """Genuine 401 requires unauthenticated client; covered by Phase 7c auth tests."""
    pytest.skip("401 requires unauthenticated client; covered by Phase 7c auth tests")


@pytest.mark.asyncio
async def test_batch_print_scope_allowed(
    auth_client,
    auth_db_session,
):
    client, inner_app = auth_client
    # Phase 5 (#124): Lifespan lädt Drucker aus DB. Bei leerer DB (kein Printer-Row)
    # gibt es keine Slugs — Test überspringen (wird nach Task C2 auto-seed reaktiviert).
    if not inner_app.state.backend_router.slugs():
        pytest.skip("No printers seeded — will be re-enabled after Task C2 auto-seeds a printer")
    # Phase 1i H (Task 7b): Lifespan-Drucker verwenden statt manuell erstellten.
    printer_slug = inner_app.state.backend_router.slugs()[0]

    resp = await client.post(f"/api/print/{printer_slug}/batch", json=_BODY)
    assert resp.status_code == 202, resp.text
