"""PrintQueue membership (#224): add and remove a printer while the queue runs.

A removed printer's waiting jobs are not printed and stay ``queued`` in the store; a re-add
recovers them like a restart does. The in-flight job of a removed printer finishes (or, past
the timeout, is interrupted). All waits are bounded.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from app.models.job import Job as DbJob
from app.models.job import JobState as DbJobState
from app.printer_backends.ipp.client import IppClient
from app.services.job_lifecycle import JobState
from app.services.job_store import JobStore, MemoryJobStore
from app.services.job_store_sqlite import SQLiteJobStore
from app.services.page_job_runner import PageJobRunner
from app.services.page_jobs import IppPagePrinter
from app.services.print_queue import PrinterWorkerState, PrintQueue
from app.services.producers.ipp_status_producer import IppPrinterState
from PIL import Image

from tests.helpers.fake_ipp_printer import FAKE_URI, FakeIppPrinter
from tests.helpers.page_jobs import RecordingHandler, payload, registered

TEST_TIMEOUT_S = 10.0
_TAPE_ID = UUID("eeeeeeee-0000-0000-0000-000000000001")

_RENDERABLE: dict[str, Any] = {
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
}


class _TapePrinter:
    """Records every print by its ``tag`` option; the first print can be held open."""

    def __init__(self, printer_id: UUID = _TAPE_ID, *, hold_first: bool = False) -> None:
        self.id = printer_id
        self.printed: list[str] = []
        self.batches: list[int] = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        if not hold_first:
            self.release.set()

    async def print_image(self, image: Image.Image, *, tape_mm: int, **options: Any) -> None:
        self.printed.append(str(options.get("tag")))
        self.entered.set()
        await self.release.wait()

    async def print_images(
        self, images: list[Image.Image], *, tape_mm: int, **options: Any
    ) -> None:
        self.batches.append(len(images))


@pytest.fixture
def handler() -> Iterator[RecordingHandler]:
    with registered(RecordingHandler()) as h:
        yield h


@pytest_asyncio.fixture
async def async_session_factory(tmp_path: Any) -> AsyncIterator[Any]:
    """A WAL database like the hub's (see ``test_print_queue_page_recovery.py``): a worker
    cancelled mid-read must not lock the next writer."""
    import app.models  # noqa: F401 — registers all models with SQLModel.metadata
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlmodel import SQLModel

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'membership.db'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _wal(dbapi_connection: Any, _record: object) -> None:
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA journal_mode = WAL")
        cur.execute("PRAGMA busy_timeout = 5000")
        cur.close()

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture(params=["memory", "sqlite"])
def store(request: Any, async_session_factory: Any) -> JobStore:
    """SQLite yields inside every store call, so an add that started the worker before the
    recovery finished would be seen (the memory store never yields)."""
    return MemoryJobStore() if request.param == "memory" else SQLiteJobStore(async_session_factory)


async def _until(predicate: Callable[[], Any]) -> None:
    async with asyncio.timeout(TEST_TIMEOUT_S):
        while True:
            value = predicate()
            if asyncio.iscoroutine(value):
                value = await value
            if value:
                return
            await asyncio.sleep(0.005)


async def _settle() -> None:
    for _ in range(10):
        await asyncio.sleep(0)


class _WatchedEvent(asyncio.Event):
    """A resume event that reports every wait: ``waiting`` is set when the worker first waits.

    After ``spin_guard`` waits it clears itself, so a worker that spins on an event which is set
    cannot starve the test loop; the test then fails on the count, not on a hang.
    """

    def __init__(self, spin_guard: int = 25) -> None:
        super().__init__()
        self.waits = 0
        self.waiting = asyncio.Event()
        self._spin_guard = spin_guard

    async def wait(self) -> bool:
        self.waits += 1
        self.waiting.set()
        if self.waits >= self._spin_guard:
            self.clear()
        return await super().wait()


def _watch_resume_event(queue: PrintQueue, *, set_: bool) -> _WatchedEvent:
    watched = _WatchedEvent()
    if set_:
        watched.set()
    queue._worker_resume_events[_TAPE_ID] = watched
    return watched


async def _state(store: JobStore, job_id: UUID) -> str:
    row = await store.get(job_id)
    assert row is not None
    return row.state


async def _submit(queue: PrintQueue, store: JobStore, tag: str) -> UUID:
    """Persist a renderable row (so a re-add can recover it), then enqueue it."""
    job_id = uuid4()
    await store.save_queued(
        DbJob(id=job_id, printer_id=_TAPE_ID, payload={**_RENDERABLE, "options": {"tag": tag}})
    )
    await queue.submit_with_id(job_id, _TAPE_ID, Image.new("1", (300, 76)), tape_mm=24, tag=tag)
    return job_id


async def _remove_behind_blocked_job(
    queue: PrintQueue, store: JobStore, fake: _TapePrinter
) -> tuple[UUID, UUID, UUID]:
    """Job 1 prints (held open), jobs 2 and 3 wait; the printer is removed meanwhile."""
    j1 = await _submit(queue, store, "j1")
    await asyncio.wait_for(fake.entered.wait(), TEST_TIMEOUT_S)
    j2 = await _submit(queue, store, "j2")
    j3 = await _submit(queue, store, "j3")
    removal = asyncio.create_task(queue.remove_printer(_TAPE_ID, timeout_s=TEST_TIMEOUT_S))
    await _settle()
    assert not removal.done()  # waits for the in-flight job
    fake.release.set()
    await asyncio.wait_for(removal, TEST_TIMEOUT_S)
    return j1, j2, j3


def _page_side(store: JobStore, fake: FakeIppPrinter, page_id: UUID) -> tuple[PrintQueue, Any]:
    holder: dict[str, PrintQueue] = {}
    runner = PageJobRunner(
        store=store,
        notify=lambda *a: holder["q"]._notify_page_change(*a),
        poll_interval_s=0.005,
        max_backoff_s=0,
    )
    queue = PrintQueue([], store=store, page_runner=runner)
    holder["q"] = queue
    return queue, lambda: _page_printer(fake, page_id)


def _page_printer(fake: FakeIppPrinter, page_id: UUID) -> IppPagePrinter:
    client = IppClient(FAKE_URI, transport=httpx.ASGITransport(app=fake))
    return IppPagePrinter(id=page_id, client=client, state=IppPrinterState())


# ---------------------------------------------------------------------------- add


async def test_add_page_printer_accepts_jobs_while_running(handler: RecordingHandler) -> None:
    store = MemoryJobStore()
    fake = FakeIppPrinter()
    page_id = uuid4()
    queue, make_page = _page_side(store, fake, page_id)
    await queue.start()
    try:
        await queue.add_page_printer(make_page())
        jid = await queue.submit_page_job(page_id, payload(), api_key_id=None, source_ip=None)
        job = await queue.wait_for_job(str(jid), timeout_s=TEST_TIMEOUT_S)
        assert job.state == JobState.COMPLETED
        assert await _state(store, jid) == DbJobState.DONE.value
    finally:
        await queue.stop(timeout_s=2)


async def test_add_on_stopped_queue_does_no_recovery() -> None:
    store = AsyncMock(spec=MemoryJobStore)
    store.mark_interrupted.return_value = 0
    store.list_pending.return_value = []
    store.list_page_jobs_in_flight.return_value = []
    queue = PrintQueue([], store=store)
    await queue.add_printer(_TapePrinter())
    assert store.mock_calls == []
    assert queue._workers == {}
    await queue.start()  # start() recovers and runs the printer added before it
    try:
        store.mark_interrupted.assert_awaited_once_with(_TAPE_ID)
        assert set(queue._workers) == {_TAPE_ID}
    finally:
        await queue.stop(timeout_s=2)


async def test_add_same_id_different_object_raises() -> None:
    queue = PrintQueue([])
    fake = _TapePrinter()
    await queue.add_printer(fake)
    await queue.add_printer(fake)  # same object: no-op
    with pytest.raises(ValueError):
        await queue.add_printer(_TapePrinter())
    with pytest.raises(ValueError):
        await queue.add_page_printer(fake)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------- remove


async def test_remove_two_waiting_jobs_stay_queued() -> None:
    store = MemoryJobStore()
    fake = _TapePrinter(hold_first=True)
    queue = PrintQueue([fake], store=store)
    await queue.start()
    try:
        j1, j2, j3 = await _remove_behind_blocked_job(queue, store, fake)
        assert (await queue.get(j1)).state == JobState.COMPLETED
        assert await _state(store, j1) == DbJobState.DONE.value
        assert fake.printed == ["j1"]
        assert await _state(store, j2) == DbJobState.QUEUED.value
        assert await _state(store, j3) == DbJobState.QUEUED.value
        assert queue.has_job(j2) is False
        assert queue.has_job(j3) is False
    finally:
        await queue.stop(timeout_s=2)


async def test_readd_recovers_waiting_jobs() -> None:
    store = MemoryJobStore()
    fake = _TapePrinter(hold_first=True)
    queue = PrintQueue([fake], store=store)
    await queue.start()
    try:
        _, j2, j3 = await _remove_behind_blocked_job(queue, store, fake)
        new_fake = _TapePrinter()
        await queue.add_printer(new_fake)
        await queue.wait_for_job(str(j3), timeout_s=TEST_TIMEOUT_S)
        assert new_fake.printed == ["j2", "j3"]
        assert fake.printed == ["j1"]
        assert await _state(store, j2) == DbJobState.DONE.value
        assert await _state(store, j3) == DbJobState.DONE.value
    finally:
        await queue.stop(timeout_s=2)


async def test_readd_resumes_printing_page_job(store: JobStore, handler: RecordingHandler) -> None:
    fake = FakeIppPrinter(job_script=[3, 5])  # sticks at 5: the page is printing
    page_id = uuid4()
    queue, make_page = _page_side(store, fake, page_id)
    await queue.start()
    try:
        await queue.add_page_printer(make_page())
        jid = await queue.submit_page_job(page_id, payload(), api_key_id=None, source_ip=None)

        async def _tracked() -> bool:
            row = await store.get(jid)
            return row is not None and "ipp_job_id" in (row.result or {})

        await _until(_tracked)
        await queue.remove_printer(page_id, timeout_s=0)
        assert await _state(store, jid) == DbJobState.PRINTING.value
        assert queue.has_job(jid) is False

        fake.job_script = [5, 9]  # the printer reports the job completed
        await queue.add_page_printer(make_page())
        job = await queue.wait_for_job(str(jid), timeout_s=TEST_TIMEOUT_S)
        assert job.state == JobState.COMPLETED

        async def _done() -> bool:
            return await _state(store, jid) == DbJobState.DONE.value

        await _until(_done)
        assert [r.operation for r in fake.received].count("Print-Job") == 1
    finally:
        await queue.stop(timeout_s=2)


async def test_remove_while_paused_exits() -> None:
    store = MemoryJobStore()
    fake = _TapePrinter()
    queue = PrintQueue([fake], store=store)
    await queue.start()
    try:
        await queue.pause_printer(_TAPE_ID, reason="user", source="user")
        watched = _watch_resume_event(queue, set_=False)
        jid = await _submit(queue, store, "j1")
        # the worker took the job and waits in the pause loop
        await asyncio.wait_for(watched.waiting.wait(), 2)
        async with asyncio.timeout(1):
            await queue.remove_printer(_TAPE_ID, timeout_s=TEST_TIMEOUT_S)
        assert fake.printed == []
        assert await _state(store, jid) == DbJobState.QUEUED.value
        assert queue.has_job(jid) is False
    finally:
        await queue.stop(timeout_s=2)


async def test_readd_keeps_manual_pause() -> None:
    store = MemoryJobStore()
    queue = PrintQueue([_TapePrinter()], store=store)
    await queue.start()
    try:
        await queue.pause_printer(_TAPE_ID, reason="user", source="user")
        jid = await _submit(queue, store, "j1")
        # A second job: recovering it yields (re-render in a thread) after the first is
        # queued, so a worker that existed before the pause would take the first one.
        await _submit(queue, store, "j2")
        await queue.remove_printer(_TAPE_ID, timeout_s=TEST_TIMEOUT_S)
        since = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
        new_fake = _TapePrinter()
        await queue.add_printer(new_fake, paused_since=since)
        await asyncio.sleep(0.2)  # give a wrongly active worker time to print
        assert new_fake.printed == []
        assert queue.is_paused(_TAPE_ID) is True
        info = queue.pause_info(_TAPE_ID)
        assert info is not None
        assert (info.source, info.since) == ("user", since)
        assert await _state(store, jid) == DbJobState.QUEUED.value
        assert queue.has_job(jid) is True  # recovered, waiting behind the pause
    finally:
        await queue.stop(timeout_s=2)


async def test_remove_keeps_queued_batch_items() -> None:
    store = MemoryJobStore()
    fake = _TapePrinter(hold_first=True)
    queue = PrintQueue([fake], store=store)
    await queue.start()
    try:
        j1 = await _submit(queue, store, "j1")
        await asyncio.wait_for(fake.entered.wait(), TEST_TIMEOUT_S)
        batch_ids = [uuid4() for _ in range(3)]
        for bid in batch_ids:
            await store.save_queued(DbJob(id=bid, printer_id=_TAPE_ID, payload={}))
        await queue.enqueue_batch(
            printer_id=_TAPE_ID,
            images=[Image.new("1", (300, 76)) for _ in batch_ids],
            job_ids=batch_ids,
            tape_mm=24,
            options={},
        )
        removal = asyncio.create_task(queue.remove_printer(_TAPE_ID, timeout_s=TEST_TIMEOUT_S))
        await _settle()
        fake.release.set()
        await asyncio.wait_for(removal, TEST_TIMEOUT_S)
        assert fake.printed == ["j1"]
        assert fake.batches == []
        assert await _state(store, j1) == DbJobState.DONE.value
        for bid in batch_ids:
            assert await _state(store, bid) == DbJobState.QUEUED.value
            assert queue.has_job(bid) is False
    finally:
        await queue.stop(timeout_s=2)


class _GatedStore(MemoryJobStore):
    """``mark_printing`` of the second call waits for ``gate``: a remove lands mid-batch."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0
        self.reached = asyncio.Event()
        self.gate = asyncio.Event()

    async def mark_printing(self, job_id: UUID) -> bool:
        self.calls += 1
        if self.calls == 2:
            self.reached.set()
            await self.gate.wait()
        return await super().mark_printing(job_id)


