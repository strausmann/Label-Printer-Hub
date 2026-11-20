# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Restart recovery renders a recovered job when the worker takes it, not in ``start()`` (#168).

``start()`` only wraps the stored rows; each wrapper renders on its own turn. A job cancelled
before or during its render never prints, and a render that fails after a cancel leaves the
row ``cancelled``. All waits are bounded.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from app.models.job import Job as DbJob
from app.services.job_lifecycle import JobState
from app.services.job_store import JobStore, MemoryJobStore
from app.services.job_store_sqlite import SQLiteJobStore
from app.services.print_queue import PrinterWorkerState, PrintQueue
from PIL import Image

TEST_TIMEOUT_S = 10.0
_TAPE_ID = UUID("eeeeeeee-0000-0000-0000-000000000168")
_BASE = datetime(2026, 11, 1, tzinfo=UTC)

_RENDERABLE: dict[str, Any] = {
    "label_data": {
        "title": "Test",
        "primary_id": "T-001",
        "qr_payload": "https://example.invalid",
        "source_app": "manual",
        "secondary": [],
        "items": [],
    },
    "content_type": "qr_two_lines",
    "rendered_tape_mm": 24,
    "tape_mm": 24,
}


class _TapePrinter:
    """Records single prints by their ``tag`` option and each batch by its images' widths."""

    def __init__(self) -> None:
        self.id = _TAPE_ID
        self.printed: list[str] = []
        self.printed_widths: list[int] = []
        self.batches: list[list[int]] = []
        self.fail_next: Exception | None = None

    async def print_image(self, image: Image.Image, *, tape_mm: int, **options: Any) -> None:
        if self.fail_next is not None:
            exc, self.fail_next = self.fail_next, None
            raise exc
        self.printed.append(str(options.get("tag")))
        self.printed_widths.append(image.width)

    async def print_images(
        self, images: list[Image.Image], *, tape_mm: int, **options: Any
    ) -> None:
        self.batches.append([img.width for img in images])


class _Renders:
    """Stands in for ``_rerender_from_db_payload``: counts calls, draws a width per row.

    The width of row *n* is ``100 + n`` (``options.width``), so a print shows which row it was.
    ``fail`` holds the tags whose render raises ``ValueError``; ``hold`` holds the tags whose
    render waits on ``release`` (a thread event: the render runs in a worker thread).
    """

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail: set[str] = set()
        self.hold: set[str] = set()
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self, _queue: PrintQueue, payload: dict[str, Any]) -> Image.Image:
        options = payload.get("options") or {}
        tag = str(options.get("tag"))
        self.calls.append(tag)
        if tag in self.hold:
            self.entered.set()
            assert self.release.wait(TEST_TIMEOUT_S)
        if tag in self.fail:
            raise ValueError("boom")
        return Image.new("1", (int(options.get("width", 100)), 76))


@pytest_asyncio.fixture
async def async_session_factory(tmp_path: Any) -> AsyncIterator[Any]:
    import app.models  # noqa: F401 — registers all models with SQLModel.metadata
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlmodel import SQLModel

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'lazy.db'}",
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


@pytest.fixture
def renders(monkeypatch: pytest.MonkeyPatch) -> _Renders:
    fake = _Renders()

    def _patched(queue: PrintQueue, payload: dict[str, Any]) -> Image.Image:
        return fake(queue, payload)

    monkeypatch.setattr(PrintQueue, "_rerender_from_db_payload", _patched)
    return fake


async def _until(predicate: Callable[[], Any]) -> None:
    async with asyncio.timeout(TEST_TIMEOUT_S):
        while True:
            value = predicate()
            if asyncio.iscoroutine(value):
                value = await value
            if value:
                return
            await asyncio.sleep(0.005)


async def _rows(store: JobStore, count: int, *, run_id: UUID | None = None) -> list[UUID]:
    """*count* queued rows ``r1``…``rN`` in this order (``created_at`` carries the order)."""
    ids: list[UUID] = []
    for n in range(1, count + 1):
        payload: dict[str, Any] = {**_RENDERABLE, "options": {"tag": f"r{n}", "width": 100 + n}}
        if run_id is not None:
            payload["tape_run"] = {"run_id": str(run_id), "awaits_confirmation": False}
        row = DbJob(
            id=uuid4(),
            printer_id=_TAPE_ID,
            template_key=None,
            payload=payload,
            created_at=_BASE + timedelta(seconds=n),
        )
        await store.save_queued(row)
        ids.append(row.id)
    return ids


