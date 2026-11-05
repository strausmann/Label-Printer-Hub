"""REST cancel / queue-clear / retry must act on the live ``PrintQueue`` (issue #184).

Unlike ``test_jobs_routes.py`` (DB-only, no queue on ``app.state``), these tests
wire a real ``PrintQueue`` + ``SQLiteJobStore`` into the app and drive the routes
through an in-loop ASGI client, so the worker's behaviour is part of the assertion:
the printer backend must receive nothing for a cancelled job, and a retried job
must print without a restart.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from app.api.routes.jobs import router as jobs_router
from app.api.routes.printers import router as printers_router
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_print, require_read
from app.db.session import get_session
from app.models.job import Job, JobState
from app.models.printer import Printer
from app.services.job_store_sqlite import SQLiteJobStore
from app.services.layout_engine import LayoutEngine
from app.services.print_queue import PrintQueue
from fastapi import FastAPI
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_PAYLOAD: dict[str, Any] = {
    "label_data": {
        "title": "Test",
        "primary_id": "T-001",
        "qr_payload": "https://example.com",
        "source_app": "manual",
        "secondary": [],
        "items": [],
    },
    "content_type": "qr_two_lines",
    "rendered_tape_mm": 24,
    "tape_mm": 24,
    "options": {"auto_cut": True},
}


class _RecordingPrinter:
    def __init__(self, printer_id: UUID) -> None:
        self.id = printer_id
        self.prints = 0

    async def print_image(self, image: Image.Image, *, tape_mm: int, **options: Any) -> None:
        self.prints += 1


class _Env:
    """Everything one test needs: app, queue, printer double, session factory."""

    def __init__(
        self,
        app: FastAPI,
        queue: PrintQueue,
        printer: _RecordingPrinter,
        factory: async_sessionmaker[AsyncSession],
        store: SQLiteJobStore,
    ) -> None:
        self.app = app
        self.queue = queue
        self.printer = printer
        self.factory = factory
        self.store = store

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://test"
        )

    async def seed_job(self, printer_id: UUID | None = None, *, enqueue: bool = True) -> UUID:
        """Persist a renderable QUEUED row and (by default) hand it to the queue."""
        job = Job(printer_id=printer_id or self.printer.id, payload=dict(_PAYLOAD))
        await self.store.save_queued(job)
        if enqueue:
            # Same hand-off as PrintService.submit_print_job: row first, then queue.
            await self.queue.submit_with_id(
                job.id, job.printer_id, Image.new("1", (300, 76)), tape_mm=24
            )
        return job.id

    async def wait_db_state(self, job_id: UUID, expected: str) -> None:
        """Poll until the row reaches *expected*.

        ``wait_for_job`` fires when the in-memory job completes; the worker
        persists ``done`` right after, so the row may lag by one DB round-trip.
        """
        for _ in range(100):
            if await self.db_state(job_id) == expected:
                return
            await asyncio.sleep(0.02)
        assert await self.db_state(job_id) == expected

    async def db_state(self, job_id: UUID) -> str:
        async with self.factory() as s:
            row = await s.get(Job, job_id)
            assert row is not None
            return row.state


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def _drain_with_canary(env: _Env) -> None:
    """Wait until the worker has passed everything submitted before this call.

    FIFO per printer: once a canary submitted last has printed, every earlier job
    that was going to print has printed too.  ``sleep(0)`` alone would prove
    nothing, because the print path awaits a thread (image decode).
    """
    canary = await env.seed_job()
    await env.queue.wait_for_job(str(canary), timeout_s=5)


@pytest_asyncio.fixture
async def env(async_session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[_Env]:
    printer_id = uuid4()
    async with async_session_factory() as s:
        s.add(
            Printer(
                id=printer_id,
                name="p",
                slug="p",
                model="pt-series",
                backend="ptouch",
                connection={"host": "198.51.100.10", "port": 9100},
            )
        )
        await s.commit()

    printer = _RecordingPrinter(printer_id)
    store = SQLiteJobStore(async_session_factory)
    queue = PrintQueue([printer], store=store, engine=LayoutEngine())
    await queue.start()

    app = FastAPI()
    app.include_router(jobs_router)
    app.include_router(printers_router)
    app.state.print_queue = queue

    async def _session() -> AsyncIterator[AsyncSession]:
        async with async_session_factory() as s:
            yield s

    auth = AuthContext(source="api-key", scope="admin", api_key_id=uuid4(), ip="127.0.0.1")
    for dep in (require_read, require_print):
        app.dependency_overrides[dep] = lambda _c=auth: _c
    app.dependency_overrides[get_session] = _session

    yield _Env(app, queue, printer, async_session_factory, store)
    await queue.stop()


async def _hold(env: _Env) -> None:
    await env.queue.pause_printer(env.printer.id, reason="user", source="user")


@pytest.mark.asyncio
async def test_cancel_route_stops_waiting_job_from_printing(env: _Env) -> None:
    await _hold(env)
    job_id = await env.seed_job()
    await _settle()

    async with env.client() as c:
        r = await c.post(f"/api/jobs/{job_id}/cancel")
    assert r.status_code == 200
    assert r.json()["state"] == JobState.CANCELLED.value

    await env.queue.resume_printer(env.printer.id)
    await _drain_with_canary(env)
    assert env.printer.prints == 1  # the canary only
    assert await env.db_state(job_id) == JobState.CANCELLED.value


@pytest.mark.asyncio
async def test_cancel_route_unknown_to_queue_falls_back_to_db(env: _Env) -> None:
    """A row the queue never saw (e.g. webhook-created) is still cancelled in the DB."""
    job_id = await env.seed_job(enqueue=False)
    async with env.client() as c:
        r = await c.post(f"/api/jobs/{job_id}/cancel")
    assert r.status_code == 200
    assert await env.db_state(job_id) == JobState.CANCELLED.value


@pytest.mark.asyncio
async def test_cancel_route_printing_job_returns_409(env: _Env) -> None:
    gate = asyncio.Event()
    entered = asyncio.Event()

    async def _slow(image: Image.Image, *, tape_mm: int, **options: Any) -> None:
        env.printer.prints += 1
        entered.set()
        await gate.wait()

    env.printer.print_image = _slow  # type: ignore[method-assign]
    job_id = await env.seed_job()
    await asyncio.wait_for(entered.wait(), timeout=5)

    async with env.client() as c:
        r = await c.post(f"/api/jobs/{job_id}/cancel")
    assert r.status_code == 409

    gate.set()
    await env.queue.wait_for_job(str(job_id), timeout_s=5)
    await env.wait_db_state(job_id, JobState.DONE.value)


@pytest.mark.asyncio
async def test_clear_route_stops_all_waiting_jobs_from_printing(env: _Env) -> None:
    await _hold(env)
    ids = [await env.seed_job() for _ in range(3)]
    await _settle()

    async with env.client() as c:
        r = await c.post(f"/api/printers/{env.printer.id}/queue/clear")
    assert r.status_code == 204

    await env.queue.resume_printer(env.printer.id)
    await _drain_with_canary(env)
    assert env.printer.prints == 1  # the canary only
    for job_id in ids:
        assert await env.db_state(job_id) == JobState.CANCELLED.value


@pytest.mark.asyncio
async def test_retry_route_prints_new_job_without_restart(env: _Env) -> None:
    failed = Job(printer_id=env.printer.id, payload=dict(_PAYLOAD), state=JobState.FAILED.value)
    async with env.factory() as s:
        s.add(failed)
        await s.commit()

    async with env.client() as c:
        r = await c.post(f"/api/jobs/{failed.id}/retry")
    assert r.status_code == 201
    new_id = r.json()["id"]
    assert new_id != str(failed.id)

    await env.queue.wait_for_job(new_id, timeout_s=5)
    assert env.printer.prints == 1
    await env.wait_db_state(UUID(new_id), JobState.DONE.value)
    assert await env.db_state(failed.id) == JobState.FAILED.value


@pytest.mark.asyncio
async def test_retry_route_unrenderable_payload_is_rejected_and_not_left_queued(
    env: _Env,
) -> None:
    webhook_job = Job(
        printer_id=env.printer.id,
        template_key="spoolman/1",
        payload={"label_title": "x"},
        state=JobState.FAILED.value,
    )
    async with env.factory() as s:
        s.add(webhook_job)
        await s.commit()

    async with env.client() as c:
        r = await c.post(f"/api/jobs/{webhook_job.id}/retry")
    assert r.status_code == 422

    await _drain_with_canary(env)
    assert env.printer.prints == 1  # the canary only
    async with env.factory() as s:
        from sqlmodel import select

        rows = (await s.execute(select(Job))).scalars().all()
    assert not [j for j in rows if j.state == JobState.QUEUED.value]


@pytest.mark.asyncio
async def test_cancel_route_respects_printer_acl(env: _Env) -> None:
    """A key restricted to another printer cannot cancel (or learn about) the job."""
    await _hold(env)
    job_id = await env.seed_job()
    await _settle()

    restricted = AuthContext(
        source="api-key",
        scope="print",
        api_key_id=uuid4(),
        ip="127.0.0.1",
        allowed_printer_ids=[str(uuid4())],
    )
    for dep in (require_read, require_print):
        env.app.dependency_overrides[dep] = lambda _c=restricted: _c

    async with env.client() as c:
        r = await c.post(f"/api/jobs/{job_id}/cancel")
    assert r.status_code == 404
    assert (await env.queue.get(job_id)).state.value == "queued"


@pytest.mark.asyncio
async def test_clear_route_respects_printer_acl(env: _Env) -> None:
    await _hold(env)
    job_id = await env.seed_job()
    await _settle()

    restricted = AuthContext(
        source="api-key",
        scope="print",
        api_key_id=uuid4(),
        ip="127.0.0.1",
        allowed_printer_ids=[str(uuid4())],
    )
    for dep in (require_read, require_print):
        env.app.dependency_overrides[dep] = lambda _c=restricted: _c

    async with env.client() as c:
        r = await c.post(f"/api/printers/{env.printer.id}/queue/clear")
    assert r.status_code == 403
    assert (await env.queue.get(job_id)).state.value == "queued"


@pytest.mark.asyncio
async def test_retry_route_printer_unknown_to_queue_is_rejected_and_not_left_queued(
    env: _Env,
) -> None:
    other_printer = uuid4()
    async with env.factory() as s:
        s.add(
            Printer(
                id=other_printer,
                name="q",
                slug="q",
                model="pt-series",
                backend="ptouch",
                connection={"host": "198.51.100.11", "port": 9100},
            )
        )
        s.add(
            failed := Job(
                printer_id=other_printer, payload=dict(_PAYLOAD), state=JobState.FAILED.value
            )
        )
        await s.commit()

    async with env.client() as c:
        r = await c.post(f"/api/jobs/{failed.id}/retry")
    assert r.status_code == 409

    async with env.factory() as s:
        from sqlmodel import select

        rows = (await s.execute(select(Job))).scalars().all()
    assert not [j for j in rows if j.state == JobState.QUEUED.value]
    assert env.printer.prints == 0


@pytest.mark.asyncio
async def test_clear_route_cancels_untracked_queued_rows_in_db(env: _Env) -> None:
    """Rows the queue never saw (webhook jobs) are still cleared via the DB."""
    untracked = await env.seed_job(enqueue=False)
    async with env.client() as c:
        r = await c.post(f"/api/printers/{env.printer.id}/queue/clear")
    assert r.status_code == 204
    assert await env.db_state(untracked) == JobState.CANCELLED.value


class _SerialiseGate:
    """Hold ``_serialize_image_to_png`` open so cancel/clear can land mid-submit."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import threading

        from app.services import print_queue as pq_module

        self.entered = threading.Event()
        self.release = threading.Event()
        real = pq_module._serialize_image_to_png

        def _gated(image: Image.Image) -> bytes:
            self.entered.set()
            self.release.wait(timeout=10)
            return real(image)

        monkeypatch.setattr(pq_module, "_serialize_image_to_png", _gated)

    async def wait_entered(self) -> None:
        for _ in range(500):
            if self.entered.is_set():
                return
            await asyncio.sleep(0.01)
        raise AssertionError("serialisation never started")


