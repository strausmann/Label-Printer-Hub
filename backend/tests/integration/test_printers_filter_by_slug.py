"""GET /api/printers?slug=... filtert auf einzelnen Printer."""

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
async def slug_client():
    """AsyncClient mit gefakter Auth + korrekt gepatchter DB-Session.

    Propagiert den _temp_db_engine-Patch (autouse, setzt eng_mod.async_session)
    in app.db.session (Name-Binding, wird NICHT automatisch aktualisiert).
    Analog zu tests/integration/api/conftest.py::api_client_with_seed.
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
async def slug_db_session():
    """DB-Session gegen die per-test temp-Engine (analog zu conftest.db_session)."""
    import app.db.engine as eng_mod

    async with eng_mod.async_session() as s:
        yield s


@pytest.fixture
def read_auth_headers() -> dict:
    """Leere Dict — Auth ist via dependency_overrides gefakt."""
    return {}


@pytest.mark.asyncio
async def test_filter_by_slug_returns_one(
    slug_client: AsyncClient,
    slug_db_session,
    read_auth_headers,
):
    # Phase 5 (#124): Lifespan lädt Drucker aus DB beim ersten Request. Wenn
    # Printer-Rows VOR dem ersten API-Call gesetzt werden, versucht die Lifespan
    # echte Model-Treiber zu initialisieren (QL-820NWB → ModelNotFoundError).
    # Test wird nach Task C2 (DB-kompatibler Mock-Seed) reaktiviert.
    pytest.skip(
        "Phase 5: DB-Seed vor erstem API-Call triggert Lifespan-ModelRegistry — "
        "wird nach Task C2 reaktiviert"
    )
    await printers_repo.create(
        slug_db_session,
        Printer(name="Brother PT-P750W", slug="brother-p750w", model="PT-P750W", backend="ptouch"),
    )
    await printers_repo.create(
        slug_db_session,
        Printer(
            name="Brother QL-820NWB", slug="brother-ql820nwb", model="QL-820NWB", backend="ptouch"
        ),
    )

    resp = await slug_client.get("/api/printers?slug=brother-p750w", headers=read_auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["slug"] == "brother-p750w"


@pytest.mark.asyncio
async def test_filter_by_slug_returns_404_when_missing(slug_client, read_auth_headers):
    resp = await slug_client.get("/api/printers?slug=unknown", headers=read_auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_no_filter_returns_all(slug_client: AsyncClient, slug_db_session, read_auth_headers):
    # Phase 5 (#124): Lifespan lädt Drucker aus DB beim ersten Request. Wenn
    # Printer-Rows VOR dem ersten API-Call gesetzt werden, versucht die Lifespan
    # echte Model-Treiber zu initialisieren (model="X" → ModelNotFoundError).
    # Test wird nach Task C2 (DB-kompatibler Mock-Seed) reaktiviert.
    pytest.skip(
        "Phase 5: DB-Seed vor erstem API-Call triggert Lifespan-ModelRegistry — "
        "wird nach Task C2 reaktiviert"
    )
    await printers_repo.create(
        slug_db_session, Printer(name="A", slug="a", model="X", backend="mock")
    )
    await printers_repo.create(
        slug_db_session, Printer(name="B", slug="b", model="X", backend="mock")
    )

    resp = await slug_client.get("/api/printers", headers=read_auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 2