async def _state(store: JobStore, job_id: UUID) -> str:
    row = await store.get(job_id)
    assert row is not None
    return row.state


async def _error(store: JobStore, job_id: UUID) -> str | None:
    row = await store.get(job_id)
    assert row is not None
    return row.error


async def test_start_renders_nothing(store: JobStore, renders: _Renders) -> None:
    await _rows(store, 200)
    queue = PrintQueue([_TapePrinter()], store=store)
    await queue.start()
    try:
        assert len(renders.calls) == 0
    finally:
        await queue.stop()


async def test_recovered_jobs_keep_their_order(store: JobStore, renders: _Renders) -> None:
    await _rows(store, 200)
    fake = _TapePrinter()
    queue = PrintQueue([fake], store=store)
    await queue.start()
    try:
        late = uuid4()
        await store.save_queued(
            DbJob(id=late, printer_id=_TAPE_ID, payload={**_RENDERABLE, "options": {"tag": "late"}})
        )
        await queue.submit_with_id(late, _TAPE_ID, Image.new("1", (90, 76)), tape_mm=24, tag="late")
        await _until(lambda: len(fake.printed) == 201)
        assert fake.printed == [f"r{n}" for n in range(1, 201)] + ["late"]
        assert len(renders.calls) == 200
    finally:
        await queue.stop()


async def test_paused_printer_prints_no_recovered_job(store: JobStore, renders: _Renders) -> None:
    await _rows(store, 5)
    fake = _TapePrinter()
    queue = PrintQueue([fake], store=store)
    await queue.start(initially_paused={_TAPE_ID: _BASE})
    try:
        await asyncio.sleep(0.5)
        assert renders.calls == []
        assert fake.printed == []
    finally:
        await queue.stop()


async def test_failed_rerender_fails_only_that_job(store: JobStore, renders: _Renders) -> None:
    ids = await _rows(store, 4)
    renders.fail = {"r3"}
    fake = _TapePrinter()
    queue = PrintQueue([fake], store=store)
    await queue.start()
    try:
        await _until(lambda: len(fake.printed) == 3)
        await _until(lambda: _done(store, ids[2], "failed"))
        assert fake.printed == ["r1", "r2", "r4"]
        assert await _error(store, ids[2]) == "recovery_rerender_failed: ValueError"
        assert queue._jobs[str(ids[2])].state == JobState.FAILED
    finally:
        await queue.stop()


async def _done(store: JobStore, job_id: UUID, state: str) -> bool:
    return await _state(store, job_id) == state


async def test_cancel_before_rendering(store: JobStore, renders: _Renders) -> None:
    ids = await _rows(store, 3)
    fake = _TapePrinter()
    queue = PrintQueue([fake], store=store)
    await queue.start()  # the worker has not run yet: no await between its creation and here
    try:
        assert await queue.cancel(str(ids[0]))
        await _until(lambda: len(fake.printed) == 2)
        assert "r1" not in renders.calls
        assert fake.printed == ["r2", "r3"]
        assert await _state(store, ids[0]) == "cancelled"
    finally:
        await queue.stop()


async def _cancel_while_rendering(store: JobStore, renders: _Renders, *, fails: bool) -> None:
    ids = await _rows(store, 2)
    renders.hold = {"r1"}
    if fails:
        renders.fail = {"r1"}
    fake = _TapePrinter()
    queue = PrintQueue([fake], store=store)
    await queue.start()
    try:
        await _until(renders.entered.is_set)
        assert await queue.cancel(str(ids[0]))
        renders.release.set()
        await _until(lambda: fake.printed == ["r2"])
        assert "r1" not in fake.printed
        assert queue._jobs[str(ids[0])].state == JobState.CANCELLED
        assert await _state(store, ids[0]) == "cancelled"
    finally:
        renders.release.set()
        await queue.stop()


async def test_cancel_during_the_render_skips_the_job(store: JobStore, renders: _Renders) -> None:
    await _cancel_while_rendering(store, renders, fails=False)


async def test_cancel_during_a_failing_render_stays_cancelled(
    store: JobStore, renders: _Renders
) -> None:
    await _cancel_while_rendering(store, renders, fails=True)


async def test_recovered_run_skips_a_failed_member(store: JobStore, renders: _Renders) -> None:
    ids = await _rows(store, 3, run_id=uuid4())
    renders.fail = {"r2"}
    fake = _TapePrinter()
    queue = PrintQueue([fake], store=store)
    await queue.start()
    try:
        await _until(lambda: _done(store, ids[2], "done"))
        assert fake.batches == [[101, 103]]
        assert await _state(store, ids[0]) == "done"
        assert await _state(store, ids[1]) == "failed"
        assert await _error(store, ids[1]) == "recovery_rerender_failed: ValueError"
    finally:
        await queue.stop()


