"""A job the API reports as cancelled must never be printed (issue #184, audit R3-1).

Two gaps remained after the cancel/clear/retry routing:

1. Between ``save_queued`` (row visible as ``queued``) and the registration in the
   queue there was an ``await`` (PNG serialisation).  ``has_job()`` was False, so a
   cancel/clear took the DB-only path, answered success, and the job was then
   registered as QUEUED in memory and printed.  Single and batch path.
2. The worker ignored a refused ``store.mark_printing`` (row no longer ``queued``).

These tests hold the serialisation open (``threading.Event`` in a patched
``_serialize_image_to_png``) and cancel/clear inside that window, and test the
worker veto with a DB-only cancel.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.models.job import Job
from app.models.job import JobState as DbJobState
from app.services import print_queue as pq_module
from app.services.job_lifecycle import JobState
from app.services.job_store import MemoryJobStore
from app.services.print_queue import PrintQueue
from PIL import Image

_PRINTER_ID = UUID("eeeeeeee-0000-0000-0000-000000000001")


class _Printer:
    def __init__(self) -> None:
        self.id = _PRINTER_ID
        self.prints = 0
        self.batch_sizes: list[int] = []

    async def print_image(self, image: Image.Image, *, tape_mm: int, **options: Any) -> None:
        self.prints += 1

    async def print_images(
        self, images: list[Image.Image], *, tape_mm: int, **options: Any
    ) -> None:
        self.batch_sizes.append(len(images))
        self.prints += len(images)


class _SerialiseGate:
    """Patch ``_serialize_image_to_png`` so the first call(s) block until released."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
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


async def _canary(queue: PrintQueue, store: MemoryJobStore) -> None:
    job_id = uuid4()
    await store.save_queued(Job(id=job_id, printer_id=_PRINTER_ID, payload={}))
    await queue.submit_with_id(job_id, _PRINTER_ID, Image.new("1", (300, 76)), tape_mm=12)
    await queue.wait_for_job(str(job_id), timeout_s=5)


@pytest.mark.asyncio
async def test_cancel_during_submit_serialisation_is_never_printed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    printer = _Printer()
    store = MemoryJobStore()
    queue = PrintQueue([printer], store=store)
    await queue.start()
    gate = _SerialiseGate(monkeypatch)
    try:
        job_id = uuid4()
        await store.save_queued(Job(id=job_id, printer_id=_PRINTER_ID, payload={}))
        submit = asyncio.create_task(
            queue.submit_with_id(job_id, _PRINTER_ID, Image.new("1", (300, 76)), tape_mm=12)
        )
        await gate.wait_entered()

        # The row is `queued` in the store; the queue must already track the job.
        assert queue.has_job(job_id) is True
        assert await queue.cancel(str(job_id)) is True

        gate.release.set()
        await submit
        await _canary(queue, store)
        assert printer.prints == 1  # the canary only
        assert (await queue.get(job_id)).state == JobState.CANCELLED
        row = await store.get(job_id)
        assert row is not None
        assert row.state == DbJobState.CANCELLED.value
    finally:
        gate.release.set()
        await queue.stop()


@pytest.mark.asyncio
async def test_clear_during_submit_serialisation_is_never_printed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    printer = _Printer()
    store = MemoryJobStore()
    queue = PrintQueue([printer], store=store)
    await queue.start()
    gate = _SerialiseGate(monkeypatch)
    try:
        job_id = uuid4()
        await store.save_queued(Job(id=job_id, printer_id=_PRINTER_ID, payload={}))
        submit = asyncio.create_task(
            queue.submit_with_id(job_id, _PRINTER_ID, Image.new("1", (300, 76)), tape_mm=12)
        )
        await gate.wait_entered()

        assert await queue.clear_queue(_PRINTER_ID) == 1

        gate.release.set()
        await submit
        await _canary(queue, store)
        assert printer.prints == 1  # the canary only
        row = await store.get(job_id)
        assert row is not None
        assert row.state == DbJobState.CANCELLED.value
    finally:
        gate.release.set()
        await queue.stop()


