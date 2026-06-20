"""SSE-Generator zeigt Events für alle Jobs eines Batches.

Strategie: _sse_stream direkt aufrufen (NICHT client.stream, weil ASGITransport
SSE-Streams buffert — siehe test_phase6b_sse.py:7-16).

Die Fixtures spiegeln das Muster aus test_batch_endpoint_happy.py — eigene
lokale Fixtures statt conftest-Fixtures, weil _temp_db_engine (autouse) nur
unter bestimmten Bedingungen korrekt in die session-Bindung propagiert wird.
Nach dem Batch-Submit wird _sse_stream direkt mit dem bus aus app._app.state
aufgerufen, damit derselbe EventBus den die PrintQueue beschreibt auch
abonniert wird.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from uuid import uuid4

import pytest
import pytest_asyncio
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_admin, require_print, require_read
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Local fixtures — mirror test_batch_endpoint_happy.py pattern
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def sse_batch_app():
    """_LifespanManager mit gefakter Auth und propagierter temp-DB-Engine.

    Gibt den _LifespanManager zurück damit ASGITransport die Lifespan
    ausführt (event_bus + print_service werden dort gestartet).
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

    return app


@pytest_asyncio.fixture
async def sse_batch_client(sse_batch_app):
    """AsyncClient gegen die App — Lifespan startet bei erster Anfrage."""
    async with AsyncClient(transport=ASGITransport(app=sse_batch_app), base_url="http://t") as c:
        yield c


@pytest_asyncio.fixture
async def sse_batch_db_session():
    """DB-Session gegen die per-test temp-Engine (analog zu conftest.db_session)."""
    import app.db.engine as eng_mod

    async with eng_mod.async_session() as s:
        yield s


@pytest.fixture
def sse_batch_auth_headers() -> dict:
    """Leere Dict — Auth ist via dependency_overrides gefakt."""
    return {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_request() -> object:
    """Minimaler mock Request — _sse_stream liest headers und ruft is_disconnected."""
    from unittest.mock import MagicMock

    disconnect_flag = asyncio.Event()

    async def _is_disconnected() -> bool:
        return disconnect_flag.is_set()

    req = MagicMock()
    req.headers = {}
    req.client = None
    req.is_disconnected = _is_disconnected
    req._disconnect_flag = disconnect_flag
    return req


# ---------------------------------------------------------------------------
# T-B5: SSE-Stream enthält Events für alle Jobs eines Batches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sse_contains_batch_job_events(
    sse_batch_client: AsyncClient,
    sse_batch_app,
    sse_batch_db_session,
    sse_batch_auth_headers: dict,
) -> None:
    """Submit Batch → PrintQueue publiziert Events → _sse_stream emittiert sie.

    Ablauf:
    1. Lifespan triggern (erster Request) — event_bus, print_service und
       app.state.printer_id werden initialisiert (zufällige UUID, da kein Host).
    2. Printer-Row in der DB mit derselben ID anlegen (id=app.state.printer_id),
       damit batch.py's single-printer-binding-Check printer.id == seeded_printer_id
       besteht, ohne dass wir die internen PrintQueue-Strukturen umpatchem müssen.
    3. App-internen EventBus und printer_id aus app._app.state lesen.
    4. _sse_stream direkt aufrufen (umgeht ASGITransport-Buffering).
    5. Batch submiten und warten bis alle 3 job_ids in SSE-Frames erscheinen (≤5 s).
    """
    import app.api.routes.events as events_mod

    # 1. Lifespan triggern (erster Request startet event_bus + print_service)
    warmup = await sse_batch_client.get("/healthz")
    assert warmup.status_code == 200, f"warmup failed: {warmup.status_code}"

    # 2. EventBus + printer_id aus app state lesen — Lifespan hat gestartet.
    inner = sse_batch_app._app  # FastAPI-Instanz hinter _LifespanManager
    bus = inner.state.event_bus
    # printer_id aus dem Lifespan — PrintQueueProducer schreibt auf
    # f"printer:{printer_id}:queue"

    # Phase 5 (#124): Lifespan lädt Drucker aus DB. Bei leerer DB (kein Printer-Row)
    # gibt es keine Slugs — Test überspringen (wird nach Task C2 auto-seed reaktiviert).
    if not inner.state.backend_router.slugs():
        pytest.skip("No printers seeded — will be re-enabled after Task C2 auto-seeds a printer")

    app_printer_id: uuid.UUID = inner.state.printer_id

    # 3. Printer-Row mit ID=app_printer_id sicherstellen und Lifespan-Slug lesen.
    #    Phase 5 (#124): Slug kommt aus backend_router (geladen aus DB).
    printer_slug = inner.state.backend_router.slugs()[0]

    channels = [
        f"printer:{app_printer_id}:queue",
        f"printer:{app_printer_id}:state",
        f"printer:{app_printer_id}:tape",
    ]
    subscriber_id = "test-b5-sse-batch"
    request = _mock_request()

    # 4. _sse_stream ZUERST starten (Bypass ASGITransport-Buffering)
    #    Die Subscription muss VOR dem Batch-Submit aktiv sein, sonst
    #    werden Events emittiert bevor wir abonniert haben.
    gen = events_mod._sse_stream(
        app_printer_id,
        bus,
        request,
        subscriber_id,
        channels,
    )

    seen_jobs: set[str] = set()
    frame_queue: asyncio.Queue[str] = asyncio.Queue()

    async def pump() -> None:
        async for frame in gen:
            await frame_queue.put(frame)

    pump_task = asyncio.create_task(pump())
    # Generator warmlaufen lassen bis subscribe() + asyncio.wait erreicht
    await asyncio.sleep(0.1)

    # 5. Batch submiten — jetzt ist die Subscription aktiv
    body = {
        "items": [
            {
                "content_type": "qr_two_lines",
                "data": {
                    "title": f"T{i}",
                    "primary_id": f"P{i}",
                    "qr_payload": "https://hangar.test/q",
                },
            }
            for i in range(3)
        ]
    }
    resp = await sse_batch_client.post(
        f"/api/print/{printer_slug}/batch",
        json=body,
        headers=sse_batch_auth_headers,
    )
    assert resp.status_code == 202, resp.text
    job_ids: set[str] = set(resp.json()["job_ids"])
    assert len(job_ids) == 3, f"expected 3 job_ids, got {resp.json()['job_ids']}"

    # 6. Frames konsumieren bis alle job_ids gesehen oder Timeout
    deadline = asyncio.get_event_loop().time() + 5.0
    while asyncio.get_event_loop().time() < deadline and seen_jobs < job_ids:
        try:
            frame = await asyncio.wait_for(frame_queue.get(), timeout=0.2)
            for jid in job_ids:
                if jid in frame:
                    seen_jobs.add(jid)
        except TimeoutError:
            continue

    # Teardown — Disconnect signalisieren
    request._disconnect_flag.set()  # type: ignore[attr-defined]
    pump_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await pump_task
    with contextlib.suppress(Exception):
        await gen.aclose()

    assert seen_jobs == job_ids, (
        f"SSE-Stream enthielt keine Events für: {job_ids - seen_jobs}\n"
        f"Gesehene job_ids: {seen_jobs}"
    )
