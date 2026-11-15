# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The status names the trays the newest sheet and calibration page jobs used (#344)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import app.models  # noqa: F401
import httpx
import pytest
import pytest_asyncio
from app.api.dependencies.printer_runtime import get_printer_runtime
from app.models.job import Job
from app.models.printer import Printer
from app.models.printer_status_cache import PrinterStatusCache
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.helpers.fake_printer_runtime import FakeRuntime

_NOW = datetime.now(UTC).replace(microsecond=0)
_PAGE_PARSED = {"kind": "page", "online": True, "printer_state": "idle"}


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


async def _printer(factory, *, backend: str = "ipp") -> UUID:
    async with factory() as s:
        p = Printer(
            name=f"p-{uuid4().hex[:6]}", slug=f"p-{uuid4().hex[:6]}", model="x", backend=backend,
            connection={"host": "127.0.0.1"},
        )  # fmt: skip
        s.add(p)
        await s.commit()
        return p.id


async def _job(
    factory,
    pid: UUID,
    kind: str,
    tray: str,
    *,
    age_min: int = 0,
    state: str = "done",
    payload: dict | None = None,
) -> datetime:
    at = _NOW - timedelta(minutes=age_min)
    async with factory() as s:
        s.add(
            Job(
                printer_id=pid,
                state=state,
                payload=payload if payload is not None else {"kind": kind, "tray": tray},
                created_at=at,
                updated_at=at,
            )
        )
        await s.commit()
    return at


async def _cache(factory, pid: UUID, *, age_s: float = 5) -> None:
    stamp = datetime.now(UTC) - timedelta(seconds=age_s)
    async with factory() as s:
        s.add(
            PrinterStatusCache(
                printer_id=pid, parsed=_PAGE_PARSED, captured_at=stamp, updated_at=stamp
            )
        )
        await s.commit()


async def _status(client, pid: UUID) -> dict:
    r = await client.get(f"/api/v1/printers/{pid}/status")
    assert r.status_code == 200
    return r.json()


async def test_newest_sheet_job_tray_is_reported(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _cache(factory, pid)
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    await _job(factory, pid, "sheet_page", "tray-1", age_min=30)
    await _job(factory, pid, "sheet_page", "manual", age_min=1)
    body = await _status(client, pid)
    assert body["last_sheet_tray"] == "manual"


@pytest.mark.parametrize("state", ["failed", "cancelled", "failed_restart"])
async def test_failed_and_cancelled_sheet_jobs_do_not_count(api, state: str) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _cache(factory, pid)
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    await _job(factory, pid, "sheet_page", "tray-1", age_min=30)
    await _job(factory, pid, "sheet_page", "manual", age_min=1, state=state)
    await _job(factory, pid, "calibration_page", "auto", age_min=1, state=state)
    body = await _status(client, pid)
    assert body["last_sheet_tray"] == "tray-1"
    assert body["last_calibration_print"] is None


@pytest.mark.parametrize("state", ["queued", "printing", "done"])
async def test_live_and_finished_jobs_count(api, state: str) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _cache(factory, pid)
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    await _job(factory, pid, "sheet_page", "manual", state=state)
    assert (await _status(client, pid))["last_sheet_tray"] == "manual"


async def test_calibration_jobs_are_not_sheet_trays(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _cache(factory, pid)
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    await _job(factory, pid, "sheet_page", "tray-1", age_min=60)
    at = await _job(factory, pid, "calibration_page", "manual", age_min=2)
    body = await _status(client, pid)
    assert body["last_sheet_tray"] == "tray-1"
    assert body["last_calibration_print"]["tray"] == "manual"
    assert body["last_calibration_print"]["at"].endswith("Z")
    parsed = datetime.fromisoformat(body["last_calibration_print"]["at"].replace("Z", "+00:00"))
    assert parsed == at


async def test_trays_are_reported_when_never_probed(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)  # no cache row
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    await _job(factory, pid, "sheet_page", "tray-1")
    body = await _status(client, pid)
    assert body["captured_at"] is None
    assert body["last_sheet_tray"] == "tray-1"


async def test_trays_are_reported_when_not_polled(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _cache(factory, pid)
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime(set())
    await _job(factory, pid, "sheet_page", "tray-1")
    body = await _status(client, pid)
    assert body["polled"] is False
    assert body["last_sheet_tray"] == "tray-1"


async def test_trays_are_reported_when_the_status_is_stale(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _cache(factory, pid, age_s=12_000_000)
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    await _job(factory, pid, "sheet_page", "tray-1")
    body = await _status(client, pid)
    assert body["stale"] is True
    assert body["last_sheet_tray"] == "tray-1"


async def test_one_statement_reads_both_fields(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _cache(factory, pid)
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    await _job(factory, pid, "sheet_page", "tray-1")
    await _job(factory, pid, "calibration_page", "manual")
    seen: list[str] = []

    async with factory() as s:
        engine = s.bind.sync_engine  # type: ignore[union-attr]

    def _count(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "FROM jobs" in statement:
            seen.append(statement)

    event.listen(engine, "before_cursor_execute", _count)
    try:
        await _status(client, pid)
    finally:
        event.remove(engine, "before_cursor_execute", _count)
    assert len(seen) == 1, seen


async def test_other_printers_jobs_do_not_count(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    other = await _printer(factory)
    await _cache(factory, pid)
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    await _job(factory, other, "sheet_page", "manual")
    await _job(factory, other, "calibration_page", "manual")
    body = await _status(client, pid)
    assert body["last_sheet_tray"] is None
    assert body["last_calibration_print"] is None


async def test_no_jobs_reports_null(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _cache(factory, pid)
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    body = await _status(client, pid)
    assert body["last_sheet_tray"] is None
    assert body["last_calibration_print"] is None


async def test_tape_printer_reports_null(api) -> None:
    client, app, factory = api
    pid = await _printer(factory, backend="mock")
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    await _job(factory, pid, "sheet_page", "tray-1")
    body = await _status(client, pid)
    assert body["last_sheet_tray"] is None
    assert body["last_calibration_print"] is None


async def test_print_key_sees_the_tray_of_jobs_it_does_not_own(api) -> None:
    """R-344-1: the tray is a property of the printer's recent use, not of the caller's jobs."""
    client, app, factory = api
    pid = await _printer(factory)
    await _cache(factory, pid)
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    async with factory() as s:
        s.add(
            Job(printer_id=pid, state="done", api_key_id=uuid4(),
                payload={"kind": "sheet_page", "tray": "manual"})
        )  # fmt: skip
        await s.commit()
    assert (await _status(client, pid))["last_sheet_tray"] == "manual"


async def test_a_deferred_grocy_job_without_kind_does_not_count(api) -> None:
    client, app, factory = api
    pid = await _printer(factory)
    await _cache(factory, pid)
    app.dependency_overrides[get_printer_runtime] = lambda: FakeRuntime({pid})
    await _job(
        factory, pid, "", "",
        payload={"deferred": True, "deferred_kind": "sheet_page", "tray": "manual"},
    )  # fmt: skip
    assert (await _status(client, pid))["last_sheet_tray"] is None