async def test_remove_during_batch_pickup_keeps_the_rest_queued() -> None:
    """The flag is checked between batch items: items after the remove are not taken."""
    store = _GatedStore()
    fake = _TapePrinter()
    queue = PrintQueue([fake], store=store)
    await queue.start()
    try:
        batch_ids = [uuid4() for _ in range(3)]
        for bid in batch_ids:
            await store.save_queued(DbJob(id=bid, printer_id=_TAPE_ID, payload={}))
        await queue.enqueue_batch(
            printer_id=_TAPE_ID,
            images=[Image.new("1", (300, 76)) for _ in batch_ids],
            job_ids=batch_ids,
            tape_mm=24,
            options={},
        )
        await asyncio.wait_for(store.reached.wait(), TEST_TIMEOUT_S)
        removal = asyncio.create_task(queue.remove_printer(_TAPE_ID, timeout_s=TEST_TIMEOUT_S))
        await _settle()
        store.gate.set()
        await asyncio.wait_for(removal, TEST_TIMEOUT_S)
        # Items 1 and 2 were taken before the remove landed: they print together.
        assert fake.batches == [2]
        assert await _state(store, batch_ids[0]) == DbJobState.DONE.value
        assert await _state(store, batch_ids[1]) == DbJobState.DONE.value
        assert await _state(store, batch_ids[2]) == DbJobState.QUEUED.value
    finally:
        await queue.stop(timeout_s=2)