async def test_recovered_run_member_cancelled_during_render_is_skipped(
    store: JobStore, renders: _Renders
) -> None:
    ids = await _rows(store, 3, run_id=uuid4())
    renders.hold = {"r2"}
    fake = _TapePrinter()
    queue = PrintQueue([fake], store=store)
    await queue.start()
    try:
        await _until(renders.entered.is_set)
        assert await queue.cancel(str(ids[1]))
        renders.release.set()
        await _until(lambda: _done(store, ids[2], "done"))
        assert fake.batches == [[101, 103]]
        assert await _state(store, ids[1]) == "cancelled"
    finally:
        renders.release.set()
        await queue.stop()


async def test_retry_of_a_recovered_job_renders(store: JobStore, renders: _Renders) -> None:
    from app.printer_backends.exceptions import PrinterOfflineError

    ids = await _rows(store, 1)
    fake = _TapePrinter()
    fake.fail_next = PrinterOfflineError("offline")
    queue = PrintQueue([fake], store=store)
    await queue.start()
    try:
        await _until(lambda: queue._jobs[str(ids[0])].state == JobState.FAILED)
        # The printer error pauses the queue after the row is written.
        await _until(lambda: queue._worker_states[_TAPE_ID] == PrinterWorkerState.PAUSED)
        await queue.resume_printer(_TAPE_ID)
        # The picture of a failed label may be gone (``_drop_pictures``): the retry draws it.
        queue._jobs[str(ids[0])].image_payload = None
        # The retry route's way: a new row first, then the queue takes it. (A queue-only copy
        # without a row is vetoed by the store, as a cancelled-then-removed job is.)
        original = await store.get(ids[0])
        assert original is not None
        retried = DbJob(
            printer_id=_TAPE_ID, payload={**original.payload, "retry_of": str(original.id)}
        )
        await store.save_queued(retried)
        await queue.enqueue_persisted(retried)
        await _until(lambda: fake.printed == ["r1"])
        assert fake.printed_widths == [101]
        assert renders.calls == ["r1", "r1"]
    finally:
        await queue.stop()


async def test_job_without_picture_or_renderer_is_not_a_render_failure(
    store: JobStore, renders: _Renders
) -> None:
    """A queued job with neither a picture nor a renderer (the picture was dropped) is not
    drawn: the worker handles it as before #168 (no picture -> ``RuntimeError``), never as a
    failed re-render."""
    fake = _TapePrinter()
    queue = PrintQueue([fake], store=store)
    await queue.start()
    try:
        job_id = uuid4()
        await store.save_queued(
            DbJob(id=job_id, printer_id=_TAPE_ID, payload={**_RENDERABLE, "options": {"tag": "x"}})
        )
        await queue.submit_with_id(job_id, _TAPE_ID, Image.new("1", (90, 76)), tape_mm=24, tag="x")
        job = queue._jobs[str(job_id)]
        assert await queue._materialise(job) is True
        assert job.image_payload is not None
        job.image_payload = None
        assert job.rerender is None
        assert await queue._materialise(job) is True
        assert job.state == JobState.QUEUED
        assert renders.calls == []
    finally:
        await queue.stop()


