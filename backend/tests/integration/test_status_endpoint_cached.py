"""Phase 7b Cluster 1f — /api/v1/printers/{id}/status reads cache, never blocks."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import NoReturn

import pytest
import pytest_asyncio

from tests.helpers.fake_printer_runtime import FakeRuntime


@pytest.fixture(autouse=True)
def _trust_legacy_pangolin_user(monkeypatch: pytest.MonkeyPatch):
    """These tests authenticate with the legacy X-Pangolin-User header, which
    counts only with the D10 opt-in (default off)."""
    from app.config import get_settings

    monkeypatch.setenv("PRINTER_HUB_TRUST_LEGACY_PANGOLIN_USER", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Every printer inserted here counts as polled: the status route needs a runtime to say so.
_RUNTIME = FakeRuntime()


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
        _RUNTIME.polled.add(p.id)
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

    from app.api.dependencies.printer_runtime import get_printer_runtime
    from app.api.routes.printers import router
    from app.db.session import get_session
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession

    app = FastAPI()
    app.include_router(router)

    async def _override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override
    app.dependency_overrides[get_printer_runtime] = lambda: _RUNTIME
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
    resp = await client.get(f"/api/v1/printers/{pid}/status", headers={"X-Pangolin-User": "test"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["online"] is None
    assert body["note"] is not None
    assert "no probe yet" in body["note"].lower()


@pytest.fixture
def printer_contact_guard(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record (and refuse) every way the request could reach a printer.

    Covers the named probe functions (SNMP preflight/identity, the ESC i S probe in the
    printers route) and, underneath them, every outgoing socket: blocking ``connect`` and
    the event loop's TCP/UDP endpoints (pysnmp and the IPP client go through those). The
    test database is SQLite, so a correct request opens no socket at all.
    """
    import asyncio.base_events
    import socket

    import app.printer_backends.snmp_helper as snmp_helper

    calls: list[str] = []

    def _refuse(name: str) -> tuple[Callable[..., NoReturn], Callable[..., Awaitable[NoReturn]]]:
        def _sync(*_args: object, **_kwargs: object) -> NoReturn:
            calls.append(name)
            raise OSError(f"test: {name} must not be called by the status endpoint")

        async def _async(*_args: object, **_kwargs: object) -> NoReturn:
            calls.append(name)
            raise OSError(f"test: {name} must not be called by the status endpoint")

        return _sync, _async

    monkeypatch.setattr(socket.socket, "connect", _refuse("socket.connect")[0])
    monkeypatch.setattr(
        asyncio.base_events.BaseEventLoop, "create_connection", _refuse("loop.create_connection")[1]
    )
    monkeypatch.setattr(
        asyncio.base_events.BaseEventLoop,
        "create_datagram_endpoint",
        _refuse("loop.create_datagram_endpoint")[1],
    )
    monkeypatch.setattr(snmp_helper, "query_preflight", _refuse("query_preflight")[1])
    monkeypatch.setattr(snmp_helper, "query_identity", _refuse("query_identity")[1])
    return calls


async def test_status_endpoint_answers_from_cache_without_contacting_the_printer(
    api_client_with_warm_cache, printer_contact_guard
):
    """The endpoint answers from the cache and never probes the printer during the request.

    This used to be a wall-clock check (``< 100 ms``), which went red on a slow gate run
    without any defect. What it is meant to prove is "no live probe on the request path";
    that is checked by effect: no probe function is called and no socket is opened.
    """
    client, pid = api_client_with_warm_cache
    resp = await client.get(f"/api/v1/printers/{pid}/status", headers={"X-Pangolin-User": "test"})
    assert resp.status_code == 200
    assert printer_contact_guard == []
    body = resp.json()
    # The values come from the cache row, not from a probe.
    assert body["online"] is True
    assert body["tape_loaded"] == "12mm"


async def test_status_endpoint_returns_404_for_unknown_printer(
    api_client_with_printer_no_cache,
):
    """Unknown printer UUID returns 404."""
    from uuid import uuid4

    client, _ = api_client_with_printer_no_cache
    resp = await client.get(
        f"/api/v1/printers/{uuid4()}/status", headers={"X-Pangolin-User": "test"}
    )
    assert resp.status_code == 404


async def test_status_endpoint_returns_cached_tape_data(api_client_with_warm_cache):
    """Cached loaded_tape_mm + error_flags surface as PrinterStatus.tape_loaded
    and PrinterStatus.error_state respectively (bot-review finding on PR #75)."""
    client, pid = api_client_with_warm_cache
    resp = await client.get(f"/api/v1/printers/{pid}/status", headers={"X-Pangolin-User": "test"})
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
