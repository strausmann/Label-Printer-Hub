"""E-11: automatic and manual pauses are visible on /api/printers with a reason.

Decision 1 (sync): the manual API pause must also pause the queue worker and the
API resume must release an auto-paused worker, otherwise the two notions drift.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import app.models  # noqa: F401 — registers all SQLModel tables with metadata
import pytest
import pytest_asyncio
from app.api.routes.printers import router
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_admin, require_print, require_read
from app.db.engine import _apply_pragmas
from app.db.session import get_session
from app.models.printer import Printer
from app.models.printer_state import PrinterState
from app.printer_backends.exceptions import PrinterCoverOpenError, TapeEmptyError
from app.services.event_bus import EventBus
from app.services.print_queue import PrintQueue
from app.services.producers.printer_pause_producer import PrinterPauseProducer
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(engine.sync_engine, "connect", _apply_pragmas)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


class _Backend:
    """Mock backend: raises *error* until ``fail`` is cleared."""

    def __init__(self, printer_id: UUID, error: Exception) -> None:
        self.id = printer_id
        self._error = error
        self.fail = True
        self.printed = 0

    async def print_image(self, image: Any, *, tape_mm: int, **_o: Any) -> None:
        if self.fail:
            raise self._error
        self.printed += 1


async def _printer(session: AsyncSession) -> Printer:
    p = Printer(
        name="p",
        model="pt-series",
        backend="ptouch",
        connection={"host": "198.51.100.10", "port": 9100},
    )
    session.add(p)
    await session.commit()
    await session.refresh(p)
    session.add(PrinterState(printer_id=p.id, paused=False))
    await session.commit()
    return p


def _app(session: AsyncSession, queue: PrintQueue | None) -> FastAPI:
    app = FastAPI()
    app.include_router(router)

    async def _override() -> AsyncIterator[AsyncSession]:
        yield session

    from uuid import uuid4

    ctx = AuthContext(source="api-key", scope="admin", api_key_id=uuid4(), ip="127.0.0.1")
    for dep in (require_read, require_print, require_admin):
        app.dependency_overrides[dep] = lambda _c=ctx: _c
    app.dependency_overrides[get_session] = _override
    if queue is not None:
        app.state.print_queue = queue
    return app


async def _setup(session: AsyncSession, error: Exception):
    printer = await _printer(session)
    backend = _Backend(printer.id, error)
    bus = EventBus()
    producer = PrinterPauseProducer(bus)
    queue = PrintQueue([backend], on_pause_change=producer.handle_change)
    await queue.start()
    sub = bus.subscribe(f"printer:{printer.id}:state", "t")
    return printer, backend, queue, sub


async def _fail_one_job(queue: PrintQueue, printer_id: UUID) -> None:
    job_id = await queue.submit(printer_id, Image.new("1", (200, 128)), tape_mm=12)
    await queue.wait_for_job(job_id, timeout_s=2.0)


@pytest.mark.asyncio
async def test_auto_pause_is_visible_with_reason_and_event(session) -> None:
    printer, _backend, queue, sub = await _setup(session, TapeEmptyError())
    try:
        await _fail_one_job(queue, printer.id)
        client = TestClient(_app(session, queue))

        for url in ("/api/printers", f"/api/printers/{printer.id}"):
            body = client.get(url).json()
            row = body[0] if isinstance(body, list) else body
            assert row["paused"] is True
            assert row["pause"]["source"] == "printer_error"
            assert row["pause"]["reason_code"] == "tape_empty"
            assert row["pause"]["since"].endswith("Z") or "+" in row["pause"]["since"]

        ev = sub.get_nowait()
        assert ev.event_type == "printer.status"
        assert ev.data["paused"] is True
        assert ev.data["pause"]["reason_code"] == "tape_empty"
    finally:
        await queue.stop(timeout_s=2.0)


@pytest.mark.asyncio
async def test_api_resume_releases_auto_paused_worker_and_next_job_prints(session) -> None:
    printer, backend, queue, sub = await _setup(session, PrinterCoverOpenError())
    try:
        await _fail_one_job(queue, printer.id)
        sub.get_nowait()  # pause event
        client = TestClient(_app(session, queue))

        backend.fail = False
        assert client.post(f"/api/printers/{printer.id}/resume").status_code == 204

        row = client.get(f"/api/printers/{printer.id}").json()
        assert row["paused"] is False
        assert row["pause"] is None
        assert queue.is_paused(printer.id) is False

        ev = sub.get_nowait()
        assert ev.event_type == "printer.status"
        assert ev.data["paused"] is False
        assert ev.data["pause"] is None

        job_id = await queue.submit(printer.id, Image.new("1", (200, 128)), tape_mm=12)
        job = await queue.wait_for_job(job_id, timeout_s=2.0)
        assert job.state.value == "completed"
        assert backend.printed == 1
    finally:
        await queue.stop(timeout_s=2.0)


@pytest.mark.asyncio
async def test_manual_pause_pauses_worker_with_user_source(session) -> None:
    printer, _backend, queue, sub = await _setup(session, TapeEmptyError())
    try:
        client = TestClient(_app(session, queue))
        assert client.post(f"/api/printers/{printer.id}/pause").status_code == 204

        assert queue.is_paused(printer.id) is True
        row = client.get(f"/api/printers/{printer.id}").json()
        assert row["paused"] is True
        assert row["pause"]["source"] == "user"
        assert row["pause"]["reason_code"] == "user"
        assert sub.get_nowait().data["pause"]["source"] == "user"
    finally:
        await queue.stop(timeout_s=2.0)


@pytest.mark.asyncio
async def test_worker_state_not_paused_means_not_paused(session) -> None:
    """Counter-test anchor: the field really derives from the worker state."""
    printer, _backend, queue, _sub = await _setup(session, TapeEmptyError())
    try:
        await _fail_one_job(queue, printer.id)
        client = TestClient(_app(session, queue))
        assert client.get(f"/api/printers/{printer.id}").json()["paused"] is True

        queue.is_paused = lambda _id: False  # type: ignore[method-assign]
        queue.pause_info = lambda _id: None  # type: ignore[method-assign]
        row = client.get(f"/api/printers/{printer.id}").json()
        assert row["paused"] is False
        assert row["pause"] is None
    finally:
        await queue.stop(timeout_s=2.0)


@pytest.mark.asyncio
async def test_without_queue_falls_back_to_db_flag(session) -> None:
    printer = await _printer(session)
    client = TestClient(_app(session, None))
    assert client.post(f"/api/printers/{printer.id}/pause").status_code == 204
    row = client.get(f"/api/printers/{printer.id}").json()
    assert row["paused"] is True
    assert row["pause"] is None