async def test_submit_during_remove_is_rejected() -> None:
    store = MemoryJobStore()
    fake = _TapePrinter(hold_first=True)
    queue = PrintQueue([fake], store=store)
    await queue.start()
    try:
        await _submit(queue, store, "j1")
        await asyncio.wait_for(fake.entered.wait(), TEST_TIMEOUT_S)
        removal = asyncio.create_task(queue.remove_printer(_TAPE_ID, timeout_s=TEST_TIMEOUT_S))
        await _settle()
        with pytest.raises(KeyError):
            await queue.submit(_TAPE_ID, Image.new("1", (300, 76)), tape_mm=24)
        fake.release.set()
        await asyncio.wait_for(removal, TEST_TIMEOUT_S)
        with pytest.raises(KeyError):
            await queue.submit(_TAPE_ID, Image.new("1", (300, 76)), tape_mm=24)
    finally:
        await queue.stop(timeout_s=2)


async def test_remove_past_timeout_interrupts_the_printing_tape_job() -> None:
    store = MemoryJobStore()
    fake = _TapePrinter(hold_first=True)
    queue = PrintQueue([fake], store=store)
    await queue.start()
    try:
        jid = await _submit(queue, store, "j1")
        await asyncio.wait_for(fake.entered.wait(), TEST_TIMEOUT_S)
        await queue.remove_printer(_TAPE_ID, timeout_s=0)
        job = await queue.wait_for_job(str(jid), timeout_s=1)
        assert job.state == JobState.FAILED
        assert await _state(store, jid) == DbJobState.FAILED_RESTART.value
    finally:
        await queue.stop(timeout_s=2)


