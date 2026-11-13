"""Restart recovery of page jobs (plan Task 8): tracking resumes, an unknown outcome is not
guessed, queued jobs print after a restart. Two queues share one store and one fake printer;
the fake keeps its job ids across the "restart", as a printer does when the hub restarts.
Waits are bounded."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from app.models.job import Job as DbJob
from app.models.job import JobState as DbJobState
from app.printer_backends.ipp.client import IppClient
from app.printer_backends.ipp.codec import OPERATIONS, decode
from app.services import page_jobs
from app.services.job_lifecycle import JobState
from app.services.job_store import JobStore, MemoryJobStore
from app.services.job_store_sqlite import SQLiteJobStore
from app.services.page_job_runner import PageJobRunner
from app.services.page_jobs import IppPagePrinter
from app.services.print_queue import PrintQueue
from app.services.producers.ipp_status_producer import IppPrinterState

from tests.helpers.fake_ipp_printer import (
    FAKE_URI,
    FailingTransport,
    FakeIppPrinter,
    FlakyTransport,
)
from tests.helpers.page_jobs import RecordingHandler, payload, registered

TEST_TIMEOUT_S = 10.0


@dataclass
class _Side:
    """One hub run: a queue over the shared store, its runner and its page printer."""

    queue: PrintQueue
    runner: PageJobRunner
    page: IppPagePrinter


def _side(
    store: JobStore,
    fake: FakeIppPrinter,
    page_id: UUID,
    transport: httpx.AsyncBaseTransport | None = None,
) -> _Side:
    client = IppClient(FAKE_URI, transport=transport or httpx.ASGITransport(app=fake))
    page = IppPagePrinter(id=page_id, client=client, state=IppPrinterState())
    holder: dict[str, PrintQueue] = {}
    runner = PageJobRunner(
        store=store,
        notify=lambda *a: holder["q"]._notify_page_change(*a),
        poll_interval_s=0.005,
        max_backoff_s=0,
    )
    queue = PrintQueue([], store=store, page_printers=[page], page_runner=runner)
    holder["q"] = queue
    return _Side(queue, runner, page)


@asynccontextmanager
async def _running(side: _Side, **start_kwargs: Any) -> AsyncIterator[_Side]:
    await side.queue.start(**start_kwargs)
    try:
        yield side
    finally:
        await side.queue.stop(timeout_s=2)


async def _until(predicate: Callable[[], Any]) -> None:
    async with asyncio.timeout(TEST_TIMEOUT_S):
        while True:
            value = predicate()
            if asyncio.iscoroutine(value):
                value = await value
            if value:
                return
            await asyncio.sleep(0.005)


async def _row(store: JobStore, job_id: UUID) -> DbJob:
    row = await store.get(job_id)
    assert row is not None
    return row


async def _wait_db(store: JobStore, job_id: UUID, expected: str) -> None:
    async def _is() -> bool:
        return (await _row(store, job_id)).state == expected

    await _until(_is)


async def _seed_printing(
    store: JobStore, page_id: UUID, result: dict[str, Any] | None, **detail: Any
) -> UUID:
    """A page job row as a crash leaves it: ``printing`` with whatever ``result`` it had."""
    row = DbJob(
        id=uuid4(), printer_id=page_id, template_key=None, payload=payload(**detail).model_dump()
    )
    await store.save_queued(row)
    assert await store.mark_printing(row.id)
    if result is not None:
        await store.set_result(row.id, result)
    return row.id


async def _tracked_in_db(store: JobStore, job_id: UUID) -> None:
    """Wait until the IPP job id is persisted: only then does a restart resume the job."""

    async def _has_id() -> bool:
        return "ipp_job_id" in ((await _row(store, job_id)).result or {})

    await _until(_has_id)


@pytest.fixture
def handler() -> Any:
    with registered(RecordingHandler()) as h:
        yield h


@pytest_asyncio.fixture
async def async_session_factory(tmp_path: Any) -> AsyncIterator[Any]:
    """The shared fixture's database, in the journal mode the hub runs with.

    SQLite's default rollback journal lets a reader block every writer. These tests stop one
    "hub run" by cancelling its worker, which can cut a read off half way and leave the
    connection holding its lock; the next run's first write then failed with ``database is
    locked`` after the busy timeout (seen on CI, as a timeout of the test). The hub uses WAL
    and a busy timeout (``app/db/engine.py``): readers block nobody there. Foreign keys stay
    off, like the shared fixture (the jobs here name printers that have no row).
    """
    import app.models  # noqa: F401 — registers all models with SQLModel.metadata
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlmodel import SQLModel

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'recovery.db'}",
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
    return MemoryJobStore() if request.param == "memory" else SQLiteJobStore(async_session_factory)


# ---------------------------------------------------------------------------- the database


async def test_a_reader_left_open_by_the_first_run_does_not_block_the_second_runs_writes(
    async_session_factory: Any,
) -> None:
    """The first "hub run" is stopped by cancelling its worker, and a cancel that lands in the
    middle of a read leaves that connection with an open read transaction. With SQLite's default
    rollback journal a reader blocks every commit, so the second run's first write failed with
    ``database is locked`` after the busy timeout, and a test waiting for it timed out (seen on
    CI). The hub runs with WAL (``app/db/engine.py``), where readers block nobody; so do these
    tests."""
    from app.models.job import Job as Row
    from sqlalchemy import select

    store = SQLiteJobStore(async_session_factory)
    row = Row(id=uuid4(), printer_id=uuid4(), template_key=None, payload={})
    await store.save_queued(row)
    await store.save_queued(Row(id=uuid4(), printer_id=uuid4(), template_key=None, payload={}))
    reader = async_session_factory()
    session = await reader.__aenter__()
    try:
        # A read cut off half way: one row taken, the statement not finished.
        stream = await session.stream(select(Row))
        await stream.fetchmany(1)
        async with asyncio.timeout(2):
            await store.mark_failed(row.id, "x")
    finally:
        await reader.__aexit__(None, None, None)
    assert (await _row(store, row.id)).state == DbJobState.FAILED.value


# ---------------------------------------------------------------------------- resume


async def test_restart_resumes_tracking_to_completion(
    async_session_factory: Any, handler: RecordingHandler
) -> None:
    store = SQLiteJobStore(async_session_factory)
    fake = FakeIppPrinter(job_script=[3, 5])  # sticks at 5: the page is printing
    page_id = uuid4()
    async with _running(_side(store, fake, page_id)) as first:
        jid = await first.queue.submit_page_job(page_id, payload(), api_key_id=None, source_ip=None)

        async def _started() -> bool:
            return (await _row(store, jid)).result == {
                "phase": "tracking",
                "started": True,
                "ipp_job_id": 1,
            }

        await _until(_started)
        await _until(lambda: handler.names(jid) == ["started"])
    assert (await _row(store, jid)).state == DbJobState.PRINTING.value  # stop() left it

    fake.job_script = [5, 9]
    async with _running(_side(store, fake, page_id)) as second:
        job = await second.queue.wait_for_job(str(jid), timeout_s=TEST_TIMEOUT_S)
        assert job.state == JobState.COMPLETED
        await _wait_db(store, jid, DbJobState.DONE.value)
        await _until(lambda: second.page.own_job_ids == set())
        await _until(lambda: handler.names(jid) == ["started", "completed"])
    assert handler.names(jid) == ["started", "completed"]  # once each, across both runs
    assert [r.operation for r in fake.received].count("Print-Job") == 1


async def test_resume_asks_the_printer_before_tracking(
    store: JobStore, handler: RecordingHandler
) -> None:
    """One Get-Jobs cross-check per printer, before the first Get-Job-Attributes."""
    fake = FakeIppPrinter(job_script=[3, 3, 3, 3])
    page_id = uuid4()
    first_run = _side(store, fake, page_id)
    async with _running(first_run):
        jid = await first_run.queue.submit_page_job(
            page_id, payload(), api_key_id=None, source_ip=None
        )
        await _tracked_in_db(store, jid)
    fake.received.clear()
    fake.job_script = [3, 9]
    async with _running(_side(store, fake, page_id)) as second:
        await second.queue.wait_for_job(str(jid), timeout_s=TEST_TIMEOUT_S)
    ops = [r.operation for r in fake.received]
    assert ops.count("Get-Jobs") == 1
    assert ops.index("Get-Jobs") < ops.index("Get-Job-Attributes")
    assert "Print-Job" not in ops


async def test_restart_does_not_adopt_a_foreign_job_that_reuses_the_ipp_job_id(
    store: JobStore, handler: RecordingHandler
) -> None:
    """The printer rebooted while the hub was down and gave the id to another client's job.

    The listed job has the id but not the hub's job name: it is not ours. The hub's job is
    settled like a job the printer forgot, and nothing is sent to the foreign job.
    """
    fake = FakeIppPrinter(job_script=[5, 5, 5])
    page_id = uuid4()
    first_run = _side(store, fake, page_id)
    async with _running(first_run):
        jid = await first_run.queue.submit_page_job(
            page_id, payload(), api_key_id=None, source_ip=None
        )
        await _tracked_in_db(store, jid)
        await _until(lambda: handler.names(jid) == ["started"])
    ipp_id = (await _row(store, jid)).result["ipp_job_id"]
    fake.reuse_job_id_for_foreign_job(ipp_id)  # the foreign job is printing, state 5
    fake.received.clear()
    async with _running(_side(store, fake, page_id)) as second:
        job = await second.queue.wait_for_job(str(jid), timeout_s=TEST_TIMEOUT_S)
        await _wait_db(store, jid, DbJobState.FAILED.value)  # the write follows the event
        await _until(lambda: "ended" in handler.names(jid))
    assert job.state == JobState.FAILED
    row = await _row(store, jid)
    assert row.error is not None and row.error.startswith("interrupted")
    assert handler.ended(jid)["error_code"] == "interrupted"
    assert handler.ended(jid)["started"] is True  # as stored
    assert "Cancel-Job" not in [r.operation for r in fake.received]
    assert "completed" not in handler.names(jid)


async def test_restart_does_not_cancel_a_foreign_job_when_a_cancel_waited(
    store: JobStore, handler: RecordingHandler
) -> None:
    """Printer not listable at recovery: the identity check precedes any Cancel-Job."""
    fake = FakeIppPrinter(job_script=[5, 5, 5])
    page_id = uuid4()
    first_run = _side(store, fake, page_id)
    async with _running(first_run):
        jid = await first_run.queue.submit_page_job(
            page_id, payload(), api_key_id=None, source_ip=None
        )
        await _tracked_in_db(store, jid)
    ipp_id = (await _row(store, jid)).result["ipp_job_id"]
    fake.reuse_job_id_for_foreign_job(ipp_id)
    fake.received.clear()
    transport = FailingTransport(httpx.ASGITransport(app=fake), "Get-Jobs", httpx.ConnectError)
    async with _running(_side(store, fake, page_id, transport=transport)) as second:
        await second.queue.cancel(str(jid))
        await second.queue.wait_for_job(str(jid), timeout_s=TEST_TIMEOUT_S)
        await _wait_db(store, jid, DbJobState.FAILED.value)
    assert "Cancel-Job" not in [r.operation for r in fake.received]


async def test_api_cancel_after_resume_waits_for_the_identity_check(
    store: JobStore, handler: RecordingHandler
) -> None:
    """Listing and Get-Job-Attributes both fail at restart, so the job cannot be verified.

    The id now belongs to a foreign job. An API cancel that arrives while the runner is
    tracking (not before it resumed) must not send Cancel-Job to that id.
    """
    fake = FakeIppPrinter(job_script=[5, 5, 5])
    page_id = uuid4()
    first_run = _side(store, fake, page_id)
    async with _running(first_run):
        jid = await first_run.queue.submit_page_job(
            page_id, payload(), api_key_id=None, source_ip=None
        )
        await _tracked_in_db(store, jid)
    ipp_id = (await _row(store, jid)).result["ipp_job_id"]
    fake.reuse_job_id_for_foreign_job(ipp_id)
    fake.received.clear()
    blind = FailingTransport(
        FailingTransport(httpx.ASGITransport(app=fake), "Get-Jobs", httpx.ConnectError),
        "Get-Job-Attributes",
        httpx.ConnectError,
    )
    async with _running(_side(store, fake, page_id, transport=blind)) as second:
        await _until(lambda: second.runner.is_tracking(jid))
        await _until(lambda: "Get-Job-Attributes" in [r.operation for r in fake.received])
        assert await second.queue.cancel(str(jid)) is True  # accepted, held back
        await asyncio.sleep(0.05)  # several polls, all failing: still unverified
    assert "Cancel-Job" not in [r.operation for r in fake.received]


async def test_api_cancel_of_a_verified_resumed_job_is_sent(
    store: JobStore, handler: RecordingHandler
) -> None:
    fake = FakeIppPrinter(job_script=[5, 5, 5])
    page_id = uuid4()
    first_run = _side(store, fake, page_id)
    async with _running(first_run):
        jid = await first_run.queue.submit_page_job(
            page_id, payload(), api_key_id=None, source_ip=None
        )
        await _tracked_in_db(store, jid)
    fake.received.clear()
    async with _running(_side(store, fake, page_id)) as second:
        await _until(lambda: second.runner.is_tracking(jid))
        await _until(lambda: "Get-Job-Attributes" in [r.operation for r in fake.received])
        assert await second.queue.cancel(str(jid)) is True
        await _until(lambda: "Cancel-Job" in [r.operation for r in fake.received])


async def test_restart_still_adopts_its_own_job(store: JobStore, handler: RecordingHandler) -> None:
    """Counter-case: the id is listed with the hub's own name and user, so it is resumed."""
    fake = FakeIppPrinter(job_script=[5, 5, 5])
    page_id = uuid4()
    first_run = _side(store, fake, page_id)
    async with _running(first_run):
        jid = await first_run.queue.submit_page_job(
            page_id, payload(), api_key_id=None, source_ip=None
        )
        await _tracked_in_db(store, jid)
    fake.job_script = [5, 9]
    async with _running(_side(store, fake, page_id)) as second:
        job = await second.queue.wait_for_job(str(jid), timeout_s=TEST_TIMEOUT_S)
    assert job.state == JobState.COMPLETED


