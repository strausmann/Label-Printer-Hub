"""PrintQueue with page printers: submit, deferral into the held slot, cancel, clear, one job at
the printer, and the media-kind guard. The printer is ``FakeIppPrinter``; waits are bounded."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from app.models.job import JobState as DbJobState
from app.printer_backends.ipp.client import IppClient
from app.services.job_lifecycle import Job, JobState
from app.services.job_store import MemoryJobStore
from app.services.page_job_runner import PageJobRunner
from app.services.page_jobs import IppPagePrinter
from app.services.print_queue import PrintQueue
from app.services.producers.ipp_status_producer import IppPrinterState
from app.sheets.errors import MediaKindMismatchError
from PIL import Image

from tests.helpers.fake_ipp_printer import FAKE_URI, FakeIppPrinter, FlakyTransport
from tests.helpers.page_jobs import RecordingHandler, payload, registered

TEST_TIMEOUT_S = 10.0


class _TapePrinter:
    def __init__(self) -> None:
        self.id = uuid4()
        self.prints = 0
        self.gate: asyncio.Event | None = None
        self.entered = asyncio.Event()

    async def print_image(self, image: Image.Image, *, tape_mm: int, **options: Any) -> None:
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        self.prints += 1

    async def print_images(self, images: list[Image.Image], *, tape_mm: int, **o: Any) -> None:
        self.prints += len(images)


class _Env:
    def __init__(self, fake: FakeIppPrinter, transport: httpx.AsyncBaseTransport | None) -> None:
        self.fake = fake
        self.store = MemoryJobStore()
        self.state = IppPrinterState()
        client = IppClient(FAKE_URI, transport=transport or httpx.ASGITransport(app=fake))
        self.page = IppPagePrinter(id=uuid4(), client=client, state=self.state)
        self.tape = _TapePrinter()
        self.events: list[tuple[str, JobState, JobState, dict[str, Any]]] = []
        # The runner's events go through the queue's hook, as with the runner the queue builds.
        self.runner = PageJobRunner(
            store=self.store,
            notify=lambda *a: self.queue._notify_page_change(*a),
            poll_interval_s=0.005,
            max_backoff_s=0,
        )
        self.queue = PrintQueue(
            [self.tape],
            store=self.store,
            on_state_change=self._on_change,
            page_printers=[self.page],
            page_runner=self.runner,
        )

    def _on_change(self, job: Job, f: JobState, t: JobState, queue_depth: int = 0) -> None:
        self.events.append(
            (job.id, f, t, {"kind": job.kind, "at_printer": job.at_printer, "summary": job.summary})
        )

    def ops(self, name: str) -> list[int]:
        return [i for i, r in enumerate(self.fake.received) if r.operation == name]

    async def db_state(self, job_id: UUID) -> str:
        row = await self.store.get(job_id)
        assert row is not None
        return row.state

    async def wait_db(self, job_id: UUID, expected: str) -> None:
        async with asyncio.timeout(TEST_TIMEOUT_S):
            while await self.db_state(job_id) != expected:
                await asyncio.sleep(0.005)

    async def until(self, predicate: Callable[[], Any]) -> None:
        async with asyncio.timeout(TEST_TIMEOUT_S):
            while True:
                value = predicate()
                if asyncio.iscoroutine(value):
                    value = await value
                if value:
                    return
                await asyncio.sleep(0.005)

    async def wait_terminal(self, job_id: UUID) -> Job:
        async with asyncio.timeout(TEST_TIMEOUT_S):
            return await self.queue.wait_for_job(str(job_id), timeout_s=TEST_TIMEOUT_S)


@asynccontextmanager
async def _env(
    fake: FakeIppPrinter, transport: httpx.AsyncBaseTransport | None = None
) -> AsyncIterator[_Env]:
    env = _Env(fake, transport)
    await env.queue.start()
    try:
        yield env
    finally:
        await env.queue.stop(timeout_s=2)


@pytest.fixture
def handler() -> Any:
    with registered(RecordingHandler()) as h:
        yield h


@pytest_asyncio.fixture
async def env(handler: RecordingHandler) -> AsyncIterator[_Env]:
    async with _env(FakeIppPrinter(job_script=[3, 5, 9])) as e:
        yield e


async def _submit(env: _Env, **detail: Any) -> UUID:
    return await env.queue.submit_page_job(
        env.page.id, payload(**detail), api_key_id=None, source_ip=None
    )


# ---------------------------------------------------------------------------- submit


async def test_submit_page_job_prints(env: _Env, handler: RecordingHandler) -> None:
    jid = await _submit(env, job_summary={"sheet": "A123", "cells": 4})
    job = await env.wait_terminal(jid)
    assert job.state == JobState.COMPLETED
    await env.wait_db(jid, DbJobState.DONE.value)
    row = await env.store.get(jid)
    assert row is not None and row.payload["kind"] == "calibration_page"
    assert handler.names(jid) == ["started", "completed"]
    mine = [e for e in env.events if e[0] == str(jid)]
    assert all(e[3]["kind"] == "calibration_page" for e in mine)
    assert all(e[3]["summary"] == {"sheet": "A123", "cells": 4} for e in mine)
    assert any(e[3]["at_printer"] == "printing" for e in mine)


async def test_submit_page_job_with_given_id(env: _Env) -> None:
    given = uuid4()
    jid = await env.queue.submit_page_job(
        env.page.id, payload(), api_key_id=uuid4(), source_ip="198.51.100.7", job_id=given
    )
    assert jid == given
    row = await env.store.get(given)
    assert row is not None and row.source_ip == "198.51.100.7"
    await env.wait_terminal(jid)


async def test_queue_refuses_kind_mismatch(env: _Env) -> None:
    with pytest.raises(MediaKindMismatchError):
        await env.queue.submit_page_job(env.tape.id, payload(), api_key_id=None, source_ip=None)
    with pytest.raises(MediaKindMismatchError):
        await env.queue.submit(env.page.id, Image.new("1", (10, 10)), tape_mm=24)
    with pytest.raises(MediaKindMismatchError):
        await env.queue.submit_with_id(uuid4(), env.page.id, Image.new("1", (10, 10)), tape_mm=24)
    with pytest.raises(MediaKindMismatchError):
        await env.queue.enqueue_batch(
            printer_id=env.page.id,
            images=[Image.new("1", (10, 10))],
            job_ids=[uuid4()],
            tape_mm=24,
            options={},
        )
    with pytest.raises(KeyError):
        await env.queue.submit_page_job(uuid4(), payload(), api_key_id=None, source_ip=None)


async def test_one_job_at_printer(handler: RecordingHandler) -> None:
    fake = FakeIppPrinter(job_script=[3, 3, 5, 5, 9])
    async with _env(fake) as env:
        a = await _submit(env)
        b = await _submit(env)
        await env.wait_terminal(b)
        prints = env.ops("Print-Job")
        assert len(prints) == 2
        # the second Print-Job comes after the first job's final (state 9) answer
        last_poll_of_a = max(
            i
            for i, r in enumerate(fake.received)
            if r.operation == "Get-Job-Attributes" and r.attributes["job-id"] == [1]
        )
        assert prints[1] > last_poll_of_a
        assert handler.names(a) == ["started", "completed"]
        assert handler.names(b) == ["started", "completed"]


# ---------------------------------------------------------------------------- deferral


async def test_preflight_unreachable_defers(handler: RecordingHandler) -> None:
    fake = FakeIppPrinter(job_script=[9])
    transport = FlakyTransport(
        httpx.ASGITransport(app=fake), {"Get-Printer-Attributes": [httpx.ConnectError]}
    )
    async with _env(fake, transport) as env:
        jid = await _submit(env)
        await env.until(lambda: env.queue.is_paused(env.page.id))
        info = env.queue.pause_info(env.page.id)
        assert info is not None
        assert (info.source, info.reason_code) == ("printer_error", "ipp_unreachable")
        assert await env.db_state(jid) == DbJobState.QUEUED.value
        assert (await env.queue.get(jid)).state == JobState.QUEUED
        assert env.ops("Print-Job") == []
        assert all(e[2] != JobState.PRINTING for e in env.events if e[0] == str(jid))
        assert handler.calls == []

        await env.queue.resume_printer(env.page.id)
        job = await env.wait_terminal(jid)
        assert job.state == JobState.COMPLETED
        assert len(env.ops("Print-Job")) == 1


async def test_deferred_job_keeps_its_place(handler: RecordingHandler) -> None:
    """The held job prints before anything submitted while the printer was paused."""
    fake = FakeIppPrinter(job_script=[9], printer_state=5, reasons=["media-empty-error"])
    async with _env(fake) as env:
        first = await _submit(env)
        await env.until(lambda: env.queue.is_paused(env.page.id))
        second = await _submit(env)
        fake.printer_state, fake.reasons = 3, ["none"]
        await env.queue.resume_printer(env.page.id)
        await env.wait_terminal(second)
        prints = [r.attributes["job-name"] for r in fake.received if r.operation == "Print-Job"]
        assert len(prints) == 2
        row_first = await env.store.get(first)
        row_second = await env.store.get(second)
        assert row_first is not None and row_second is not None
        assert row_first.result is not None and row_first.result["ipp_job_id"] == 1
        assert row_second.result is not None and row_second.result["ipp_job_id"] == 2


async def test_blocking_reason_pauses_with_keyword(handler: RecordingHandler) -> None:
    fake = FakeIppPrinter(printer_state=5, reasons=["toner-empty-error"])
    async with _env(fake) as env:
        jid = await _submit(env)
        await env.until(lambda: env.queue.is_paused(env.page.id))
        info = env.queue.pause_info(env.page.id)
        assert info is not None and info.reason_code == "toner-empty"
        assert await env.db_state(jid) == DbJobState.QUEUED.value
        assert env.ops("Print-Job") == []


# ---------------------------------------------------------------------------- cancel / clear


async def test_cancel_queued_page_job(handler: RecordingHandler) -> None:
    async with _env(FakeIppPrinter(job_script=[9])) as env:
        await env.queue.pause_printer(env.page.id, reason="user", source="user")
        jid = await _submit(env)
        assert await env.queue.cancel(str(jid)) is True
        assert await env.db_state(jid) == DbJobState.CANCELLED.value
        assert handler.ended(jid) == {
            "state": "cancelled",
            "started": False,
            "error_code": "cancelled",
        }
        await env.queue.resume_printer(env.page.id)
        canary = await _submit(env)
        await env.wait_terminal(canary)
        assert len(env.ops("Print-Job")) == 1  # the canary only


async def test_cancel_held_page_job(handler: RecordingHandler) -> None:
    fake = FakeIppPrinter(job_script=[9], accepting_jobs=False)
    async with _env(fake) as env:
        jid = await _submit(env)
        await env.until(lambda: env.queue.is_paused(env.page.id))
        assert await env.queue.cancel(str(jid)) is True
        assert await env.db_state(jid) == DbJobState.CANCELLED.value
        assert handler.ended(jid)["state"] == "cancelled"
        fake.accepting_jobs = True
        await env.queue.resume_printer(env.page.id)
        canary = await _submit(env)
        await env.wait_terminal(canary)
        assert len(env.ops("Print-Job")) == 1


async def test_cancel_tracked_page_job_sends_cancel_job(handler: RecordingHandler) -> None:
    async with _env(FakeIppPrinter(job_script=[3])) as env:
        jid = await _submit(env)
        await env.until(lambda: env.runner.is_tracking(jid))
        assert await env.queue.cancel(str(jid)) is True
        job = await env.wait_terminal(jid)
        assert job.state == JobState.CANCELLED
        assert len(env.ops("Cancel-Job")) == 1
        await env.wait_db(jid, DbJobState.CANCELLED.value)


async def test_clear_cancels_queued_and_held_never_tracked(handler: RecordingHandler) -> None:
    fake = FakeIppPrinter(job_script=[3])
    async with _env(fake) as env:
        tracked = await _submit(env)
        await env.until(lambda: env.runner.is_tracking(tracked))
        waiting = [await _submit(env), await _submit(env)]
        assert await env.queue.clear_queue(env.page.id) == 2
        for jid in waiting:
            assert await env.db_state(jid) == DbJobState.CANCELLED.value
            assert handler.ended(jid)["state"] == "cancelled"
        assert (await env.queue.get(tracked)).state == JobState.PRINTING
        assert env.ops("Cancel-Job") == []
        fake.job_script = [9]
        await env.wait_terminal(tracked)
        assert len(env.ops("Print-Job")) == 1


async def test_tape_printing_job_still_not_cancellable(handler: RecordingHandler) -> None:
    """ADR 0005: a tape job on the wire cannot be cancelled, though PRINTING -> CANCELLED exists."""
    async with _env(FakeIppPrinter()) as env:
        env.tape.gate = asyncio.Event()
        jid = await env.queue.submit(env.tape.id, Image.new("1", (10, 10)), tape_mm=24)
        async with asyncio.timeout(TEST_TIMEOUT_S):
            await env.tape.entered.wait()
        assert (await env.queue.get(jid)).state == JobState.PRINTING
        assert await env.queue.cancel(jid) is False
        n = await env.queue.clear_queue(env.tape.id)
        assert n == 0
        env.tape.gate.set()
        job = await env.queue.wait_for_job(jid, timeout_s=TEST_TIMEOUT_S)
        assert job.state == JobState.COMPLETED
        assert env.tape.prints == 1


async def test_page_job_is_page_job(env: _Env) -> None:
    jid = await _submit(env)
    assert env.queue.is_page_job(jid) is True
    tape = await env.queue.submit(env.tape.id, Image.new("1", (10, 10)), tape_mm=24)
    assert env.queue.is_page_job(tape) is False
    await env.wait_terminal(jid)


async def test_stop_does_not_wait_for_a_tracked_job(handler: RecordingHandler) -> None:
    """Stopping the queue cancels the tracking at once; the row stays ``printing``
    (the printer may still print the page) and no outcome is reported."""
    env = _Env(FakeIppPrinter(job_script=[3]), None)
    await env.queue.start()
    jid = await _submit(env)
    await env.until(lambda: env.runner.is_tracking(jid))
    loop = asyncio.get_running_loop()
    began = loop.time()
    await env.queue.stop(timeout_s=30)
    assert loop.time() - began < 5
    assert await env.db_state(jid) == DbJobState.PRINTING.value
    assert handler.calls == []
    assert env.state.own_job_ids == set()