# ---------------------------------------------------------------------------- add/remove races


class _GatedPendingStore(MemoryJobStore):
    """``list_pending`` waits for ``gate``: a membership call lands during recovery."""

    def __init__(self) -> None:
        super().__init__()
        self.reached = asyncio.Event()
        self.gate = asyncio.Event()

    async def list_pending(self, printer_id: UUID) -> list[DbJob]:
        self.reached.set()
        await self.gate.wait()
        return await super().list_pending(printer_id)


async def _save_renderable(store: JobStore, tag: str) -> UUID:
    job_id = uuid4()
    await store.save_queued(
        DbJob(id=job_id, printer_id=_TAPE_ID, payload={**_RENDERABLE, "options": {"tag": tag}})
    )
    return job_id


def _assert_gone(queue: PrintQueue) -> None:
    assert _TAPE_ID not in queue._queues
    assert _TAPE_ID not in queue._printers
    assert _TAPE_ID not in queue._workers
    assert queue._to_resume == {}


async def _remove_during_add(
    queue: PrintQueue, store: _GatedPendingStore, fake: _TapePrinter
) -> None:
    adding = asyncio.create_task(
        queue.add_printer(fake, paused_since=datetime(2026, 11, 1, tzinfo=UTC))
    )
    await asyncio.wait_for(store.reached.wait(), TEST_TIMEOUT_S)
    removal = asyncio.create_task(queue.remove_printer(_TAPE_ID, timeout_s=TEST_TIMEOUT_S))
    await _settle()
    store.gate.set()
    # Both calls finish; neither raises.
    await asyncio.wait_for(asyncio.gather(adding, removal), TEST_TIMEOUT_S)