# ---------------------------------------------------------------------------- unknown outcome


@pytest.mark.parametrize(
    "result",
    [
        {"phase": "uploading", "started": False},
        {"phase": "uploading", "started": True},
        {"phase": "uploading", "started": False, "ipp_job_id": 5},  # id or not: R1
        {"phase": "tracking", "started": False},  # no IPP job id
        {"started": False},
        None,
    ],
    ids=[
        "uploading",
        "uploading-started",
        "uploading-with-id",
        "tracking-no-id",
        "no-phase",
        "no-result",
    ],
)
async def test_restart_without_ipp_job_id_unknown_outcome(
    store: JobStore, handler: RecordingHandler, result: dict[str, Any] | None
) -> None:
    """R1: the printer may have taken the upload; the hub does not know, and says so."""
    fake = FakeIppPrinter()
    page_id = uuid4()
    jid = await _seed_printing(store, page_id, result)
    async with _running(_side(store, fake, page_id)):
        pass
    row = await _row(store, jid)
    assert row.state == DbJobState.FAILED_RESTART.value
    assert handler.names(jid) == ["unknown"]
    assert fake.received == []  # nothing to ask the printer about, nothing sent


async def test_unknown_outcome_handler_failure_does_not_stop_startup(
    store: JobStore, handler: RecordingHandler
) -> None:
    async def boom(_job_id: UUID) -> None:
        raise RuntimeError("handler bug")

    handler.on_unknown = boom  # type: ignore[method-assign]
    page_id = uuid4()
    jid = await _seed_printing(store, page_id, {"phase": "uploading", "started": False})
    queued = DbJob(
        id=uuid4(), printer_id=page_id, template_key=None, payload=payload().model_dump()
    )
    await store.save_queued(queued)
    async with _running(_side(store, FakeIppPrinter(job_script=[9]), page_id)) as side:
        await side.queue.wait_for_job(str(queued.id), timeout_s=TEST_TIMEOUT_S)
    assert (await _row(store, jid)).state == DbJobState.FAILED_RESTART.value