async def _start_submit_and_hold(env: _Env, gate: _SerialiseGate) -> tuple[UUID, asyncio.Task[Any]]:
    """Persist a row and start ``submit_with_id`` (as PrintService does), stuck in serialisation."""
    job = Job(printer_id=env.printer.id, payload=dict(_PAYLOAD))
    await env.store.save_queued(job)
    task = asyncio.create_task(
        env.queue.submit_with_id(job.id, job.printer_id, Image.new("1", (300, 76)), tape_mm=24)
    )
    await gate.wait_entered()
    return job.id, task


@pytest.mark.asyncio
async def test_cancel_route_during_submit_serialisation_is_never_printed(
    env: _Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = _SerialiseGate(monkeypatch)
    try:
        job_id, submit = await _start_submit_and_hold(env, gate)
        async with env.client() as c:
            r = await c.post(f"/api/jobs/{job_id}/cancel")
        assert r.status_code == 200
        assert r.json()["state"] == JobState.CANCELLED.value

        gate.release.set()
        await submit
        await _drain_with_canary(env)
        assert env.printer.prints == 1  # the canary only
        assert await env.db_state(job_id) == JobState.CANCELLED.value
    finally:
        gate.release.set()


@pytest.mark.asyncio
async def test_clear_route_during_submit_serialisation_is_never_printed(
    env: _Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = _SerialiseGate(monkeypatch)
    try:
        job_id, submit = await _start_submit_and_hold(env, gate)
        async with env.client() as c:
            r = await c.post(f"/api/printers/{env.printer.id}/queue/clear")
        assert r.status_code == 204

        gate.release.set()
        await submit
        await _drain_with_canary(env)
        assert env.printer.prints == 1  # the canary only
        assert await env.db_state(job_id) == JobState.CANCELLED.value
    finally:
        gate.release.set()
