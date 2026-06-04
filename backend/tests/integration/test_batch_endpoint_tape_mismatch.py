"""Phase 1k.2: Tape-Mismatch ist jetzt ein fataler Batch-Fehler (nicht per-item).

Szenarien:
- Alle Items gleiche tape_mm + falsches Tape eingelegt → TapeMismatchError → 409.
- Items mit gemischter tape_mm → MixedTapeSizesError → 400.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_admin, require_print, require_read
from app.printer_backends.exceptions import TapeMismatchError
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
    """Phase 1k.2: Alle Items gleiche tape_mm + falsches Tape → TapeMismatchError → 409.

    Vorher (Phase 1i): TapeMismatchError war ein per-item-Fehler (best-effort).
    Jetzt (Phase 1k.2): TapeMismatchError ist fatal — der gesamte Batch wird abgelehnt.
    submit_batch_job prüft das Tape 1x für alle Items.
    """
    client, inner_app = tape_client
    # Phase 1i H (Task 7b): Lifespan-Drucker verwenden statt manuell erstellten.
    printer_slug = inner_app.state.backend_router.slugs()[0]

    # Phase 1k.2: submit_batch_job (nicht mehr submit_print_job) wird aufgerufen.
    # Simuliere: 24mm tape geladen, alle Items erwarten 12mm → TapeMismatchError.
    async def _raise_mismatch(self, requests, *, half_cut):
        raise TapeMismatchError(expected_mm=12, loaded_mm=24)

    monkeypatch.setattr(PrintService, "submit_batch_job", _raise_mismatch)

    body = {
        "items": [
            {
                "template_id": "hangar-furniture-12mm",
                "data": {"title": "A", "primary_id": "A", "qr_payload": "q"},
            },
            {
                "template_id": "hangar-furniture-12mm",
                "data": {"title": "B", "primary_id": "B", "qr_payload": "q"},
            },
        ]
    }
    resp = await client.post(
        f"/api/print/{printer_slug}/batch", json=body, headers=tape_auth_headers
    )
    # Phase 1k.2: TapeMismatchError propagiert als fataler Fehler → 409
    assert resp.status_code == 409, resp.text
    data = resp.json()
    assert data["detail"]["error_code"] == "tape_mismatch"


@pytest.mark.asyncio
async def test_batch_mixed_tape_sizes_returns_400(
    tape_client,
    tape_db_session,
    tape_auth_headers,
):
    """Phase 1k.2: Batch mit Items die verschiedene tape_mm Templates nutzen → 400.

    MixedTapeSizesError wird von dispatch_batch VOR submit_batch_job geworfen.
    Der Route-Layer mappt das auf HTTP 400.
    """
    client, inner_app = tape_client
    printer_slug = inner_app.state.backend_router.slugs()[0]

    body = {
        "items": [
            {
                "template_id": "hangar-furniture-12mm",
                "data": {"title": "A", "primary_id": "A", "qr_payload": "q"},
            },
            {
                "template_id": "hangar-furniture-24mm",
                "data": {"title": "B", "primary_id": "B", "qr_payload": "q"},
            },
        ]
    }
    resp = await client.post(
        f"/api/print/{printer_slug}/batch", json=body, headers=tape_auth_headers
    )
    assert resp.status_code == 400, resp.text
    data = resp.json()
    assert data["detail"]["error_code"] == "mixed_tape_sizes"
    assert set(data["detail"]["tape_mm_values"]) == {12, 24}