# ---------------------------------------------------------------------------- queued jobs


async def test_restart_requeues_queued_page_jobs(handler: RecordingHandler) -> None:
    rendered: list[str] = []

    def render(p: Any) -> bytes:
        rendered.append(p.job_name)
        return b"%PDF-1.4\n%%EOF\n"

    store = MemoryJobStore()
    fake = FakeIppPrinter(job_script=[9])
    page_id = uuid4()
    with registered(handler, render=render):
        first = _side(store, fake, page_id)
        async with _running(first):
            await first.queue.pause_printer(page_id, reason="user", source="user")
            jid = await first.queue.submit_page_job(
                page_id, payload(), api_key_id=None, source_ip=None
            )
        assert (await _row(store, jid)).state == DbJobState.QUEUED.value
        assert rendered == []  # rendering happens at send, not at recovery either
        async with _running(_side(store, fake, page_id)) as second:
            job = await second.queue.wait_for_job(str(jid), timeout_s=TEST_TIMEOUT_S)
            assert job.state == JobState.COMPLETED
        assert len(rendered) == 1
    assert [r.operation for r in fake.received].count("Print-Job") == 1


async def test_resumed_job_goes_before_queued_ones(handler: RecordingHandler) -> None:
    store = MemoryJobStore()
    fake = FakeIppPrinter(job_script=[3, 3, 3])
    page_id = uuid4()
    first = _side(store, fake, page_id)
    async with _running(first):
        a = await first.queue.submit_page_job(page_id, payload(), api_key_id=None, source_ip=None)
        await _tracked_in_db(store, a)
        b = await first.queue.submit_page_job(page_id, payload(), api_key_id=None, source_ip=None)
    fake.job_script = [5, 9]
    async with _running(_side(store, fake, page_id)) as second:
        await second.queue.wait_for_job(str(b), timeout_s=TEST_TIMEOUT_S)
        assert (await _row(store, a)).state == DbJobState.DONE.value
        assert handler.names(a) == ["started", "completed"]
    assert [r.operation for r in fake.received].count("Print-Job") == 2  # a once, b once


