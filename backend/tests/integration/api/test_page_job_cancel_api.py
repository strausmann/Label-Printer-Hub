"""Cancel, queue-clear and retry routes for page jobs (they go through ``PrintQueue``, #184).

A real ``PrintQueue`` + ``SQLiteJobStore`` with one IPP page printer whose transport is the
fake printer; the routes are driven through an in-loop ASGI client. Waits are bounded.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
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
from app.printer_backends.ipp.client import IppClient
from app.services.event_bus import BusEvent, EventBus
from app.services.job_store_sqlite import SQLiteJobStore
from app.services.page_job_runner import PageJobRunner
from app.services.page_jobs import IppPagePrinter
from app.services.print_queue import PrintQueue
from app.services.producers.ipp_status_producer import IppPrinterState
from app.services.producers.print_queue_producer import PrintQueueProducer
from app.settings_store import SettingsStore
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.helpers.fake_ipp_printer import FAKE_URI, FakeIppPrinter
from tests.helpers.page_jobs import RecordingHandler, payload, registered

TEST_TIMEOUT_S = 10.0


class _Env:
    def __init__(
        self,
        app: FastAPI,
        queue: PrintQueue,
        runner: PageJobRunner,
        fake: FakeIppPrinter,
        printer_id: UUID,
        factory: async_sessionmaker[AsyncSession],
        handler: RecordingHandler,
        events: list[BusEvent],
    ) -> None:
        self.events = events
        self.app = app
        self.queue = queue
        self.runner = runner
        self.fake = fake
        self.printer_id = printer_id
        self.factory = factory
        self.handler = handler

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://t")

    def ops(self, name: str) -> int:
        return sum(1 for r in self.fake.received if r.operation == name)

    async def submit(self, kind: str = "calibration_page") -> UUID:
        return await self.queue.submit_page_job(
            self.printer_id,
            payload(kind),
            api_key_id=None,
            source_ip=None,  # type: ignore[arg-type]
        )

    async def row(self, job_id: UUID) -> Job:
        async with self.factory() as s:
            row = await s.get(Job, job_id)
            assert row is not None
            return row

    async def until(self, predicate: Callable[[], Any]) -> None:
        async with asyncio.timeout(TEST_TIMEOUT_S):
            while True:
                value = predicate()
                if asyncio.iscoroutine(value):
                    value = await value
                if value:
                    return
                await asyncio.sleep(0.01)

    async def wait_state(self, job_id: UUID, state: str) -> None:
        async def _is() -> bool:
            return (await self.row(job_id)).state == state

        await self.until(_is)


@pytest_asyncio.fixture
async def env(async_session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[_Env]:
    with registered(RecordingHandler()) as handler:
        printer_id = uuid4()
        async with async_session_factory() as s:
            s.add(
                Printer(
                    id=printer_id,
                    name="page",
                    slug="page",
                    model="x",
                    backend="ipp",
                    connection={"uri": FAKE_URI},
                )
            )
            await s.commit()
        fake = FakeIppPrinter(job_script=[3])
        client = IppClient(FAKE_URI, transport=httpx.ASGITransport(app=fake))
        page = IppPagePrinter(id=printer_id, client=client, state=IppPrinterState())
        store = SQLiteJobStore(async_session_factory)
        # Every job event the runner emits is published as the real producer builds it.
        bus = EventBus()
        events: list[BusEvent] = []
        producer = PrintQueueProducer(bus)
        real_publish = bus.publish

        def _record(channel: str, event: BusEvent) -> None:
            events.append(event)
            real_publish(channel, event)

        bus.publish = _record  # type: ignore[method-assign]
        runner = PageJobRunner(
            store=store, notify=producer.handle_transition, poll_interval_s=0.01, max_backoff_s=0
        )
        queue = PrintQueue([], store=store, page_printers=[page], page_runner=runner)
        await queue.start()

        app = FastAPI()
        app.include_router(jobs_router)
        app.include_router(printers_router)
        app.state.print_queue = queue
        app.state.settings_store = SettingsStore()  # the sheet page retry reads the language

        async def _session() -> AsyncIterator[AsyncSession]:
            async with async_session_factory() as s:
                yield s

        auth = AuthContext(source="api-key", scope="admin", api_key_id=uuid4(), ip="127.0.0.1")
        for dep in (require_read, require_print):
            app.dependency_overrides[dep] = lambda _c=auth: _c
        app.dependency_overrides[get_session] = _session
        try:
            yield _Env(app, queue, runner, fake, printer_id, async_session_factory, handler, events)
        finally:
            await queue.stop(timeout_s=2)
            await client.aclose()


@pytest.mark.asyncio
async def test_cancel_route_queued_page_job_not_sent(env: _Env) -> None:
    await env.queue.pause_printer(env.printer_id, reason="user", source="user")
    jid = await env.submit()
    async with env.client() as c:
        r = await c.post(f"/api/v1/jobs/{jid}/cancel")
    assert r.status_code == 200, r.text
    assert r.json()["state"] == JobState.CANCELLED.value
    await env.queue.resume_printer(env.printer_id)
    await asyncio.sleep(0.05)
    assert env.ops("Print-Job") == 0
    assert env.handler.ended(jid) == {
        "state": "cancelled",
        "started": False,
        "error_code": "cancelled",
    }


@pytest.mark.asyncio
async def test_cancel_route_held_page_job(env: _Env) -> None:
    env.fake.accepting_jobs = False
    jid = await env.submit()
    await env.until(lambda: env.queue.is_paused(env.printer_id))
    async with env.client() as c:
        r = await c.post(f"/api/v1/jobs/{jid}/cancel")
    assert r.status_code == 200, r.text
    assert r.json()["state"] == JobState.CANCELLED.value
    assert env.ops("Print-Job") == 0
    assert env.handler.ended(jid)["state"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_route_tracked_page_job_sends_cancel_job(env: _Env) -> None:
    jid = await env.submit()
    await env.until(lambda: env.runner.is_tracking(jid))
    async with env.client() as c:
        r = await c.post(f"/api/v1/jobs/{jid}/cancel")
    assert r.status_code == 202, r.text
    assert r.json()["state"] == JobState.PRINTING.value
    assert env.ops("Cancel-Job") == 1
    await env.wait_state(jid, JobState.CANCELLED.value)
    await env.until(lambda: "ended" in env.handler.names(jid))
    assert env.handler.ended(jid) == {
        "state": "cancelled",
        "started": False,
        "error_code": "cancelled",
    }


@pytest.mark.asyncio
async def test_queue_clear_cancels_queued_page_jobs(env: _Env) -> None:
    await env.queue.pause_printer(env.printer_id, reason="user", source="user")
    jobs = [await env.submit(), await env.submit()]
    async with env.client() as c:
        r = await c.post(f"/api/v1/printers/{env.printer_id}/queue/clear")
    assert r.status_code == 204, r.text
    for jid in jobs:
        assert (await env.row(jid)).state == JobState.CANCELLED.value
        assert env.handler.ended(jid)["state"] == "cancelled"
    assert env.ops("Print-Job") == 0


@pytest.mark.asyncio
async def test_retry_route_calibration_page_resubmits(env: _Env) -> None:
    env.fake.print_status = 0x040A
    jid = await env.submit()
    await env.wait_state(jid, JobState.FAILED.value)
    env.fake.print_status = 0
    env.fake.job_script = [9]
    async with env.client() as c:
        r = await c.post(f"/api/v1/jobs/{jid}/retry")
    assert r.status_code == 201, r.text
    new_id = UUID(r.json()["id"])
    assert new_id != jid
    assert r.json()["payload"]["kind"] == "calibration_page"
    await env.wait_state(new_id, JobState.DONE.value)
    await env.until(lambda: "completed" in env.handler.names(new_id))
    assert env.handler.names(new_id) == ["started", "completed"]


@pytest.mark.asyncio
async def test_retry_route_sheet_page_without_a_usable_payload_is_422(env: _Env) -> None:
    """A sheet page goes to the cell-aware retry (Task 9); a stored payload that does not
    describe a sheet cannot be retried and no row is created."""
    env.fake.print_status = 0x040A
    jid = await env.submit("sheet_page")
    await env.wait_state(jid, JobState.FAILED.value)
    async with env.client() as c:
        r = await c.post(f"/api/v1/jobs/{jid}/retry")
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["type"] == "job-not-retryable"
    async with env.factory() as s:
        from sqlalchemy import select

        rows = (await s.execute(select(Job))).scalars().all()
    assert len(rows) == 1  # no new row was created


@pytest.mark.asyncio
async def test_retry_route_tape_payload_on_page_printer_is_409(env: _Env) -> None:
    """A tape row whose printer became a page printer: a clean 409, never a 500."""
    async with env.factory() as s:
        row = Job(
            printer_id=env.printer_id,
            payload={"content_type": "qr_two_lines", "label_data": {}, "rendered_tape_mm": 24},
            state=JobState.FAILED.value,
        )
        s.add(row)
        await s.commit()
        old_id = row.id
    async with env.client() as c:
        r = await c.post(f"/api/v1/jobs/{old_id}/retry")
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error_code"] == "media_kind_mismatch"


def _assert_no_printer_address(raw: str) -> None:
    """The printer's URI and host must not appear anywhere in the raw JSON text."""
    host = FAKE_URI.split("//", 1)[1].split("/", 1)[0]
    assert FAKE_URI not in raw
    assert host not in raw
    assert "ipp://" not in raw


