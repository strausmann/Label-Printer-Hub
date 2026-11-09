"""A stale or unpolled cached status is reported as unknown, with its age (#227)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import app.models  # noqa: F401
import httpx
import pytest
import pytest_asyncio
from app.api.dependencies.printer_runtime import get_printer_runtime
from app.models.printer import Printer
from app.models.printer_status_cache import PrinterStatusCache
from app.printer_backends.ipp.client import IppClient
from app.services.event_bus import EventBus
from app.services.producers.ipp_status_producer import IppPrinterState, IppStatusProducer
from app.services.sse_snapshot import build_snapshot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.helpers.fake_ipp_printer import FAKE_URI, FailingTransport, FakeIppPrinter
from tests.helpers.fake_printer_runtime import FakeRuntime

TAPE_PARSED = {
    "online": True,
    "loaded_tape_mm": 62,
    "hr_printer_status": "idle",
    "error_flags": ["cover_open"],
}


@pytest.fixture(autouse=True)
def _trust_legacy_pangolin_user(monkeypatch: pytest.MonkeyPatch):
    from app.config import get_settings

    monkeypatch.setenv("PRINTER_HUB_TRUST_LEGACY_PANGOLIN_USER", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def api(async_session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator:
    from app.api.routes.printers import router
    from app.db.session import get_session
    from fastapi import FastAPI

    async with async_session_factory() as session:
        app = FastAPI()
        app.include_router(router)

        async def _override() -> AsyncIterator[AsyncSession]:
            yield session

        app.dependency_overrides[get_session] = _override
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://t",
            headers={"X-Pangolin-User": "tester"},
        ) as c:
            yield c, app, async_session_factory


async def _printer(factory, *, backend: str = "mock", connection: dict | None = None) -> UUID:
    async with factory() as s:
        p = Printer(
            name="p",
            slug="p",
            model="x",
            backend=backend,
            connection=connection or {"host": "127.0.0.1"},
        )
        s.add(p)
        await s.commit()
        return p.id


async def _cache_row(factory, pid: UUID, *, age_s: float, parsed: dict | None = None) -> None:
    stamp = datetime.now(UTC) - timedelta(seconds=age_s)
    async with factory() as s:
        s.add(
            PrinterStatusCache(
                printer_id=pid, parsed=parsed or TAPE_PARSED, captured_at=stamp, updated_at=stamp
            )
        )
        await s.commit()


async def _status(client, pid: UUID) -> dict:
    r = await client.get(f"/api/v1/printers/{pid}/status")
    assert r.status_code == 200
    return r.json()


async def test_status_older_than_bound_is_stale(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _cache_row(factory, pid, age_s=12_349_795)
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    body = await _status(client, pid)
    assert body["online"] is None
    assert body["stale"] is True
    assert body["polled"] is True
    assert body["tape_loaded"] is None
    assert body["error_state"] is None
    assert body["last_probe_age_s"] >= 12_349_795
    assert body["captured_at"] is not None
    assert "12349795" not in body["note"] and "90" in body["note"]


async def test_fresh_status_is_not_stale(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _cache_row(factory, pid, age_s=10)
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    body = await _status(client, pid)
    assert body["stale"] is False
    assert body["online"] is True
    assert body["tape_loaded"] == "62mm"


async def test_unpolled_printer_reports_polled_false(api) -> None:
    client, app, factory = api
    pid = await _printer(factory, connection={"host": "127.0.0.1", "snmp": {"discover": False}})
    await _cache_row(factory, pid, age_s=5)
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime(set())
    body = await _status(client, pid)
    assert body["polled"] is False
    assert body["online"] is None
    assert body["tape_loaded"] is None
    assert body["note"] == "Not polled"


async def test_no_runtime_reports_unpolled(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _cache_row(factory, pid, age_s=5)
    assert getattr(app.state, "printer_runtime", None) is None
    body = await _status(client, pid)
    assert body["polled"] is False
    assert body["online"] is None


async def test_future_updated_at_is_stale(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _cache_row(factory, pid, age_s=-3600)
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    body = await _status(client, pid)
    assert body["stale"] is True
    assert body["online"] is None


async def test_stale_page_printer_drops_markers_and_trays(api) -> None:
    client, app, factory = api
    pid = await _printer(factory, backend="ipp", connection={"uri": FAKE_URI})
    fake = FakeIppPrinter(
        reasons=["toner-low-warning"],
        markers=[{"name": "Black Toner", "color": "#000000", "level": 15, "type": "toner"}],
    )
    producer = IppStatusProducer(
        bus=EventBus(),
        printer_id=pid,
        client=IppClient(FAKE_URI, transport=httpx.ASGITransport(app=fake)),
        session_factory=factory,
        state=IppPrinterState(),
        pause_control=None,
        interval_s=30,
    )
    await producer.probe_once()
    await producer.stop()
    async with factory() as s:
        row = await s.get(PrinterStatusCache, pid)
        stamp = datetime.now(UTC) - timedelta(days=2)
        row.updated_at = stamp
        row.captured_at = stamp
        await s.commit()
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    body = await _status(client, pid)
    assert body["kind"] == "page"
    assert body["stale"] is True
    assert body["online"] is None
    assert body["markers"] is None and body["state_reasons"] is None
    assert body["printer_state"] is None and body["jobs_ahead"] is None


async def test_offline_ipp_write_refreshes_updated_at(api) -> None:
    client, app, factory = api
    pid = await _printer(factory, backend="ipp", connection={"uri": FAKE_URI})
    fake = FakeIppPrinter()
    producer = IppStatusProducer(
        bus=EventBus(),
        printer_id=pid,
        client=IppClient(
            FAKE_URI,
            transport=FailingTransport(
                httpx.ASGITransport(app=fake), "Get-Printer-Attributes", httpx.ConnectError
            ),
        ),
        session_factory=factory,
        state=IppPrinterState(),
        pause_control=None,
        interval_s=30,
    )
    assert await producer.probe_once() is None
    async with factory() as s:
        first = (await s.get(PrinterStatusCache, pid)).updated_at
    await asyncio.sleep(0.05)
    assert await producer.probe_once() is None  # identical offline write: no column changes
    async with factory() as s:
        second = (await s.get(PrinterStatusCache, pid)).updated_at
    await producer.stop()
    assert second > first
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    body = await _status(client, pid)
    assert body["stale"] is False
    assert body["online"] is False


async def test_snapshot_omits_stale_status(api) -> None:
    _client, _app, factory = api
    pid = await _printer(factory)
    await _cache_row(factory, pid, age_s=12_349_795)
    async with factory() as s:
        frames = await build_snapshot(s, pid)
    assert [f["type"] for f in frames] == ["printer.status"]
    assert frames[0]["data"]["online"] is None
    assert frames[0]["data"]["stale"] is True
    assert "printer.tape_changed" not in [f["type"] for f in frames]


async def test_snapshot_keeps_fresh_status(api) -> None:
    _client, _app, factory = api
    pid = await _printer(factory)
    await _cache_row(factory, pid, age_s=5)
    async with factory() as s:
        frames = await build_snapshot(s, pid)
    assert [f["type"] for f in frames] == ["printer.status", "printer.tape_changed"]
    assert frames[0]["data"]["online"] is True


async def test_snapshot_omits_unpolled_status(api) -> None:
    _client, _app, factory = api
    pid = await _printer(factory)
    await _cache_row(factory, pid, age_s=5)
    async with factory() as s:
        frames = await build_snapshot(s, pid, runtime=FakeRuntime(set()))
    assert [f["type"] for f in frames] == ["printer.status"]
    assert frames[0]["data"]["online"] is None


OFFLINE_PAGE = {"online": False, "kind": "page", "last_error": "IppUnreachableError"}


async def test_offline_ipp_row_200_s_old_is_not_stale(api) -> None:
    """The IPP producer backs off to 300 s while the printer is down: 200 s is a normal gap."""
    client, app, factory = api
    pid = await _printer(factory, backend="ipp", connection={"uri": FAKE_URI})
    await _cache_row(factory, pid, age_s=200, parsed=OFFLINE_PAGE)
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    body = await _status(client, pid)
    assert body["stale"] is False
    assert body["online"] is False
    assert body["last_error"] == "IppUnreachableError"


async def test_ipp_row_700_s_old_is_stale(api) -> None:
    client, app, factory = api
    pid = await _printer(factory, backend="ipp", connection={"uri": FAKE_URI})
    await _cache_row(factory, pid, age_s=700, parsed=OFFLINE_PAGE)
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    body = await _status(client, pid)
    assert body["stale"] is True
    assert body["online"] is None
    assert body["note"] == "Status older than 600 s"


async def test_tape_row_200_s_old_keeps_the_old_bound(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _cache_row(factory, pid, age_s=200)
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    body = await _status(client, pid)
    assert body["stale"] is True
    assert body["note"] == "Status older than 90 s"


TAPE_BLOCK = {"online": True, "loaded_tape_mm": 12, "media_width_mm": 12, "media_type": "LAMINATED"}


async def test_tape_route_refuses_a_stale_tape(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _cache_row(factory, pid, age_s=12_349_795, parsed=TAPE_BLOCK)
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    r = await client.get(f"/api/v1/printers/{pid}/tape")
    assert r.status_code == 404
    assert r.json()["detail"] == "Status older than 90 s"


async def test_tape_route_refuses_an_unpolled_printer(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _cache_row(factory, pid, age_s=5, parsed=TAPE_BLOCK)
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime(set())
    r = await client.get(f"/api/v1/printers/{pid}/tape")
    assert r.status_code == 404
    assert r.json()["detail"] == "Not polled"


async def test_tape_route_serves_a_fresh_tape(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _cache_row(factory, pid, age_s=5, parsed=TAPE_BLOCK)
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    r = await client.get(f"/api/v1/printers/{pid}/tape")
    assert r.status_code == 200
    assert r.json()["width_mm"] == 12