# ---------------------------------------------------------------------------- the printer forgot


async def test_printer_forgot_job(handler: RecordingHandler) -> None:
    store = MemoryJobStore()
    fake = FakeIppPrinter(job_script=[5])
    page_id = uuid4()
    async with _running(_side(store, fake, page_id)) as side:
        jid = await side.queue.submit_page_job(page_id, payload(), api_key_id=None, source_ip=None)

        async def _started() -> bool:
            return bool(((await _row(store, jid)).result or {}).get("started"))

        await _until(_started)
        fake.forget_jobs()
        job = await side.queue.wait_for_job(str(jid), timeout_s=TEST_TIMEOUT_S)
    assert job.state == JobState.FAILED and job.error_code == "interrupted"
    await _wait_db(store, jid, DbJobState.FAILED.value)
    row = await _row(store, jid)
    assert (row.result or {})["started"] is True
    assert handler.ended(jid) == {"state": "failed", "started": True, "error_code": "interrupted"}


@pytest.mark.parametrize("started", [False, True])
async def test_restart_after_printer_forgot_job(
    store: JobStore, handler: RecordingHandler, started: bool
) -> None:
    """The printer rebooted too: neither listed nor answering ends the job ``interrupted``,
    with ``started`` as persisted, at startup."""
    fake = FakeIppPrinter(job_script=[3])
    page_id = uuid4()
    jid = await _seed_printing(
        store, page_id, {"phase": "tracking", "ipp_job_id": 77, "started": started}
    )
    async with _running(_side(store, fake, page_id)) as side:
        job = await side.queue.wait_for_job(str(jid), timeout_s=TEST_TIMEOUT_S)
        assert job.state == JobState.FAILED and job.error_code == "interrupted"
        await _wait_db(store, jid, DbJobState.FAILED.value)  # before stop() can cut the write
        await _until(lambda: handler.names(jid) == ["ended"])
    row = await _row(store, jid)
    assert (row.result or {})["started"] is started
    assert handler.ended(jid) == {
        "state": "failed",
        "started": started,
        "error_code": "interrupted",
    }
    ops = [r.operation for r in fake.received]
    assert "Print-Job" not in ops
    # Exactly the cross-check lookup, no poll: the job ended at startup (spec 11.5).
    assert ops.count("Get-Jobs") == 1 and ops.count("Get-Job-Attributes") == 1