@pytest.mark.asyncio
async def test_cancel_one_batch_item_during_serialisation_prints_the_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    printer = _Printer()
    store = MemoryJobStore()
    queue = PrintQueue([printer], store=store)
    await queue.start()
    gate = _SerialiseGate(monkeypatch)
    try:
        ids = [uuid4() for _ in range(3)]
        for jid in ids:
            await store.save_queued(Job(id=jid, printer_id=_PRINTER_ID, payload={}))
        batch_tasks = [
            asyncio.create_task(
                queue.enqueue_batch(
                    printer_id=_PRINTER_ID,
                    images=[Image.new("1", (300, 76)) for _ in ids],
                    job_ids=ids,
                    tape_mm=12,
                    options={},
                )
            )
        ]
        await gate.wait_entered()

        assert queue.has_job(ids[1]) is True
        assert await queue.cancel(str(ids[1])) is True

        gate.release.set()
        await batch_tasks[0]
        await queue.wait_for_job(str(ids[0]), timeout_s=5)
        await queue.wait_for_job(str(ids[2]), timeout_s=5)
        assert printer.batch_sizes == [2]
        assert (await queue.get(ids[1])).state == JobState.CANCELLED
        row = await store.get(ids[1])
        assert row is not None
        assert row.state == DbJobState.CANCELLED.value
    finally:
        gate.release.set()
        await queue.stop()


@pytest.mark.asyncio
async def test_clear_during_batch_serialisation_prints_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    printer = _Printer()
    store = MemoryJobStore()
    queue = PrintQueue([printer], store=store)
    await queue.start()
    gate = _SerialiseGate(monkeypatch)
    try:
        ids = [uuid4() for _ in range(2)]
        for jid in ids:
            await store.save_queued(Job(id=jid, printer_id=_PRINTER_ID, payload={}))
        batch_tasks = [
            asyncio.create_task(
                queue.enqueue_batch(
                    printer_id=_PRINTER_ID,
                    images=[Image.new("1", (300, 76)) for _ in ids],
                    job_ids=ids,
                    tape_mm=12,
                    options={},
                )
            )
        ]
        await gate.wait_entered()

        assert await queue.clear_queue(_PRINTER_ID) == 2

        gate.release.set()
        await batch_tasks[0]
        await _canary(queue, store)
        assert printer.batch_sizes == []
        assert printer.prints == 1  # the canary only
        for jid in ids:
            row = await store.get(jid)
            assert row is not None
            assert row.state == DbJobState.CANCELLED.value
    finally:
        gate.release.set()
        await queue.stop()


@pytest.mark.asyncio
async def test_failed_serialisation_releases_the_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = PrintQueue([_Printer()], store=MemoryJobStore())

    def _boom(image: Image.Image) -> bytes:
        raise ValueError("bad image")

    monkeypatch.setattr(pq_module, "_serialize_image_to_png", _boom)
    job_id = uuid4()
    with pytest.raises(ValueError, match="bad image"):
        await queue.submit_with_id(job_id, _PRINTER_ID, Image.new("1", (10, 10)), tape_mm=12)
    assert queue.has_job(job_id) is False

    batch_ids = [uuid4(), uuid4()]
    with pytest.raises(ValueError, match="bad image"):
        await queue.enqueue_batch(
            printer_id=_PRINTER_ID,
            images=[Image.new("1", (10, 10)), Image.new("1", (10, 10))],
            job_ids=batch_ids,
            tape_mm=12,
            options={},
        )
    assert not any(queue.has_job(j) for j in batch_ids)


@pytest.mark.asyncio
async def test_worker_skips_job_whose_row_is_no_longer_queued() -> None:
    """DB-only cancel of a tracked job (store refuses mark_printing): not printed."""
    printer = _Printer()
    store = MemoryJobStore()
    queue = PrintQueue([printer], store=store)
    await queue.start()
    try:
        await queue.pause_printer(_PRINTER_ID, reason="user", source="user")
        job_id = uuid4()
        await store.save_queued(Job(id=job_id, printer_id=_PRINTER_ID, payload={}))
        await queue.submit_with_id(job_id, _PRINTER_ID, Image.new("1", (300, 76)), tape_mm=12)
        await store.mark_cancelled(job_id)  # bypasses the queue, like the old DB-only route

        await queue.resume_printer(_PRINTER_ID)
        await queue.wait_for_job(str(job_id), timeout_s=5)

        assert printer.prints == 0
        job = await queue.get(job_id)
        assert job.state == JobState.FAILED
        assert job.error_msg == "cancelled_before_print"
        row = await store.get(job_id)
        assert row is not None
        assert row.state == DbJobState.CANCELLED.value
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_batch_skips_item_whose_row_is_no_longer_queued() -> None:
    printer = _Printer()
    store = MemoryJobStore()
    queue = PrintQueue([printer], store=store)
    await queue.start()
    try:
        await queue.pause_printer(_PRINTER_ID, reason="user", source="user")
        ids = [uuid4(), uuid4(), uuid4()]
        for jid in ids:
            await store.save_queued(Job(id=jid, printer_id=_PRINTER_ID, payload={}))
        await queue.enqueue_batch(
            printer_id=_PRINTER_ID,
            images=[Image.new("1", (300, 76)) for _ in ids],
            job_ids=ids,
            tape_mm=12,
            options={},
        )
        await store.mark_cancelled(ids[1])  # DB-only cancel

        await queue.resume_printer(_PRINTER_ID)
        for jid in (ids[0], ids[2]):
            await queue.wait_for_job(str(jid), timeout_s=5)
        await queue.wait_for_job(str(ids[1]), timeout_s=5)

        assert printer.batch_sizes == [2]
        skipped = await queue.get(ids[1])
        assert skipped.state == JobState.FAILED
        assert skipped.error_msg == "cancelled_before_print"
    finally:
        await queue.stop()


