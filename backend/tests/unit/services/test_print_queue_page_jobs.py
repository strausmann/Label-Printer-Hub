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


async def test_user_pause_during_preflight_survives_deferral(handler: RecordingHandler) -> None:
    """The user pauses while the pre-flight is in flight; the pre-flight then defers. The pause
    stays a user pause, a healthy probe does not lift it, and the job does not print."""
    from app.services.event_bus import EventBus
    from app.services.producers.ipp_status_producer import IppStatusProducer

    fake = FakeIppPrinter(job_script=[9])
    holder: dict[str, _Env] = {}

    class _PauseThenUnreachable(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.inner = httpx.ASGITransport(app=fake)
            self.armed = True

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if self.armed:
                self.armed = False
                env = holder["env"]
                await env.queue.pause_printer(env.page.id, reason="user", source="user")
                raise httpx.ConnectError("printer not reachable", request=request)
            return await self.inner.handle_async_request(request)

    async with _env(fake, _PauseThenUnreachable()) as env:
        holder["env"] = env
        jid = await _submit(env)
        await env.until(lambda: env.queue.pause_info(env.page.id) is not None)
        await asyncio.sleep(0.05)  # let the worker handle the Deferred
        info = env.queue.pause_info(env.page.id)
        assert info is not None and info.source == "user"

        producer = IppStatusProducer(
            bus=EventBus(),
            printer_id=env.page.id,
            client=IppClient(FAKE_URI, transport=httpx.ASGITransport(app=fake)),
            session_factory=None,  # type: ignore[arg-type]  # cache write fails, logged
            state=env.state,
            pause_control=env.queue,
            interval_s=30,
        )
        await producer.probe_once()
        await producer.stop()
        await asyncio.sleep(0.05)
        assert env.queue.is_paused(env.page.id)
        assert env.ops("Print-Job") == []
        assert await env.db_state(jid) == DbJobState.QUEUED.value


async def test_printer_error_pause_may_become_user_pause(env: _Env) -> None:
    await env.queue.pause_printer(env.page.id, reason="ipp_unreachable", source="printer_error")
    await env.queue.pause_printer(env.page.id, reason="user", source="user")
    info = env.queue.pause_info(env.page.id)
    assert info is not None and info.source == "user"


async def test_no_pause_when_deferred_job_was_cancelled(handler: RecordingHandler) -> None:
    fake = FakeIppPrinter(job_script=[9])
    holder: dict[str, Any] = {}

    class _CancelThenUnreachable(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            await holder["env"].queue.cancel(str(holder["jid"]))
            raise httpx.ConnectError("printer not reachable", request=request)

    async with _env(fake, _CancelThenUnreachable()) as env:
        holder["env"] = env
        await env.queue.pause_printer(env.page.id, reason="user", source="user")
        holder["jid"] = await _submit(env)
        await env.queue.resume_printer(env.page.id)
        await env.wait_db(holder["jid"], DbJobState.CANCELLED.value)
        await asyncio.sleep(0.05)
        assert not env.queue.is_paused(env.page.id)


class _GatedStore(MemoryJobStore):
    """``save_queued`` stops at a gate: the row does not exist while the gate is closed."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.gate = asyncio.Event()

    async def save_queued(self, job: Any) -> None:
        self.entered.set()
        await self.gate.wait()
        await super().save_queued(job)


async def test_clear_queue_during_the_row_insert_is_not_undone(handler: RecordingHandler) -> None:
    """The job is registered in memory before its row is saved. A clear in between cancels the
    in-memory job; its cancellation finds no row to persist. The insert that follows must not
    leave the row ``queued`` (a restart would resurrect the cancelled job)."""
    fake = FakeIppPrinter(job_script=[9])
    async with _env(fake) as env:
        gated = _GatedStore()
        env.queue._store = gated  # type: ignore[assignment]
        await env.queue.pause_printer(env.page.id, reason="user", source="user")
        submit = asyncio.create_task(
            env.queue.submit_page_job(env.page.id, payload(), api_key_id=None, source_ip=None)
        )
        async with asyncio.timeout(TEST_TIMEOUT_S):
            await gated.entered.wait()
        assert await env.queue.clear_queue(env.page.id) == 1  # the in-memory job, no row yet
        gated.gate.set()
        jid = await submit
        row = await gated.get(jid)
        assert row is not None
        assert row.state == DbJobState.CANCELLED.value
        await env.queue.resume_printer(env.page.id)
        await asyncio.sleep(0)  # the worker has nothing to take
        assert env.ops("Print-Job") == []


class _DoneFails(MemoryJobStore):
    async def mark_done(self, job_id: UUID) -> None:
        raise RuntimeError("db down")


async def test_backstop_ends_the_job_completely(handler: RecordingHandler) -> None:
    """The runner raises (the completion write fails): the job ends failed with its event,
    its outcome call and its waiters released, not just a silent in-memory change."""
    async with _env(FakeIppPrinter(job_script=[5, 9])) as env:
        failing = _DoneFails()
        failing._jobs = env.store._jobs  # type: ignore[attr-defined]
        env.queue._store = failing  # type: ignore[assignment]
        env.runner._store = failing  # type: ignore[assignment]
        jid = await _submit(env)
        job = await env.wait_terminal(jid)  # a waiter is released
        assert job.state == JobState.FAILED
        assert job.error_code == "interrupted"
        assert any(
            e[0] == str(jid) and e[1] == JobState.PRINTING and e[2] == JobState.FAILED
            for e in env.events
        )
        await env.until(lambda: "ended" in handler.names(jid))
        assert handler.ended(jid) == {
            "state": "failed",
            "started": True,
            "error_code": "interrupted",
        }
        await env.wait_db(jid, DbJobState.FAILED.value)


# ---------------------------------------------------------------------------- 266-09


class _SavedThenRaises(MemoryJobStore):
    """``save_queued`` commits the row, then raises (a lock on the refresh after the commit)."""

    def __init__(self, exc: BaseException, *, mark_fails: bool = False) -> None:
        super().__init__()
        self.exc = exc
        self.mark_fails = mark_fails

    async def save_queued(self, job: Any) -> None:
        await super().save_queued(job)
        raise self.exc

    async def mark_failed_code(self, job_id: UUID, *a: Any, **k: Any) -> None:
        if self.mark_fails:
            raise RuntimeError("database is locked")
        await super().mark_failed_code(job_id, *a, **k)


async def _submit_into(env: _Env, store: MemoryJobStore, jid: UUID) -> None:
    env.queue._store = store  # type: ignore[assignment]
    env.runner._store = store  # type: ignore[assignment]
    await env.queue.pause_printer(env.page.id, reason="user", source="user")
    await env.queue.submit_page_job(
        env.page.id, payload("sheet_page"), api_key_id=None, source_ip=None, job_id=jid
    )


@pytest.mark.parametrize(
    "exc",
    [RuntimeError("database is locked"), TimeoutError("refresh timed out")],
    ids=["db-error", "timeout"],
)
async def test_save_queued_failure_marks_row_failed_and_releases_cells(
    handler: RecordingHandler, exc: BaseException
) -> None:
    """The row was committed, then ``save_queued`` raised: the row ends ``failed`` with
    ``print_interrupted`` (no restart prints it), the cells are freed through ``on_ended`` and
    the job leaves memory. The caller still sees the error (the route answers 502)."""
    async with _env(FakeIppPrinter(job_script=[9])) as env:
        store = _SavedThenRaises(exc)
        jid = uuid4()
        with pytest.raises(type(exc)):
            await _submit_into(env, store, jid)
        row = await store.get(jid)
        assert row is not None and row.state == DbJobState.FAILED.value
        assert (row.error or "").startswith("print_interrupted:")
        assert (row.result or {}).get("started") is False
        assert handler.ended(jid) == {
            "state": "failed",
            "started": False,
            "error_code": "print_interrupted",
        }
        assert not env.queue.has_job(jid)
        await env.queue.resume_printer(env.page.id)
        await asyncio.sleep(0.05)
        assert env.ops("Print-Job") == []


async def test_save_queued_failure_with_a_failing_end_write_keeps_the_cells(
    handler: RecordingHandler,
) -> None:
    """The end cannot be written either: the row may still say ``queued`` and a restart could
    print it, so the cells stay reserved (the startup sweep or the job settles them) and the
    job stays known, ended, and is never evicted or printed by this process."""
    async with _env(FakeIppPrinter(job_script=[9])) as env:
        store = _SavedThenRaises(RuntimeError("database is locked"), mark_fails=True)
        jid = uuid4()
        with pytest.raises(RuntimeError):
            await _submit_into(env, store, jid)
        assert "ended" not in handler.names(jid)
        assert env.queue.has_job(jid)
        assert (await env.queue.get(jid)).state == JobState.FAILED
        assert env.queue.forget_job(jid) is False  # unpersisted: never evicted
        await env.queue.resume_printer(env.page.id)
        await asyncio.sleep(0.05)
        assert env.ops("Print-Job") == []


async def test_save_queued_failure_before_the_commit_is_unchanged(
    handler: RecordingHandler,
) -> None:
    """No row was written: nothing to mark; the job leaves memory as before."""

    class _Raises(MemoryJobStore):
        async def save_queued(self, job: Any) -> None:
            raise ConnectionError("database unreachable")

    async with _env(FakeIppPrinter(job_script=[9])) as env:
        store = _Raises()
        jid = uuid4()
        with pytest.raises(ConnectionError):
            await _submit_into(env, store, jid)
        assert await store.get(jid) is None
        assert not env.queue.has_job(jid)
        assert "ended" not in handler.names(jid)  # the caller frees the cells of a job-less page


async def test_save_queued_failure_after_a_cancel_persists_the_cancel(
    handler: RecordingHandler,
) -> None:
    """A cancel lands while the row is saved, then the save raises after its commit: the row
    ends ``cancelled`` (what the user asked for), with the one ``on_ended`` the cancel sent."""

    class _GatedThenRaises(_GatedStore):
        async def save_queued(self, job: Any) -> None:
            await super().save_queued(job)
            raise RuntimeError("database is locked")

    async with _env(FakeIppPrinter(job_script=[9])) as env:
        store = _GatedThenRaises()
        env.queue._store = store  # type: ignore[assignment]
        await env.queue.pause_printer(env.page.id, reason="user", source="user")
        jid = uuid4()
        submit = asyncio.create_task(
            env.queue.submit_page_job(
                env.page.id, payload(), api_key_id=None, source_ip=None, job_id=jid
            )
        )
        async with asyncio.timeout(TEST_TIMEOUT_S):
            await store.entered.wait()
        assert await env.queue.cancel(str(jid))
        store.gate.set()
        with pytest.raises(RuntimeError):
            await submit
        row = await store.get(jid)
        assert row is not None and row.state == DbJobState.CANCELLED.value
        assert handler.ended(jid)["state"] == "cancelled"
        assert not env.queue.has_job(jid)


class _DoneAndFailFail(_DoneFails):
    async def mark_failed_code(self, job_id: UUID, *a: Any, **k: Any) -> None:
        raise RuntimeError("db down")


async def test_backstop_end_that_cannot_be_written_is_never_evicted(
    handler: RecordingHandler,
) -> None:
    """The backstop ends the job in memory, but its row could not be written (it still says
    ``printing``). Like a tape job whose end was not written, it stays known: eviction must
    not forget it (Task 7's ``_unpersisted`` rule, applied to page jobs)."""
    async with _env(FakeIppPrinter(job_script=[5, 9])) as env:
        failing = _DoneAndFailFail()
        failing._jobs = env.store._jobs  # type: ignore[attr-defined]
        env.queue._store = failing  # type: ignore[assignment]
        env.runner._store = failing  # type: ignore[assignment]
        jid = await _submit(env)
        job = await env.wait_terminal(jid)
        assert job.state == JobState.FAILED
        assert env.queue.forget_job(jid) is False
        assert jid not in {j for j, _ in env.queue.finished_jobs()}