# ---------------------------------------------------------------------------- unreachable


async def test_unreachable_during_tracking_keeps_waiting(handler: RecordingHandler) -> None:
    store = MemoryJobStore()
    fake = FakeIppPrinter(job_script=[3])
    page_id = uuid4()
    flaky = FlakyTransport(
        httpx.ASGITransport(app=fake),
        {
            "Get-Job-Attributes": [httpx.ConnectError] * 20,
            "Cancel-Job": [httpx.ConnectError] * 2,  # the cancel is retried by the polling
        },
    )
    async with _running(_side(store, fake, page_id, flaky)) as side:
        jid = await side.queue.submit_page_job(page_id, payload(), api_key_id=None, source_ip=None)
        await _until(lambda: flaky.failures.count("Get-Job-Attributes") >= 20)
        assert (await _row(store, jid)).state == DbJobState.PRINTING.value
        assert (await side.queue.get(jid)).state == JobState.PRINTING
        assert handler.names(jid) == []  # no outcome, not even a started
        assert await side.queue.cancel(str(jid)) is True  # still cancellable
        job = await side.queue.wait_for_job(str(jid), timeout_s=TEST_TIMEOUT_S)
        assert job.state == JobState.CANCELLED
        await _wait_db(store, jid, DbJobState.CANCELLED.value)
    assert flaky.failures.count("Cancel-Job") == 2
    assert [r.operation for r in fake.received].count("Cancel-Job") == 1