async def test_remove_during_add_recovery_leaves_no_dead_worker() -> None:
    store = _GatedPendingStore()
    queue = PrintQueue([], store=store)
    await queue.start()
    try:
        await _remove_during_add(queue, store, _TapePrinter())
        _assert_gone(queue)
    finally:
        await queue.stop(timeout_s=2)


async def test_remove_during_add_recovery_with_pending_jobs() -> None:
    store = _GatedPendingStore()
    queue = PrintQueue([], store=store)
    await queue.start()
    try:
        j1 = await _save_renderable(store, "j1")
        j2 = await _save_renderable(store, "j2")
        fake = _TapePrinter()
        await _remove_during_add(queue, store, fake)
        _assert_gone(queue)
        assert fake.printed == []  # added paused, then removed
        assert await _state(store, j1) == DbJobState.QUEUED.value
        assert await _state(store, j2) == DbJobState.QUEUED.value
        assert queue.has_job(j1) is False
    finally:
        await queue.stop(timeout_s=2)


async def test_remove_during_start_recovery() -> None:
    store = _GatedPendingStore()
    fake = _TapePrinter()
    queue = PrintQueue([fake], store=store)
    jid = await _save_renderable(store, "j1")
    starting = asyncio.create_task(
        queue.start(initially_paused={_TAPE_ID: datetime(2026, 11, 1, tzinfo=UTC)})
    )
    await asyncio.wait_for(store.reached.wait(), TEST_TIMEOUT_S)
    removal = asyncio.create_task(queue.remove_printer(_TAPE_ID, timeout_s=TEST_TIMEOUT_S))
    await _settle()
    store.gate.set()
    try:
        await asyncio.wait_for(asyncio.gather(starting, removal), TEST_TIMEOUT_S)
        _assert_gone(queue)
        assert fake.printed == []
        assert await _state(store, jid) == DbJobState.QUEUED.value
    finally:
        await queue.stop(timeout_s=2)


