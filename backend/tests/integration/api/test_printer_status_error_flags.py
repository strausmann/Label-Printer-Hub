# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The tape status lists its raw error flags for the web UI to put into words (#376)."""

from __future__ import annotations

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
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.helpers.fake_printer_runtime import FakeRuntime


def _tape(flags: list[str], *, online: bool = True) -> dict:
    return {
        "online": online,
        "loaded_tape_mm": 12,
        "hr_printer_status": "idle",
        "error_flags": flags,
    }


@pytest.fixture(autouse=True)
def _trust_legacy_pangolin_user(monkeypatch: pytest.MonkeyPatch):
    from app.config import get_settings

    monkeypatch.setenv("LABELYARD_TRUST_LEGACY_PANGOLIN_USER", "true")
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


async def _cache_row(factory, pid: UUID, *, age_s: float, parsed: dict) -> None:
    stamp = datetime.now(UTC) - timedelta(seconds=age_s)
    async with factory() as s:
        s.add(
            PrinterStatusCache(printer_id=pid, parsed=parsed, captured_at=stamp, updated_at=stamp)
        )
        await s.commit()


async def _status(client, pid: UUID) -> dict:
    r = await client.get(f"/api/v1/printers/{pid}/status")
    assert r.status_code == 200
    return r.json()


async def test_fresh_tape_status_lists_the_flags(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _cache_row(factory, pid, age_s=5, parsed=_tape(["doorOpen", "noPaper"]))
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    body = await _status(client, pid)
    assert body["error_flags"] == ["doorOpen", "noPaper"]
    assert body["error_state"] == "doorOpen, noPaper"


async def test_no_flags_is_an_empty_list(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _cache_row(factory, pid, age_s=5, parsed=_tape([]))
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    body = await _status(client, pid)
    assert body["error_flags"] == []
    assert body["error_state"] is None


async def test_offline_reading_lists_no_flags(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _cache_row(factory, pid, age_s=5, parsed=_tape(["doorOpen"], online=False))
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    body = await _status(client, pid)
    assert body["online"] is False
    assert body["error_flags"] == []


async def test_stale_status_lists_no_flags(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _cache_row(factory, pid, age_s=12_349_795, parsed=_tape(["doorOpen"]))
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    body = await _status(client, pid)
    assert body["stale"] is True
    assert body["error_flags"] == []


async def test_unpolled_status_lists_no_flags(api) -> None:
    client, app, factory = api
    pid = await _printer(factory, connection={"host": "127.0.0.1", "snmp": {"discover": False}})
    await _cache_row(factory, pid, age_s=5, parsed=_tape(["doorOpen"]))
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime(set())
    body = await _status(client, pid)
    assert body["polled"] is False
    assert body["error_flags"] == []


async def test_page_printer_lists_no_flags(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _cache_row(
        factory,
        pid,
        age_s=5,
        parsed={"kind": "page", "online": True, "error_flags": ["doorOpen"]},
    )
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    body = await _status(client, pid)
    assert body["kind"] == "page"
    assert body["error_flags"] == []