async def test_unreachable_at_restart_keeps_waiting(
    store: JobStore, handler: RecordingHandler
) -> None:
    """R3: the cross-check itself cannot reach the printer. The jobs are not failed; the
    tracking resumes and the unreachable-keeps-waiting rule applies."""
    fake = FakeIppPrinter(job_script=[5])
    page_id = uuid4()
    first = _side(store, fake, page_id)
    async with _running(first):
        jid = await first.queue.submit_page_job(page_id, payload(), api_key_id=None, source_ip=None)

        async def _started() -> bool:
            return bool(((await _row(store, jid)).result or {}).get("started"))

        await _until(_started)
        await _until(lambda: handler.names(jid) == ["started"])
    fake.job_script = [5, 9]
    flaky = FlakyTransport(
        httpx.ASGITransport(app=fake),
        {"Get-Jobs": [httpx.ConnectError], "Get-Job-Attributes": [httpx.ConnectError] * 5},
    )
    async with _running(_side(store, fake, page_id, flaky)) as side:
        job = await side.queue.wait_for_job(str(jid), timeout_s=TEST_TIMEOUT_S)
        assert job.state == JobState.COMPLETED
        await _wait_db(store, jid, DbJobState.DONE.value)
        await _until(lambda: handler.names(jid) == ["started", "completed"])
    assert flaky.failures.count("Get-Jobs") == 1 and flaky.failures.count("Get-Job-Attributes") == 5
    assert handler.names(jid) == ["started", "completed"]  # started was reported by the first run


# ---------------------------------------------------------------------------- pause


async def test_resume_ignores_user_pause(store: JobStore, handler: RecordingHandler) -> None:
    """The job is at the printer already: a user pause stops new jobs, not the tracking of a
    running one — and the pause itself stays."""
    from datetime import UTC, datetime

    fake = FakeIppPrinter(job_script=[3])
    page_id = uuid4()
    first = _side(store, fake, page_id)
    async with _running(first):
        jid = await first.queue.submit_page_job(page_id, payload(), api_key_id=None, source_ip=None)
        await _tracked_in_db(store, jid)
    fake.job_script = [5, 9]
    second = _side(store, fake, page_id)
    async with _running(second, initially_paused={page_id: datetime.now(UTC)}):
        job = await second.queue.wait_for_job(str(jid), timeout_s=TEST_TIMEOUT_S)
        assert job.state == JobState.COMPLETED
        info = second.queue.pause_info(page_id)
        assert info is not None and info.source == "user"


async def test_resumed_job_can_be_cancelled(store: JobStore, handler: RecordingHandler) -> None:
    fake = FakeIppPrinter(job_script=[3])
    page_id = uuid4()
    first = _side(store, fake, page_id)
    async with _running(first):
        jid = await first.queue.submit_page_job(page_id, payload(), api_key_id=None, source_ip=None)
        await _tracked_in_db(store, jid)
    second = _side(store, fake, page_id)
    async with _running(second):
        await _until(lambda: second.runner.is_tracking(jid))
        assert await second.queue.cancel(str(jid)) is True
        job = await second.queue.wait_for_job(str(jid), timeout_s=TEST_TIMEOUT_S)
        assert job.state == JobState.CANCELLED
    assert [r.operation for r in fake.received].count("Cancel-Job") == 1


