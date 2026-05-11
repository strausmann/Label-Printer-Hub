import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.services.job_lifecycle import (
    JobState,
    JobStateMachine,
)
from app.services.print_queue import PrintQueue
from PIL import Image


@pytest.mark.asyncio
async def test_queue_submit_returns_job_id() -> None:
    fake_printer = MagicMock()
    fake_printer.id = "pt750w"
    queue = PrintQueue([fake_printer])

    img = Image.new("1", (300, 76))
    job_id = await queue.submit("pt750w", img, tape_mm=12)
    assert isinstance(job_id, str)
    assert len(job_id) >= 8  # UUID-like


@pytest.mark.asyncio
async def test_queue_serial_per_printer() -> None:
    """Two jobs on the same printer execute serially, not in parallel."""
    fake_printer = MagicMock()
    fake_printer.id = "pt750w"
    fake_printer.print_image = AsyncMock(return_value=None)

    queue = PrintQueue([fake_printer])
    await queue.start()
    try:
        img = Image.new("1", (300, 76))
        job_id_1 = await queue.submit("pt750w", img, tape_mm=12)
        job_id_2 = await queue.submit("pt750w", img, tape_mm=12)

        await queue.wait_for_job(job_id_1, timeout_s=5)
        await queue.wait_for_job(job_id_2, timeout_s=5)

        assert fake_printer.print_image.await_count == 2
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_queue_pause_and_resume_job() -> None:
    fake_printer = MagicMock()
    fake_printer.id = "pt750w"
    fake_printer.print_image = AsyncMock()
    queue = PrintQueue([fake_printer])

    img = Image.new("1", (300, 76))
    job_id = await queue.submit("pt750w", img, tape_mm=12)
    assert (await queue.pause_job(job_id)) is True
    assert (await queue.get(job_id)).state == JobState.PAUSED
    assert (await queue.resume_job(job_id)) is True
    assert (await queue.get(job_id)).state == JobState.QUEUED


@pytest.mark.asyncio
async def test_queue_clear_cancels_all_pending() -> None:
    fake_printer = MagicMock()
    fake_printer.id = "pt750w"
    queue = PrintQueue([fake_printer])

    img = Image.new("1", (300, 76))
    j1 = await queue.submit("pt750w", img, tape_mm=12)
    j2 = await queue.submit("pt750w", img, tape_mm=12)
    cancelled = await queue.clear_queue("pt750w")
    assert cancelled == 2
    assert (await queue.get(j1)).state == JobState.CANCELLED
    assert (await queue.get(j2)).state == JobState.CANCELLED


@pytest.mark.asyncio
async def test_queue_pause_printer_blocks_worker() -> None:
    """When a printer is paused, the worker must not pick further jobs."""
    fake_printer = MagicMock()
    fake_printer.id = "pt750w"
    fake_printer.print_image = AsyncMock()
    queue = PrintQueue([fake_printer])
    await queue.start()
    try:
        await queue.pause_printer("pt750w", reason="manual pause")

        img = Image.new("1", (300, 76))
        job_id = await queue.submit("pt750w", img, tape_mm=12)

        # Deterministic check: worker is paused, job stays in asyncio.Queue.
        await asyncio.sleep(0)  # yield to event loop; worker should not proceed
        assert queue._worker_states["pt750w"].value == "paused"
        assert queue._queues["pt750w"].qsize() == 1
        assert (await queue.get(job_id)).state == JobState.QUEUED

        await queue.resume_printer("pt750w")
        await queue.wait_for_job(job_id, timeout_s=5)
        assert (await queue.get(job_id)).state == JobState.COMPLETED
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_queue_retry_failed_creates_new_job() -> None:
    fake_printer = MagicMock()
    fake_printer.id = "pt750w"
    queue = PrintQueue([fake_printer])

    img = Image.new("1", (300, 76))
    job_id = await queue.submit("pt750w", img, tape_mm=12)
    # Drive job to FAILED manually (no worker running)
    job = await queue.get(job_id)
    JobStateMachine.transition(job, JobState.PRINTING)
    JobStateMachine.transition(job, JobState.FAILED)

    new_id = await queue.retry_job(job_id)
    assert new_id is not None
    assert new_id != job_id
    new_job = await queue.get(new_id)
    assert new_job.state == JobState.QUEUED
    assert new_job.retry_count == 1
    assert new_job.options.get("parent_job_id") == job_id
