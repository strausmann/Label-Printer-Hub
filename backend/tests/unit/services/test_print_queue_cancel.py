"""Cancelling / clearing / retrying must reach the queue worker, not only the DB.

Issue #184: the REST routes only wrote the database, so the worker (which gates
on the in-memory job state) still sent a cancelled job to the printer, and a
retry copy only ran after a restart.  These tests drive ``PrintQueue`` with a
real job store and a recording printer to pin the contract:

* a cancelled waiting job is never sent to the backend and ends ``cancelled``
  both in memory and in the store;
* ``clear_queue`` does the same for every waiting job of the printer;
* cancel racing the worker's pick-up resolves to exactly one consistent outcome;
* ``enqueue_persisted`` (used by retry) prints without a restart and never
  enqueues the same row twice.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.models.job import Job
from app.models.job import JobState as DbJobState
from app.services.job_lifecycle import JobState
from app.services.job_store import MemoryJobStore
from app.services.layout_engine import LayoutEngine
from app.services.print_queue import PrintQueue
from PIL import Image

_PRINTER_ID = UUID("dddddddd-0000-0000-0000-000000000001")

_RENDERABLE_PAYLOAD: dict[str, Any] = {
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
    """Printer double that records every print and can hold one print open."""

    def __init__(self, printer_id: UUID = _PRINTER_ID) -> None:
        self.id = printer_id
        self.prints = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()  # by default prints finish immediately

    async def print_image(self, image: Image.Image, *, tape_mm: int, **options: Any) -> None:
        self.prints += 1
        self.entered.set()
        await self.release.wait()


async def _submit_persisted(
    queue: PrintQueue, store: MemoryJobStore, printer_id: UUID = _PRINTER_ID
) -> UUID:
    """Mirror PrintService.submit_print_job: persist the row, then enqueue it."""
    job_id = uuid4()
    await store.save_queued(Job(id=job_id, printer_id=printer_id, payload={}))
    await queue.submit_with_id(job_id, printer_id, Image.new("1", (300, 76)), tape_mm=12)
    return job_id


async def _settle() -> None:
    """Let the worker task run until it blocks."""
    for _ in range(5):
        await asyncio.sleep(0)


async def _drain_with_canary(queue: PrintQueue, store: MemoryJobStore) -> None:
    """Prove the worker has passed everything submitted so far.

    The queue is FIFO per printer, so once a canary submitted *after* the jobs
    under test has printed, any of them that was going to print already has.  A
    bare ``sleep(0)`` is not enough: the print path awaits a thread (image
    decode), so "nothing printed yet" would be true for a job still on its way.
    """
    canary = await _submit_persisted(queue, store)
    await queue.wait_for_job(str(canary), timeout_s=5)


@pytest.mark.asyncio
async def test_cancel_waiting_job_is_never_sent_and_persisted() -> None:
    printer = _RecordingPrinter()
    store = MemoryJobStore()
    queue = PrintQueue([printer], store=store)
    await queue.start()
    try:
        # Hold the worker (user pause) so the job waits in the in-memory queue.
        await queue.pause_printer(_PRINTER_ID, reason="user", source="user")
        job_id = await _submit_persisted(queue, store)
        await _settle()

        assert await queue.cancel(str(job_id)) is True

        await queue.resume_printer(_PRINTER_ID)
        await _drain_with_canary(queue, store)
        assert printer.prints == 1  # the canary only
        assert (await queue.get(job_id)).state == JobState.CANCELLED
        row = await store.get(job_id)
        assert row is not None
        assert row.state == DbJobState.CANCELLED.value
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_cancel_printing_job_is_refused_and_not_persisted() -> None:
    printer = _RecordingPrinter()
    printer.release.clear()
    store = MemoryJobStore()
    queue = PrintQueue([printer], store=store)
    await queue.start()
    try:
        job_id = await _submit_persisted(queue, store)
        await asyncio.wait_for(printer.entered.wait(), timeout=5)

        assert await queue.cancel(str(job_id)) is False

        printer.release.set()
        await queue.wait_for_job(str(job_id), timeout_s=5)
        assert (await queue.get(job_id)).state == JobState.COMPLETED
        row = await store.get(job_id)
        assert row is not None
        assert row.state == DbJobState.DONE.value
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_clear_queue_prevents_printing_and_persists_cancellation() -> None:
    printer = _RecordingPrinter()
    store = MemoryJobStore()
    queue = PrintQueue([printer], store=store)
    await queue.start()
    try:
        await queue.pause_printer(_PRINTER_ID, reason="user", source="user")
        ids = [await _submit_persisted(queue, store) for _ in range(3)]
        await _settle()

        assert await queue.clear_queue(_PRINTER_ID) == 3

        await queue.resume_printer(_PRINTER_ID)
        await _drain_with_canary(queue, store)
        assert printer.prints == 1  # the canary only
        for job_id in ids:
            assert (await queue.get(job_id)).state == JobState.CANCELLED
            row = await store.get(job_id)
            assert row is not None
            assert row.state == DbJobState.CANCELLED.value
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_clear_queue_leaves_printing_job_alone() -> None:
    printer = _RecordingPrinter()
    printer.release.clear()
    store = MemoryJobStore()
    queue = PrintQueue([printer], store=store)
    await queue.start()
    try:
        printing_id = await _submit_persisted(queue, store)
        await asyncio.wait_for(printer.entered.wait(), timeout=5)
        waiting_id = await _submit_persisted(queue, store)

        assert await queue.clear_queue(_PRINTER_ID) == 1

        printer.release.set()
        await queue.wait_for_job(str(printing_id), timeout_s=5)
        assert (await queue.get(printing_id)).state == JobState.COMPLETED
        assert (await queue.get(waiting_id)).state == JobState.CANCELLED
        assert printer.prints == 1
    finally:
        await queue.stop()


class _GatedStore(MemoryJobStore):
    """MemoryJobStore whose mark_printing / mark_cancelled can be held open."""

    def __init__(self) -> None:
        super().__init__()
        self.printing_entered = asyncio.Event()
        self.printing_gate = asyncio.Event()
        self.printing_gate.set()
        self.cancelled_entered = asyncio.Event()
        self.cancelled_gate = asyncio.Event()
        self.cancelled_gate.set()

    async def mark_printing(self, job_id: UUID) -> bool:
        self.printing_entered.set()
        await self.printing_gate.wait()
        return await super().mark_printing(job_id)

    async def mark_cancelled(self, job_id: UUID) -> None:
        self.cancelled_entered.set()
        await self.cancelled_gate.wait()
        await super().mark_cancelled(job_id)


@pytest.mark.asyncio
async def test_race_cancel_while_worker_persists_pickup_resolves_to_printing() -> None:
    """Worker took the job first (DB write in flight): cancel loses, job prints."""
    printer = _RecordingPrinter()
    store = _GatedStore()
    store.printing_gate.clear()
    queue = PrintQueue([printer], store=store)
    await queue.start()
    try:
        job_id = await _submit_persisted(queue, store)
        await asyncio.wait_for(store.printing_entered.wait(), timeout=5)

        # Worker is inside mark_printing: the job is already PRINTING in memory.
        assert await queue.cancel(str(job_id)) is False

        store.printing_gate.set()
        await queue.wait_for_job(str(job_id), timeout_s=5)
        assert printer.prints == 1
        assert (await queue.get(job_id)).state == JobState.COMPLETED
        row = await store.get(job_id)
        assert row is not None
        assert row.state == DbJobState.DONE.value
    finally:
        store.printing_gate.set()
        await queue.stop()


@pytest.mark.asyncio
async def test_race_worker_pops_while_cancel_persists_resolves_to_cancelled() -> None:
    """Cancel won (DB write still in flight) when the worker pops: nothing printed."""
    printer = _RecordingPrinter()
    store = _GatedStore()
    store.cancelled_gate.clear()
    queue = PrintQueue([printer], store=store)
    await queue.start()
    try:
        await queue.pause_printer(_PRINTER_ID, reason="user", source="user")
        job_id = await _submit_persisted(queue, store)
        await _settle()

        cancel_task = asyncio.create_task(queue.cancel(str(job_id)))
        await asyncio.wait_for(store.cancelled_entered.wait(), timeout=5)

        # Release the worker while the cancel's DB write is still pending.
        await queue.resume_printer(_PRINTER_ID)
        await _drain_with_canary(queue, store)
        assert printer.prints == 1  # the canary only

        store.cancelled_gate.set()
        assert await cancel_task is True
        assert printer.prints == 1
        assert (await queue.get(job_id)).state == JobState.CANCELLED
        row = await store.get(job_id)
        assert row is not None
        assert row.state == DbJobState.CANCELLED.value
    finally:
        store.cancelled_gate.set()
        await queue.stop()


def _engine() -> LayoutEngine:
    return LayoutEngine()


@pytest.mark.asyncio
async def test_enqueue_persisted_prints_without_restart() -> None:
    printer = _RecordingPrinter()
    store = MemoryJobStore()
    queue = PrintQueue([printer], store=store, engine=_engine())
    await queue.start()
    try:
        row = Job(printer_id=_PRINTER_ID, payload=dict(_RENDERABLE_PAYLOAD))
        await store.save_queued(row)

        await queue.enqueue_persisted(row)

        await queue.wait_for_job(str(row.id), timeout_s=5)
        assert printer.prints == 1
        stored = await store.get(row.id)
        assert stored is not None
        assert stored.state == DbJobState.DONE.value
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_enqueue_persisted_is_idempotent() -> None:
    printer = _RecordingPrinter()
    store = MemoryJobStore()
    queue = PrintQueue([printer], store=store, engine=_engine())
    await queue.start()
    try:
        await queue.pause_printer(_PRINTER_ID, reason="user", source="user")
        row = Job(printer_id=_PRINTER_ID, payload=dict(_RENDERABLE_PAYLOAD))
        await store.save_queued(row)

        await queue.enqueue_persisted(row)
        await queue.enqueue_persisted(row)

        await queue.resume_printer(_PRINTER_ID)
        await queue.wait_for_job(str(row.id), timeout_s=5)
        await _drain_with_canary(queue, store)
        assert printer.prints == 2  # the row once + the canary
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_enqueue_persisted_rejects_unrenderable_payload() -> None:
    from app.services.print_queue import UnrenderableJobError

    printer = _RecordingPrinter()
    store = MemoryJobStore()
    queue = PrintQueue([printer], store=store, engine=_engine())
    await queue.start()
    try:
        row = Job(printer_id=_PRINTER_ID, template_key="spoolman/1", payload={"label_title": "x"})
        await store.save_queued(row)

        with pytest.raises(UnrenderableJobError):
            await queue.enqueue_persisted(row)

        await _drain_with_canary(queue, store)
        assert printer.prints == 1  # the canary only
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_enqueue_persisted_unknown_printer_raises_key_error() -> None:
    queue = PrintQueue([_RecordingPrinter()], store=MemoryJobStore(), engine=_engine())
    row = Job(printer_id=uuid4(), payload=dict(_RENDERABLE_PAYLOAD))
    with pytest.raises(KeyError):
        await queue.enqueue_persisted(row)


@pytest.mark.asyncio
async def test_restart_after_retry_enqueues_the_row_exactly_once() -> None:
    """A retried row that never printed is picked up once by recovery, not twice."""
    store = MemoryJobStore()
    first_printer = _RecordingPrinter()
    first = PrintQueue([first_printer], store=store, engine=_engine())
    await first.start()
    await first.pause_printer(_PRINTER_ID, reason="user", source="user")
    row = Job(printer_id=_PRINTER_ID, payload=dict(_RENDERABLE_PAYLOAD))
    await store.save_queued(row)
    await first.enqueue_persisted(row)
    await _settle()
    assert first_printer.prints == 0
    await first.stop(timeout_s=1)

    second_printer = _RecordingPrinter()
    second = PrintQueue([second_printer], store=store, engine=_engine())
    await second.start()
    try:
        await second.wait_for_job(str(row.id), timeout_s=5)
        await _drain_with_canary(second, store)
        assert second_printer.prints == 2  # the row once + the canary
        # Recovery must not enqueue a row a second time (no duplicate print).
        assert second._queues[_PRINTER_ID].qsize() == 0
    finally:
        await second.stop()


@pytest.mark.asyncio
async def test_enqueue_persisted_before_start_is_not_duplicated_by_recovery() -> None:
    """Handing a row over before start() must not let recovery enqueue it again."""
    printer = _RecordingPrinter()
    store = MemoryJobStore()
    queue = PrintQueue([printer], store=store, engine=_engine())
    row = Job(printer_id=_PRINTER_ID, payload=dict(_RENDERABLE_PAYLOAD))
    await store.save_queued(row)

    await queue.enqueue_persisted(row)
    await queue.start()
    try:
        await queue.wait_for_job(str(row.id), timeout_s=5)
        await _drain_with_canary(queue, store)
        assert printer.prints == 2  # the row once + the canary
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_cancel_unknown_job_raises_key_error() -> None:
    queue = PrintQueue([_RecordingPrinter()], store=MemoryJobStore())
    with pytest.raises(KeyError):
        await queue.cancel(str(uuid4()))
    assert queue.has_job(uuid4()) is False


@pytest.mark.asyncio
async def test_cancel_while_persisted_row_is_rendering_wins() -> None:
    """Codex P1 on #187: a cancel during the re-render must not lose to the enqueue.

    The row is committed before ``enqueue_persisted`` renders it.  If the queue did
    not track it yet, a concurrent cancel would only touch the DB row and the
    enqueue would then print it anyway.
    """
    import threading

    printer = _RecordingPrinter()
    store = MemoryJobStore()
    queue = PrintQueue([printer], store=store, engine=_engine())
    await queue.start()
    release = threading.Event()
    entered = threading.Event()
    real_render = queue._rerender_from_db_payload

    def _slow_render(payload: dict[str, Any]) -> Image.Image:
        entered.set()
        release.wait(timeout=10)
        return real_render(payload)

    queue._rerender_from_db_payload = _slow_render  # type: ignore[method-assign]
    try:
        row = Job(printer_id=_PRINTER_ID, payload=dict(_RENDERABLE_PAYLOAD))
        await store.save_queued(row)
        enqueue = asyncio.create_task(queue.enqueue_persisted(row))
        while not entered.is_set():
            await asyncio.sleep(0.01)

        # Mid-render the queue already tracks the row, so cancel reaches it.
        assert queue.has_job(row.id) is True
        assert await queue.cancel(str(row.id)) is True

        release.set()
        await enqueue
        await _drain_with_canary(queue, store)
        assert printer.prints == 1  # the canary only
        assert (await queue.get(row.id)).state == JobState.CANCELLED
        stored = await store.get(row.id)
        assert stored is not None
        assert stored.state == DbJobState.CANCELLED.value
    finally:
        release.set()
        await queue.stop()


@pytest.mark.asyncio
async def test_enqueue_persisted_skips_row_cancelled_in_db_before_the_claim() -> None:
    printer = _RecordingPrinter()
    store = MemoryJobStore()
    queue = PrintQueue([printer], store=store, engine=_engine())
    await queue.start()
    try:
        row = Job(printer_id=_PRINTER_ID, payload=dict(_RENDERABLE_PAYLOAD))
        await store.save_queued(row)
        await store.mark_cancelled(row.id)  # a DB-only cancel got there first

        await queue.enqueue_persisted(row)

        await _drain_with_canary(queue, store)
        assert printer.prints == 1  # the canary only
        assert (await queue.get(row.id)).state == JobState.CANCELLED
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_failed_render_releases_the_claim() -> None:
    from app.services.print_queue import UnrenderableJobError

    queue = PrintQueue([_RecordingPrinter()], store=MemoryJobStore(), engine=_engine())

    def _boom(payload: dict[str, Any]) -> Image.Image:
        raise ValueError("bad")

    queue._rerender_from_db_payload = _boom  # type: ignore[method-assign]
    row = Job(printer_id=_PRINTER_ID, payload=dict(_RENDERABLE_PAYLOAD))
    with pytest.raises(UnrenderableJobError):
        await queue.enqueue_persisted(row)
    assert queue.has_job(row.id) is False