@pytest.mark.asyncio
async def test_job_responses_and_events_never_carry_the_printer_address(env: _Env) -> None:
    """Spec 14/18: the IPP URI is admin-only. A read key must not get it back through jobs.

    Raw-text assertions on purpose: a parsed check would miss a renamed field.
    """
    jid = await env.submit()
    await env.until(lambda: env.runner.is_tracking(jid))
    async with env.client() as c:
        tracked = await c.get(f"/api/v1/jobs/{jid}")
        cancel = await c.post(f"/api/v1/jobs/{jid}/cancel")
    assert cancel.status_code == 202, cancel.text
    await env.wait_state(jid, JobState.CANCELLED.value)
    async with env.client() as c:
        detail = await c.get(f"/api/v1/jobs/{jid}")
    env.fake.print_status = 0x040A
    failed = await env.submit()
    await env.wait_state(failed, JobState.FAILED.value)
    env.fake.print_status = 0
    env.fake.job_script = [9]
    async with env.client() as c:
        retry = await c.post(f"/api/v1/jobs/{failed}/retry")
    assert retry.status_code == 201, retry.text
    await env.wait_state(UUID(retry.json()["id"]), JobState.DONE.value)
    async with env.client() as c:
        listing = await c.get("/api/v1/jobs")
    for response in (tracked, cancel, detail, listing, retry):
        _assert_no_printer_address(response.text)
    assert env.events, "the runner emitted no job events"
    _assert_no_printer_address(json.dumps([e.data for e in env.events], default=str))
    # the reference tracking uses is still stored
    assert (await env.row(jid)).result["ipp_job_id"] == 1