async def test_submit_of_a_row_recovery_claimed_prints_once_and_completes() -> None:
    """PrintService saves the row, then calls submit_with_id: an add's recovery can claim the
    row in between. The label prints once, and the caller's job ends completed."""
    store = _GatedPendingStore()
    queue = PrintQueue([], store=store)
    await queue.start()
    try:
        fake = _TapePrinter()
        adding = asyncio.create_task(queue.add_printer(fake))
        await asyncio.wait_for(store.reached.wait(), TEST_TIMEOUT_S)
        jid = await _save_renderable(store, "j1")  # PrintService: row saved ...
        store.gate.set()
        await asyncio.wait_for(adding, TEST_TIMEOUT_S)
        assert queue.has_job(jid)  # ... recovery claimed it ...
        await queue.submit_with_id(  # ... then the submit arrives
            jid, _TAPE_ID, Image.new("1", (300, 76)), tape_mm=24, tag="j1"
        )
        job = await queue.wait_for_job(str(jid), timeout_s=TEST_TIMEOUT_S)
        await _settle()
        assert fake.printed == ["j1"]
        assert job.state == JobState.COMPLETED
        assert await _state(store, jid) == DbJobState.DONE.value
    finally:
        await queue.stop(timeout_s=2)


async def test_batch_of_rows_recovery_claimed_prints_once_and_completes() -> None:
    store = _GatedPendingStore()
    queue = PrintQueue([], store=store)
    await queue.start()
    try:
        fake = _TapePrinter()
        adding = asyncio.create_task(queue.add_printer(fake, paused_since=datetime.now(UTC)))
        await asyncio.wait_for(store.reached.wait(), TEST_TIMEOUT_S)
        ids = [await _save_renderable(store, f"b{i}") for i in range(2)]
        store.gate.set()
        await asyncio.wait_for(adding, TEST_TIMEOUT_S)
        await queue.enqueue_batch(
            printer_id=_TAPE_ID,
            images=[Image.new("1", (300, 76)) for _ in ids],
            job_ids=ids,
            tape_mm=24,
            options={},
        )
        await queue.resume_printer(_TAPE_ID)
        for jid in ids:
            job = await queue.wait_for_job(str(jid), timeout_s=TEST_TIMEOUT_S)
            assert job.state == JobState.COMPLETED
            assert await _state(store, jid) == DbJobState.DONE.value
        await _settle()
        assert len(fake.printed) + sum(fake.batches) == 2  # each label exactly once
    finally:
        await queue.stop(timeout_s=2)


# ---------------------------------------------------------------------------- order and races