class _FailingCancelStore(MemoryJobStore):
    """Fails ``mark_cancelled`` for the first job it is asked about, then works."""

    def __init__(self) -> None:
        super().__init__()
        self.failed_for: UUID | None = None

    async def mark_cancelled(self, job_id: UUID) -> None:
        if self.failed_for is None:
            self.failed_for = job_id
            raise RuntimeError("database is locked")
        await super().mark_cancelled(job_id)


@pytest.mark.asyncio
async def test_cancel_surfaces_a_store_failure_after_the_in_memory_cancel() -> None:
    """Hardening: a DB fault must not be reported as a successful cancel."""
    printer = _Printer()
    store = _FailingCancelStore()
    queue = PrintQueue([printer], store=store)
    await queue.start()
    try:
        await queue.pause_printer(_PRINTER_ID, reason="user", source="user")
        job_id = uuid4()
        await store.save_queued(Job(id=job_id, printer_id=_PRINTER_ID, payload={}))
        await queue.submit_with_id(job_id, _PRINTER_ID, Image.new("1", (300, 76)), tape_mm=12)

        with pytest.raises(RuntimeError, match="database is locked"):
            await queue.cancel(str(job_id))

        # In memory it is cancelled, so this process still never prints it.
        await queue.resume_printer(_PRINTER_ID)
        await _canary_plain(queue, store)
        assert (await queue.get(job_id)).state == JobState.CANCELLED
    finally:
        await queue.stop()


async def _canary_plain(queue: PrintQueue, store: MemoryJobStore) -> None:
    jid = uuid4()
    await store.save_queued(Job(id=jid, printer_id=_PRINTER_ID, payload={}))
    await queue.submit_with_id(jid, _PRINTER_ID, Image.new("1", (300, 76)), tape_mm=12)
    await queue.wait_for_job(str(jid), timeout_s=5)


@pytest.mark.asyncio
async def test_clear_persists_every_job_before_surfacing_a_store_failure() -> None:
    printer = _Printer()
    store = _FailingCancelStore()
    queue = PrintQueue([printer], store=store)
    await queue.start()
    try:
        await queue.pause_printer(_PRINTER_ID, reason="user", source="user")
        ids = [uuid4(), uuid4()]
        for jid in ids:
            await store.save_queued(Job(id=jid, printer_id=_PRINTER_ID, payload={}))
            await queue.submit_with_id(jid, _PRINTER_ID, Image.new("1", (300, 76)), tape_mm=12)

        with pytest.raises(RuntimeError, match="database is locked"):
            await queue.clear_queue(_PRINTER_ID)

        for jid in ids:  # all cancelled in memory despite the DB fault
            assert (await queue.get(jid)).state == JobState.CANCELLED
        # The DB fault hit one row; the other one was still persisted.
        other = next(j for j in ids if j != store.failed_for)
        row = await store.get(other)
        assert row is not None
        assert row.state == DbJobState.CANCELLED.value
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_task_cancellation_during_rerender_releases_the_claim() -> None:
    """Hardening: a cancelled request must not leave a claimed, never-queued job."""
    store = MemoryJobStore()
    queue = PrintQueue([_Printer()], store=store)
    release = threading.Event()
    entered = threading.Event()
    real = queue._rerender_from_db_payload

    def _slow(payload: dict[str, Any]) -> Image.Image:
        entered.set()
        release.wait(timeout=10)
        return real(payload)

    queue._rerender_from_db_payload = _slow  # type: ignore[method-assign]
    row = Job(
        printer_id=_PRINTER_ID,
        payload={
            "label_data": {
                "title": "T",
                "primary_id": "T-1",
                "qr_payload": "https://example.com",
                "source_app": "manual",
                "secondary": [],
                "items": [],
            },
            "content_type": "qr_two_lines",
            "rendered_tape_mm": 24,
            "tape_mm": 24,
            "options": {},
        },
    )
    await store.save_queued(row)
    task = asyncio.create_task(queue.enqueue_persisted(row))
    for _ in range(500):
        if entered.is_set():
            break
        await asyncio.sleep(0.01)
    assert queue.has_job(row.id) is True

    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert queue.has_job(row.id) is False