@pytest.mark.asyncio
async def test_cancel_between_printing_and_mark_printing_is_202(
    env: _Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """265-07: the runner moved the job to PRINTING in memory and holds it, but its row still
    says ``queued`` (``mark_printing`` has not returned). The cancel is a request at the
    printer, so the answer is 202, not a 200 that reads like a finished cancel."""
    store = env.runner._store
    real = store.mark_printing
    entered = asyncio.Event()
    gate = asyncio.Event()

    async def gated(job_id: UUID) -> bool:
        entered.set()
        await gate.wait()
        return await real(job_id)

    monkeypatch.setattr(store, "mark_printing", gated)
    jid = await env.submit()
    async with asyncio.timeout(TEST_TIMEOUT_S):
        await entered.wait()
    assert (await env.row(jid)).state == JobState.QUEUED.value
    async with env.client() as c:
        r = await c.post(f"/api/v1/jobs/{jid}/cancel")
    gate.set()
    assert r.status_code == 202, r.text
    assert r.json()["state"] == JobState.PRINTING.value
    await env.wait_state(jid, JobState.CANCELLED.value)
    assert env.ops("Print-Job") == 0
    await env.until(lambda: "ended" in env.handler.names(jid))
    assert env.handler.ended(jid)["state"] == "cancelled"