async def test_add_pauses_before_recovery() -> None:
    """A recovered job must never print on a printer the user stopped: the pause comes first."""
    store = MemoryJobStore()
    queue = PrintQueue([], store=store)
    calls: list[str] = []
    real_pause = queue.pause_printer
    real_recover = queue._recover_printer

    async def pause_spy(*args: Any, **kwargs: Any) -> None:
        calls.append("pause")
        await real_pause(*args, **kwargs)

    async def recover_spy(printer_id: UUID) -> None:
        calls.append("recover")
        await real_recover(printer_id)

    queue.pause_printer = pause_spy  # type: ignore[method-assign]
    queue._recover_printer = recover_spy  # type: ignore[method-assign]
    await queue.start()
    try:
        await queue.add_printer(_TapePrinter(), paused_since=datetime(2026, 11, 1, tzinfo=UTC))
        assert calls == ["pause", "recover"]
    finally:
        await queue.stop(timeout_s=2)


async def test_concurrent_add_returns_after_worker_runs() -> None:
    """Both callers of a concurrent add of the same printer get control back once its worker
    runs, not only once the worker task exists."""
    store = _GatedPendingStore()
    queue = PrintQueue([], store=store)
    started: list[str] = []
    real_worker = queue._worker

    async def worker_spy(printer_id: UUID) -> None:
        started.append("worker")
        await real_worker(printer_id)

    queue._worker = worker_spy  # type: ignore[method-assign]
    await queue.start()
    try:
        fake = _TapePrinter()
        seen: dict[str, bool] = {}

        async def add(name: str) -> None:
            await queue.add_printer(fake)
            seen[name] = bool(started)  # read at once: no turn of the loop since the return

        first = asyncio.create_task(add("first"))
        await asyncio.wait_for(store.reached.wait(), TEST_TIMEOUT_S)
        second = asyncio.create_task(add("second"))
        await _settle()
        assert not second.done()  # waits for the add that is running
        store.gate.set()
        await asyncio.wait_for(asyncio.gather(first, second), TEST_TIMEOUT_S)
        assert seen == {"first": True, "second": True}
        assert set(queue._workers) == {_TAPE_ID}
    finally:
        await queue.stop(timeout_s=2)


@pytest.mark.parametrize("kind", ["single", "batch"])
async def test_pause_loop_does_not_spin(kind: str) -> None:
    """A worker that finds the printer still paused while the resume event is set clears the
    event before it waits again: it wakes at most twice, instead of once per loop turn."""
    store = MemoryJobStore()
    fake = _TapePrinter()
    queue = PrintQueue([fake], store=store)
    await queue.start()
    try:
        watched = _watch_resume_event(queue, set_=True)
        queue._worker_states[_TAPE_ID] = PrinterWorkerState.PAUSED  # paused, event still set
        if kind == "single":
            await _submit(queue, store, "j1")
        else:
            ids = [await _save_renderable(store, f"b{i}") for i in range(2)]
            await queue.enqueue_batch(
                printer_id=_TAPE_ID,
                images=[Image.new("1", (300, 76)) for _ in ids],
                job_ids=ids,
                tape_mm=24,
                options={},
            )
        await asyncio.wait_for(watched.waiting.wait(), TEST_TIMEOUT_S)
        await asyncio.sleep(0.05)  # a spinning worker would count a wake-up per turn
        assert watched.waits <= 2
        assert fake.printed == [] and fake.batches == []
        await queue.resume_printer(_TAPE_ID)  # the cleared event still wakes the worker
        await _until(lambda: fake.printed or fake.batches)
    finally:
        await queue.stop(timeout_s=2)


async def test_start_refuses_a_printer_that_is_being_added() -> None:
    """``start()`` claims every printer of its snapshot; none of them can be mid-add."""
    queue = PrintQueue([_TapePrinter()], store=MemoryJobStore())
    queue._adds[_TAPE_ID] = asyncio.Event()  # impossible state: an add of a snapshot printer
    with pytest.raises(AssertionError):
        await queue.start()
    assert queue._running is False  # a failed start can be retried


# ---------------------------------------------------------------------------- removal timeout