class _GatedGetJobs(httpx.AsyncBaseTransport):
    """Holds every Get-Jobs request until ``gate`` is set (the cross-check is "in flight")."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self.inner = inner
        self.gate = asyncio.Event()
        self.entered = asyncio.Event()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        msg, _ = decode(await request.aread())
        if msg.code == OPERATIONS["Get-Jobs"]:
            self.entered.set()
            await self.gate.wait()
        return await self.inner.handle_async_request(request)


async def test_cancel_before_the_crosscheck_completes(
    store: JobStore, handler: RecordingHandler
) -> None:
    """A recovered job is cancellable while the worker is still asking the printer."""
    fake = FakeIppPrinter(job_script=[3])
    page_id = uuid4()
    first = _side(store, fake, page_id)
    async with _running(first):
        jid = await first.queue.submit_page_job(page_id, payload(), api_key_id=None, source_ip=None)
        await _tracked_in_db(store, jid)
    gated = _GatedGetJobs(httpx.ASGITransport(app=fake))
    async with _running(_side(store, fake, page_id, gated)) as second:
        async with asyncio.timeout(TEST_TIMEOUT_S):
            await gated.entered.wait()
        assert [r.operation for r in fake.received].count("Cancel-Job") == 0
        assert await second.queue.cancel(str(jid)) is True
        gated.gate.set()
        job = await second.queue.wait_for_job(str(jid), timeout_s=TEST_TIMEOUT_S)
        assert job.state == JobState.CANCELLED
        await _wait_db(store, jid, DbJobState.CANCELLED.value)
        await _until(lambda: handler.names(jid)[-1:] == ["ended"])
    assert handler.ended(jid) == {"state": "cancelled", "started": False, "error_code": "cancelled"}
    assert [r.operation for r in fake.received].count("Cancel-Job") == 1


async def test_restart_with_a_printer_that_is_no_page_printer_any_more(
    store: JobStore, handler: RecordingHandler
) -> None:
    """Disabled, deleted or re-typed printer: its in-flight page job cannot be tracked, so
    the outcome is unknown (R1). A job of a loaded page printer is not touched."""
    fake = FakeIppPrinter(job_script=[3])
    page_id, gone_id = uuid4(), uuid4()
    orphan = await _seed_printing(
        store, gone_id, {"phase": "tracking", "ipp_job_id": 3, "started": True}
    )
    mine = await _seed_printing(
        store, page_id, {"phase": "tracking", "ipp_job_id": 9, "started": False}
    )
    async with _running(_side(store, fake, page_id)):
        await _wait_db(store, orphan, DbJobState.FAILED_RESTART.value)
        assert handler.names(orphan) == ["unknown"]
        assert (await _row(store, orphan)).error == "page_outcome_unknown"
        assert handler.names(mine) == []  # its own printer's job went the resume way


async def test_hanging_unknown_handler_does_not_block_startup(
    store: JobStore, handler: RecordingHandler, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import print_queue

    monkeypatch.setattr(print_queue, "_ON_UNKNOWN_TIMEOUT_S", 0.05)
    release = asyncio.Event()

    async def hang(_job_id: UUID) -> None:
        await release.wait()

    handler.on_unknown = hang  # type: ignore[method-assign]
    page_id = uuid4()
    jid = await _seed_printing(store, page_id, {"phase": "uploading", "started": False})
    queued = DbJob(
        id=uuid4(), printer_id=page_id, template_key=None, payload=payload().model_dump()
    )
    await store.save_queued(queued)
    side = _side(store, FakeIppPrinter(job_script=[9]), page_id)
    async with asyncio.timeout(TEST_TIMEOUT_S):
        await side.queue.start()  # returns although the handler never does
    try:
        job = await side.queue.wait_for_job(str(queued.id), timeout_s=TEST_TIMEOUT_S)
        assert job.state == JobState.COMPLETED
    finally:
        release.set()
        await side.queue.stop(timeout_s=2)
    assert (await _row(store, jid)).state == DbJobState.FAILED_RESTART.value


# ---------------------------------------------------------------------------- store


async def test_mark_interrupted_leaves_page_jobs_alone(store: JobStore) -> None:
    printer = uuid4()
    tape = DbJob(printer_id=printer, template_key=None, payload={})
    page = DbJob(printer_id=printer, template_key=None, payload=payload().model_dump())
    for row in (tape, page):
        await store.save_queued(row)
        assert await store.mark_printing(row.id)
    assert await store.mark_interrupted(printer) == 1  # R2: only the tape job
    assert (await _row(store, tape.id)).state == DbJobState.FAILED_RESTART.value
    assert (await _row(store, tape.id)).error == "printer_interrupted"
    assert (await _row(store, page.id)).state == DbJobState.PRINTING.value


async def test_list_page_jobs_in_flight(store: JobStore) -> None:
    printer, other = uuid4(), uuid4()
    mk = lambda pid, pl: DbJob(printer_id=pid, template_key=None, payload=pl)  # noqa: E731
    page = mk(printer, payload().model_dump())
    queued_page = mk(printer, payload().model_dump())
    tape = mk(printer, {})
    elsewhere = mk(other, payload().model_dump())
    for row in (page, queued_page, tape, elsewhere):
        await store.save_queued(row)
    for row in (page, tape, elsewhere):
        assert await store.mark_printing(row.id)
    found = await store.list_page_jobs_in_flight(printer)
    assert [j.id for j in found] == [page.id]
    everywhere = await store.list_page_jobs_in_flight()  # every printer
    assert {j.id for j in everywhere} == {page.id, elsewhere.id}


async def test_mark_failed_restart(store: JobStore) -> None:
    printer = uuid4()
    row = DbJob(printer_id=printer, template_key=None, payload=payload().model_dump())
    await store.save_queued(row)
    assert await store.mark_printing(row.id)
    await store.mark_failed_restart(row.id, "page_outcome_unknown")
    got = await _row(store, row.id)
    assert got.state == DbJobState.FAILED_RESTART.value
    assert got.error == "page_outcome_unknown"
    assert got.finished_at is not None
    await store.mark_failed_restart(row.id, "again")  # terminal: unchanged
    assert (await _row(store, row.id)).error == "page_outcome_unknown"
    await store.mark_failed_restart(uuid4(), "x")  # unknown id: silent no-op


# ---------------------------------------------------------------------------- recovery check


@contextmanager
def _check(fn: Any) -> Iterator[None]:
    page_jobs.register_recovery_check("calibration_page", fn)
    try:
        yield
    finally:
        page_jobs.unregister_recovery_check("calibration_page", fn)


async def _queued_row(store: JobStore, page_id: UUID) -> UUID:
    row = DbJob(id=uuid4(), printer_id=page_id, template_key=None, payload=payload().model_dump())
    await store.save_queued(row)
    return row.id


@pytest.mark.parametrize("allowed", [True, False])
async def test_recovery_asks_the_kind_before_it_requeues_a_row(
    handler: RecordingHandler, allowed: bool
) -> None:
    """263-47: a ``queued`` row prints after a restart only if its kind agrees (a sheet page:
    its cells are still reserved for it). Refused: the row ends ``failed`` (never started) and
    the handler hears it; nothing reaches the printer."""
    store = MemoryJobStore()
    fake = FakeIppPrinter(job_script=[9])
    page_id = uuid4()
    jid = await _queued_row(store, page_id)
    asked: list[UUID] = []

    async def check(job_id: UUID, _p: Any) -> bool:
        asked.append(job_id)
        return allowed

    with _check(check):
        async with _running(_side(store, fake, page_id)) as side:
            if allowed:
                job = await side.queue.wait_for_job(str(jid), timeout_s=TEST_TIMEOUT_S)
                assert job.state == JobState.COMPLETED
            else:
                await _wait_db(store, jid, DbJobState.FAILED.value)
                row = await _row(store, jid)
                assert (row.error or "").startswith("recovery_refused:")
                assert (row.result or {}).get("started") is False
                assert handler.ended(jid) == {
                    "state": "failed",
                    "started": False,
                    "error_code": "recovery_refused",
                }
                assert not side.queue.has_job(jid)
    assert asked == [jid]
    assert [r.operation for r in fake.received].count("Print-Job") == (1 if allowed else 0)


async def test_a_recovery_check_that_raises_leaves_the_row_unprinted_and_queued(
    handler: RecordingHandler,
) -> None:
    store = MemoryJobStore()
    fake = FakeIppPrinter(job_script=[9])
    page_id = uuid4()
    jid = await _queued_row(store, page_id)

    async def check(_j: UUID, _p: Any) -> bool:
        raise RuntimeError("database is locked")

    with _check(check):
        async with _running(_side(store, fake, page_id)) as side:
            await asyncio.sleep(0.1)
            assert not side.queue.has_job(jid)
    assert (await _row(store, jid)).state == DbJobState.QUEUED.value  # the next start asks again
    assert "Print-Job" not in [r.operation for r in fake.received]
    assert handler.names(jid) == []