async def test_render_failure_whose_row_write_fails_keeps_the_worker(
    store: JobStore, renders: _Renders, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The store refusing the ``failed`` write does not end the worker: the next job prints."""
    ids = await _rows(store, 2)
    renders.fail = {"r1"}
    real = store.mark_failed

    async def _broken(job_id: UUID, error: str) -> None:
        if error.startswith("recovery_rerender_failed"):
            raise OSError("disk full")
        await real(job_id, error)

    monkeypatch.setattr(store, "mark_failed", _broken)
    fake = _TapePrinter()
    queue = PrintQueue([fake], store=store)
    await queue.start()
    try:
        await _until(lambda: fake.printed == ["r2"])
        # The row stays ``queued``; the in-memory claim is gone, so a later recovery of this
        # printer (a remove and re-add) takes the row again instead of skipping it.
        assert await _state(store, ids[0]) == "queued"
        assert str(ids[0]) not in queue._jobs
    finally:
        await queue.stop()


async def test_pause_during_the_render_holds_the_job(store: JobStore, renders: _Renders) -> None:
    """A pause that lands while a recovered job is drawn is honoured before the job is taken."""
    ids = await _rows(store, 2)
    renders.hold = {"r1"}
    fake = _TapePrinter()
    queue = PrintQueue([fake], store=store)
    await queue.start()
    try:
        await _until(renders.entered.is_set)
        await queue.pause_printer(_TAPE_ID, reason="user", source="user")
        renders.release.set()
        await _until(lambda: queue._jobs[str(ids[0])].image_payload is not None)
        await asyncio.sleep(0.1)  # the worker had its chance to take the job
        assert fake.printed == []
        assert await _state(store, ids[0]) == "queued"
        await queue.resume_printer(_TAPE_ID)
        await _until(lambda: fake.printed == ["r1", "r2"])
    finally:
        renders.release.set()
        await queue.stop()


async def test_removal_during_the_render_keeps_the_job_queued(
    store: JobStore, renders: _Renders
) -> None:
    """#224: a printer removed while a recovered job is drawn does not print it; its row stays
    ``queued``."""
    ids = await _rows(store, 1)
    renders.hold = {"r1"}
    fake = _TapePrinter()
    queue = PrintQueue([fake], store=store)
    await queue.start()
    try:
        await _until(renders.entered.is_set)
        removal = asyncio.create_task(queue.remove_printer(_TAPE_ID, timeout_s=TEST_TIMEOUT_S))
        await _until(lambda: queue._removing(_TAPE_ID))
        renders.release.set()
        await asyncio.wait_for(removal, TEST_TIMEOUT_S)
        assert fake.printed == []
        assert await _state(store, ids[0]) == "queued"
    finally:
        renders.release.set()
        await queue.stop()


async def test_pause_during_a_run_members_render_holds_the_group(
    store: JobStore, renders: _Renders
) -> None:
    """A pause that lands while a member of a recovered run is drawn is honoured before the
    group is taken; after the resume the whole group prints as one batch."""
    ids = await _rows(store, 3, run_id=uuid4())
    renders.hold = {"r2"}
    fake = _TapePrinter()
    queue = PrintQueue([fake], store=store)
    await queue.start()
    try:
        await _until(renders.entered.is_set)
        await queue.pause_printer(_TAPE_ID, reason="user", source="user")
        renders.release.set()
        await _until(lambda: queue._jobs[str(ids[2])].image_payload is not None)
        await asyncio.sleep(0.1)  # the worker had its chance to take the group
        assert fake.batches == []
        assert [await _state(store, i) for i in ids] == ["queued"] * 3
        await queue.resume_printer(_TAPE_ID)
        await _until(lambda: _done(store, ids[2], "done"))
        assert fake.batches == [[101, 102, 103]]
    finally:
        renders.release.set()
        await queue.stop()


async def test_removal_during_the_first_members_render_keeps_the_run_queued(
    store: JobStore, renders: _Renders
) -> None:
    """#224 with #168: a printer removed while the first member of a recovered run is drawn
    prints nothing of the run; every row stays ``queued``."""
    ids = await _rows(store, 3, run_id=uuid4())
    renders.hold = {"r1"}
    fake = _TapePrinter()
    queue = PrintQueue([fake], store=store)
    await queue.start()
    try:
        await _until(renders.entered.is_set)
        removal = asyncio.create_task(queue.remove_printer(_TAPE_ID, timeout_s=TEST_TIMEOUT_S))
        await _until(lambda: queue._removing(_TAPE_ID))
        renders.release.set()
        await asyncio.wait_for(removal, TEST_TIMEOUT_S)
        assert fake.batches == []
        assert [await _state(store, i) for i in ids] == ["queued"] * 3
    finally:
        renders.release.set()
        await queue.stop()


async def test_removal_during_a_later_members_render_keeps_the_run_queued(
    store: JobStore, renders: _Renders
) -> None:
    """As above, with the removal during the render of the second member."""
    ids = await _rows(store, 3, run_id=uuid4())
    renders.hold = {"r2"}
    fake = _TapePrinter()
    queue = PrintQueue([fake], store=store)
    await queue.start()
    try:
        await _until(renders.entered.is_set)
        removal = asyncio.create_task(queue.remove_printer(_TAPE_ID, timeout_s=TEST_TIMEOUT_S))
        await _until(lambda: queue._removing(_TAPE_ID))
        renders.release.set()
        await asyncio.wait_for(removal, TEST_TIMEOUT_S)
        assert fake.batches == []
        assert [await _state(store, i) for i in ids] == ["queued"] * 3
    finally:
        renders.release.set()
        await queue.stop()
