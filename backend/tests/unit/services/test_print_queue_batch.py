"""Tests fuer BatchJob path durch PrintQueue (Phase 1k.2 Task 8)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from app.printer_backends.exceptions import PrinterOfflineError
from app.services.job_lifecycle import JobState
from app.services.print_queue import PrinterWorkerState, PrintQueue
from PIL import Image


class _FakePrinter:
    """_PrinterLike test double with print_image + print_images."""

    def __init__(self, printer_id: UUID) -> None:
        self.id = printer_id
        self.print_image = AsyncMock()
        self.print_images = AsyncMock()


@pytest.fixture
def printer_id() -> UUID:
    return uuid4()


@pytest.fixture
def fake_printer(printer_id: UUID) -> _FakePrinter:
    return _FakePrinter(printer_id)


@pytest.fixture
def make_image() -> Callable[[], Image.Image]:
    return lambda: Image.new("1", (600, 70), color=1)


@pytest.mark.anyio
async def test_enqueue_batch_creates_batch_job(fake_printer, make_image):
    """enqueue_batch puts a BatchJob onto the queue, returns batch_id."""
    queue = PrintQueue([fake_printer])
    images = [make_image() for _ in range(3)]
    job_ids = [uuid4(), uuid4(), uuid4()]

    batch_id = await queue.enqueue_batch(
        printer_id=fake_printer.id,
        images=images,
        job_ids=job_ids,
        tape_mm=12,
        options={"auto_cut": True, "high_resolution": False},
    )

    assert isinstance(batch_id, UUID)


@pytest.mark.anyio
async def test_worker_dispatches_batchjob_to_print_images(fake_printer, make_image):
    """Worker recognises BatchJob and calls printer.print_images, not print_image."""
    queue = PrintQueue([fake_printer])
    images = [make_image() for _ in range(2)]
    job_ids = [uuid4(), uuid4()]

    await queue.start()
    try:
        await queue.enqueue_batch(
            printer_id=fake_printer.id,
            images=images,
            job_ids=job_ids,
            tape_mm=12,
            options={"auto_cut": True, "high_resolution": False, "half_cut": True},
        )
        # Wait for worker to consume the batch
        for _ in range(50):
            if fake_printer.print_images.await_count > 0:
                break
            await asyncio.sleep(0.05)
    finally:
        await queue.stop(timeout_s=2.0)

    assert fake_printer.print_images.await_count == 1
    assert fake_printer.print_image.await_count == 0  # NOT called

    call = fake_printer.print_images.call_args
    assert len(call.args[0]) == 2  # images list
    assert call.kwargs["tape_mm"] == 12
    assert call.kwargs["half_cut"] is True


@pytest.mark.anyio
async def test_batchjob_success_marks_all_job_ids_completed(fake_printer, make_image):
    """On print_images success, all job_ids of the batch are marked completed."""
    queue = PrintQueue([fake_printer])
    images = [make_image() for _ in range(3)]
    job_ids = [uuid4(), uuid4(), uuid4()]

    await queue.start()
    try:
        await queue.enqueue_batch(
            printer_id=fake_printer.id,
            images=images,
            job_ids=job_ids,
            tape_mm=12,
            options={"auto_cut": True, "half_cut": True},
        )
        for _ in range(50):
            if fake_printer.print_images.await_count > 0:
                break
            await asyncio.sleep(0.05)
    finally:
        await queue.stop(timeout_s=2.0)

    assert fake_printer.print_images.await_count == 1

    # Verify all jobs reached COMPLETED state (not just that print_images was called).
    for jid in job_ids:
        job = await queue.get(jid)
        assert job.state == JobState.COMPLETED, f"job {jid} expected COMPLETED, got {job.state}"


@pytest.mark.anyio
async def test_batchjob_failure_marks_all_job_ids_failed(fake_printer, make_image):
    """On print_images exception, all job_ids of the batch are marked failed."""
    fake_printer.print_images = AsyncMock(side_effect=RuntimeError("printer offline"))
    queue = PrintQueue([fake_printer])
    images = [make_image() for _ in range(2)]
    job_ids = [uuid4(), uuid4()]

    await queue.start()
    try:
        await queue.enqueue_batch(
            printer_id=fake_printer.id,
            images=images,
            job_ids=job_ids,
            tape_mm=12,
            options={"auto_cut": True, "half_cut": True},
        )
        for _ in range(50):
            if fake_printer.print_images.await_count > 0:
                break
            await asyncio.sleep(0.05)
    finally:
        await queue.stop(timeout_s=2.0)

    assert fake_printer.print_images.await_count == 1

    # Verify all jobs reached FAILED state with the expected error message.
    for jid in job_ids:
        job = await queue.get(jid)
        assert job.state == JobState.FAILED, f"job {jid} expected FAILED, got {job.state}"
        assert "printer offline" in (job.error_message or ""), (
            f"job {jid} error_message missing 'printer offline': {job.error_message!r}"
        )


@pytest.mark.anyio
async def test_enqueue_batch_rejects_unknown_printer(fake_printer, make_image):
    """enqueue_batch raises KeyError for unknown printer_id."""
    queue = PrintQueue([fake_printer])
    images = [make_image()]
    with pytest.raises(KeyError):
        await queue.enqueue_batch(
            printer_id=uuid4(),  # unknown
            images=images,
            job_ids=[uuid4()],
            tape_mm=12,
            options={},
        )


@pytest.mark.anyio
async def test_enqueue_batch_requires_matching_lengths(fake_printer, make_image):
    """images and job_ids must have same length."""
    queue = PrintQueue([fake_printer])
    images = [make_image() for _ in range(3)]
    with pytest.raises(ValueError, match="images and job_ids length mismatch"):
        await queue.enqueue_batch(
            printer_id=fake_printer.id,
            images=images,
            job_ids=[uuid4(), uuid4()],  # only 2
            tape_mm=12,
            options={},
        )


@pytest.mark.anyio
async def test_enqueue_batch_rejects_empty_images(fake_printer):
    """enqueue_batch raises ValueError for empty images list."""
    queue = PrintQueue([fake_printer])
    with pytest.raises(ValueError, match="at least one image"):
        await queue.enqueue_batch(
            printer_id=fake_printer.id,
            images=[],
            job_ids=[],
            tape_mm=12,
            options={},
        )


@pytest.mark.anyio
async def test_batchjob_cancelled_job_skipped_in_active(fake_printer, make_image):
    """If a job is cancelled before worker picks it up, only active items get printed."""
    queue = PrintQueue([fake_printer])
    images = [make_image() for _ in range(3)]
    job_ids = [uuid4(), uuid4(), uuid4()]

    await queue.start()
    try:
        await queue.enqueue_batch(
            printer_id=fake_printer.id,
            images=images,
            job_ids=job_ids,
            tape_mm=12,
            options={"auto_cut": True, "half_cut": True},
        )
        # Cancel the middle job BEFORE worker picks up
        await queue.cancel(str(job_ids[1]))
        # Wait for batch to process
        for _ in range(50):
            if fake_printer.print_images.await_count > 0:
                break
            await asyncio.sleep(0.05)
    finally:
        await queue.stop(timeout_s=2.0)

    # Worker called print_images once with only 2 images (middle was cancelled)
    assert fake_printer.print_images.await_count == 1
    call_args = fake_printer.print_images.call_args
    assert len(call_args.args[0]) == 2, (
        f"Expected 2 images (1 cancelled), got {len(call_args.args[0])}"
    )


@pytest.mark.anyio
async def test_batchjob_printer_offline_pauses_printer_and_marks_failed(
    fake_printer: _FakePrinter,
    make_image: Callable[[], Image.Image],
) -> None:
    """_process_batch C6 path: PrinterOfflineError pauses printer + all jobs failed."""
    fake_printer.print_images = AsyncMock(side_effect=PrinterOfflineError("offline"))
    queue = PrintQueue([fake_printer])
    images = [make_image() for _ in range(2)]
    job_ids = [uuid4(), uuid4()]

    await queue.start()
    try:
        await queue.enqueue_batch(
            printer_id=fake_printer.id,
            images=images,
            job_ids=job_ids,
            tape_mm=12,
            options={"auto_cut": True, "half_cut": True},
        )
        for _ in range(50):
            if fake_printer.print_images.await_count > 0:
                break
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.1)  # Allow state transitions to complete
    finally:
        await queue.stop(timeout_s=2.0)

    for jid in job_ids:
        job = await queue.get(jid)
        assert job.state == JobState.FAILED
        assert job.error_code == "printer_offline"

    # Recoverable PrinterError must pause the worker
    assert queue._worker_states[fake_printer.id] == PrinterWorkerState.PAUSED


@pytest.mark.anyio
async def test_batchjob_generic_exception_marks_jobs_failed(
    fake_printer: _FakePrinter,
    make_image: Callable[[], Image.Image],
) -> None:
    """_process_batch fallback path: generic Exception marks jobs failed, no pause."""
    fake_printer.print_images = AsyncMock(side_effect=RuntimeError("kapow"))
    queue = PrintQueue([fake_printer])
    images = [make_image() for _ in range(2)]
    job_ids = [uuid4(), uuid4()]

    await queue.start()
    try:
        await queue.enqueue_batch(
            printer_id=fake_printer.id,
            images=images,
            job_ids=job_ids,
            tape_mm=12,
            options={"auto_cut": True, "half_cut": True},
        )
        for _ in range(50):
            if fake_printer.print_images.await_count > 0:
                break
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.1)  # Allow state transitions to complete
    finally:
        await queue.stop(timeout_s=2.0)

    for jid in job_ids:
        job = await queue.get(jid)
        assert job.state == JobState.FAILED
        assert "kapow" in (job.error_message or "")

    # Generic Exception must NOT pause the printer
    assert queue._worker_states[fake_printer.id] == PrinterWorkerState.ACTIVE
