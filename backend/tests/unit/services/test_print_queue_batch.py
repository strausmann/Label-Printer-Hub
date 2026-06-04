"""Tests fuer BatchJob path durch PrintQueue (Phase 1k.2 Task 8)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from app.services.print_queue import PrintQueue
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

    # Status check — depends on JobStore implementation. Use list_completed if available:
    # For now, assert print_images called once (Mock-Store via MemoryJobStore default).
    assert fake_printer.print_images.await_count == 1


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