class _CallGatedStore(MemoryJobStore):
    """One store call waits for ``gate`` (cancellable): a removal timeout lands inside it."""

    def __init__(self, gated: str) -> None:
        super().__init__()
        self._gated = gated
        self.reached = asyncio.Event()
        self.gate = asyncio.Event()
        self.calls = 0

    async def _maybe_wait(self, name: str) -> None:
        if name == self._gated:
            self.calls += 1
            self.reached.set()
            await self.gate.wait()

    async def mark_printing(self, job_id: UUID) -> bool:
        await self._maybe_wait("mark_printing")
        return await super().mark_printing(job_id)

    async def mark_done(self, job_id: UUID) -> None:
        await self._maybe_wait("mark_done")
        await super().mark_done(job_id)


async def _remove_with_timeout_then_release(queue: PrintQueue, store: _CallGatedStore) -> None:
    """Remove with a zero timeout (the worker is cancelled), then open the gate once the
    cancel has been delivered, as a database call that finishes late would."""
    worker = queue._workers[_TAPE_ID]
    removal = asyncio.create_task(queue.remove_printer(_TAPE_ID, timeout_s=0))
    await _until(lambda: worker.cancelling() > 0 or worker.done())
    store.gate.set()
    await asyncio.wait_for(removal, TEST_TIMEOUT_S)


async def test_timeout_cancel_of_terminal_job_keeps_terminal_row() -> None:
    """The job the removal timeout cancelled before its row was taken ends ``failed`` in memory;
    its row must end terminal too, not stay ``queued`` for a recovery that skips the known id."""
    store = _CallGatedStore("mark_printing")
    fake = _TapePrinter()
    queue = PrintQueue([fake], store=store)
    await queue.start()
    try:
        jid = await _submit(queue, store, "j1")
        await asyncio.wait_for(store.reached.wait(), TEST_TIMEOUT_S)
        await _remove_with_timeout_then_release(queue, store)
        job = await queue.wait_for_job(str(jid), timeout_s=1)
        assert job.state == JobState.FAILED
        assert fake.printed == []  # it never reached the printer
        assert await _state(store, jid) == DbJobState.FAILED.value
    finally:
        await queue.stop(timeout_s=2)


async def test_timeout_cancel_after_print_marks_single_job_done() -> None:
    """The label printed; the timeout hits while the row is being marked done. The row ends done,
    not ``failed_restart`` (the printer did print it)."""
    store = _CallGatedStore("mark_done")
    fake = _TapePrinter()
    queue = PrintQueue([fake], store=store)
    await queue.start()
    try:
        jid = await _submit(queue, store, "j1")
        await asyncio.wait_for(store.reached.wait(), TEST_TIMEOUT_S)
        await _remove_with_timeout_then_release(queue, store)
        job = await queue.wait_for_job(str(jid), timeout_s=1)
        assert job.state == JobState.COMPLETED
        assert fake.printed == ["j1"]
        assert await _state(store, jid) == DbJobState.DONE.value
    finally:
        await queue.stop(timeout_s=2)


async def test_removal_timeout_after_print_marks_group_done() -> None:
    """A group that printed is marked done label by label. A removal timeout in the middle of it
    must not report the rest of the group ``failed_restart``: every label of it printed."""
    store = _CallGatedStore("mark_done")
    fake = _TapePrinter()
    queue = PrintQueue([fake], store=store)
    await queue.start()
    try:
        ids = [await _save_renderable(store, f"b{i}") for i in range(3)]
        await queue.enqueue_batch(
            printer_id=_TAPE_ID,
            images=[Image.new("1", (300, 76)) for _ in ids],
            job_ids=ids,
            tape_mm=24,
            options={},
        )
        await asyncio.wait_for(store.reached.wait(), TEST_TIMEOUT_S)
        assert fake.batches == [3]  # the whole group printed
        await _remove_with_timeout_then_release(queue, store)
        for jid in ids:
            job = await queue.wait_for_job(str(jid), timeout_s=1)
            assert job.state == JobState.COMPLETED
            assert await _state(store, jid) == DbJobState.DONE.value
    finally:
        await queue.stop(timeout_s=2)
