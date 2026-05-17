"""Phase 7b Cluster 1f — /api/printers/{id}/status reads cache, never blocks."""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_printer(session_factory):
    """Insert one Printer row and return its UUID."""
    from app.models.printer import Printer

    async with session_factory() as s:
        p = Printer(
            name="cache-endpoint-test",
            model="PT-P750W",
            backend="ptouch",
            connection={"host": "127.0.0.1", "port": 9100},
        )
        s.add(p)
        await s.commit()
        await s.refresh(p)
        return p.id


async def _insert_cache(session_factory, printer_id, parsed: dict):
    """Insert a PrinterStatusCache row for the given printer."""
    from app.models.printer_status_cache import PrinterStatusCache

    async with session_factory() as s:
        row = PrinterStatusCache(
            printer_id=printer_id,
            parsed=parsed,
            captured_at=datetime.now(UTC),
        )
        s.add(row)
        await s.commit()


def _build_test_app(session):
    """Return a minimal FastAPI app with only the printers router."""
    from collections.abc import AsyncIterator

    from app.api.routes.printers import router
    from app.db.session import get_session
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession

    app = FastAPI()
    app.include_router(router)

    async def _override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override
    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def api_client_with_printer_no_cache():
    """AsyncClient + printer UUID; no cache row exists."""
    import app.db.engine as _eng
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    factory = _eng.async_session
    printer_id = await _insert_printer(factory)

    # Open a session that lives for the whole test
    session_factory: async_sessionmaker[AsyncSession] = factory
    async with session_factory() as s:
        from httpx import ASGITransport, AsyncClient

        app = _build_test_app(s)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            yield c, printer_id


@pytest_asyncio.fixture
async def api_client_with_warm_cache():
    """AsyncClient + printer UUID; cache row with online=True exists."""
    import app.db.engine as _eng
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    factory = _eng.async_session
    printer_id = await _insert_printer(factory)
    await _insert_cache(
        factory,
        printer_id,
        {
            "online": True,
            "loaded_tape_mm": 12,
            "hr_printer_status": "idle",
            "error_flags": [],
        },
    )

    session_factory: async_sessionmaker[AsyncSession] = factory
    async with session_factory() as s:
        from httpx import ASGITransport, AsyncClient

        app = _build_test_app(s)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            yield c, printer_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_status_endpoint_returns_pending_when_cache_empty(
    api_client_with_printer_no_cache,
):
    """When no cache row exists the endpoint returns online=None and a note."""
    client, pid = api_client_with_printer_no_cache
    resp = await client.get(f"/api/printers/{pid}/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["online"] is None
    assert body["note"] is not None
    assert "no probe yet" in body["note"].lower()


async def test_status_endpoint_returns_under_100ms(api_client_with_warm_cache):
    """Even with no live SNMP path, the endpoint answers from cache in <100ms."""
    client, pid = api_client_with_warm_cache
    t0 = time.monotonic()
    resp = await client.get(f"/api/printers/{pid}/status")
    elapsed_ms = (time.monotonic() - t0) * 1000
    assert resp.status_code == 200
    assert elapsed_ms < 100, f"endpoint blocked {elapsed_ms:.1f}ms"
    body = resp.json()
    assert body["online"] is True


async def test_status_endpoint_returns_404_for_unknown_printer(
    api_client_with_printer_no_cache,
):
    """Unknown printer UUID returns 404."""
    from uuid import uuid4

    client, _ = api_client_with_printer_no_cache
    resp = await client.get(f"/api/printers/{uuid4()}/status")
    assert resp.status_code == 404


async def test_status_endpoint_returns_cached_tape_data(api_client_with_warm_cache):
    """Cached loaded_tape_mm + error_flags surface as PrinterStatus.tape_loaded
    and PrinterStatus.error_state respectively (bot-review finding on PR #75)."""
    client, pid = api_client_with_warm_cache
    resp = await client.get(f"/api/printers/{pid}/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["online"] is True
    # last_probe_age_s should be present and non-negative
    assert body.get("last_probe_age_s") is not None
    assert body["last_probe_age_s"] >= 0
    # Cached parsed JSON is rendered into the documented schema fields,
    # not silently dropped: loaded_tape_mm=12 → tape_loaded="12mm",
    # error_flags=[] → error_state=None.
    assert body["tape_loaded"] == "12mm"
    assert body["error_state"] is None
