import asyncio
import uuid
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
    uuid.UUID(job_id)  # raises ValueError if not a valid UUID


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

        # Deterministic check: worker is paused and must not start printing.
        # With the post-get pause loop, the worker pops the job and then blocks —
        # qsize() drops to 0 but the job state remains QUEUED (not PRINTING).
        await asyncio.sleep(0)  # yield to event loop; worker should not proceed
        assert queue._worker_states["pt750w"].value == "paused"
        assert (await queue.get(job_id)).state == JobState.QUEUED
        assert fake_printer.print_image.await_count == 0

        await queue.resume_printer("pt750w")
        await queue.wait_for_job(job_id, timeout_s=5)
        assert (await queue.get(job_id)).state == JobState.COMPLETED
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_queue_pause_after_idle_worker_is_respected() -> None:
    """Pausing while the worker is idle at queue.get() must still block the next pop."""
    fake_printer = MagicMock()
    fake_printer.id = "pt750w"
    fake_printer.print_image = AsyncMock()
    queue = PrintQueue([fake_printer])
    await queue.start()
    try:
        # Worker is now idle at queue.get() with an empty queue.
        # Give the loop a tick so the worker is actually blocked.
        await asyncio.sleep(0)

        # Pause AFTER the worker has entered queue.get().
        await queue.pause_printer("pt750w", reason="race test")

        # Submit a job. The pause must hold.
        img = Image.new("1", (300, 76))
        job_id = await queue.submit("pt750w", img, tape_mm=12)

        # Yield a few times — worker would print here if pause was ignored.
        for _ in range(5):
            await asyncio.sleep(0)
        assert (await queue.get(job_id)).state == JobState.QUEUED
        assert fake_printer.print_image.await_count == 0

        # Resume — job should complete now.
        await queue.resume_printer("pt750w")
        await queue.wait_for_job(job_id, timeout_s=5)
        assert (await queue.get(job_id)).state == JobState.COMPLETED
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_queue_stop_drains_in_flight_job() -> None:
    """stop() must wait for the currently-printing job to complete cleanly."""
    started = asyncio.Event()
    finished = asyncio.Event()

    async def slow_print(image, *, tape_mm, **kw):
        started.set()
        await asyncio.sleep(0.1)
        finished.set()

    fake_printer = MagicMock()
    fake_printer.id = "pt750w"
    fake_printer.print_image = AsyncMock(side_effect=slow_print)
    queue = PrintQueue([fake_printer])
    await queue.start()

    img = Image.new("1", (300, 76))
    job_id = await queue.submit("pt750w", img, tape_mm=12)
    await started.wait()  # printer is in the middle of printing

    await queue.stop(timeout_s=5.0)
    # The in-flight print finished cleanly (was not cancelled).
    assert finished.is_set()
    assert (await queue.get(job_id)).state == JobState.COMPLETED


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


# ---------------------------------------------------------------------------
# Recoverable errors → printer paused; fatal errors → printer stays active
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_pauses_printer_on_recoverable_error() -> None:
    """When a worker catches TapeEmptyError, the printer transitions to PAUSED
    so subsequent jobs in the queue are NOT processed until resume_printer."""
    from app.printer_backends.exceptions import TapeEmptyError
    from app.services.job_lifecycle import JobState
    from app.services.print_queue import PrinterWorkerState

    class _EmptyPrinter:
        id = "p1"

        async def print_image(self, image, *, tape_mm, **_options):
            raise TapeEmptyError()

    queue = PrintQueue(printers=[_EmptyPrinter()])
    await queue.start()
    try:
        image = Image.new("1", (200, 128))
        job_id = await queue.submit("p1", image, tape_mm=24)
        job = await queue.wait_for_job(job_id, timeout_s=2.0)
        assert job.state == JobState.FAILED
        assert job.error_code == "tape_empty"
        # The printer is now PAUSED
        assert queue._worker_states["p1"] == PrinterWorkerState.PAUSED
    finally:
        await queue.stop(timeout_s=2.0)


@pytest.mark.asyncio
async def test_worker_does_not_pause_on_fatal_error() -> None:
    """PrintFailedError is NOT recoverable; the worker stays active so
    subsequent jobs are still attempted."""
    from app.printer_backends.exceptions import PrintFailedError
    from app.services.job_lifecycle import JobState
    from app.services.print_queue import PrinterWorkerState

    class _FailPrinter:
        id = "p1"

        async def print_image(self, image, *, tape_mm, **_options):
            raise PrintFailedError("bad raster")

    queue = PrintQueue(printers=[_FailPrinter()])
    await queue.start()
    try:
        image = Image.new("1", (200, 128))
        job_id = await queue.submit("p1", image, tape_mm=24)
        job = await queue.wait_for_job(job_id, timeout_s=2.0)
        assert job.state == JobState.FAILED
        assert job.error_code == "print_failed"
        # Printer NOT paused — fatal error doesn't halt the queue
        assert queue._worker_states["p1"] == PrinterWorkerState.ACTIVE
    finally:
        await queue.stop(timeout_s=2.0)


# ---------------------------------------------------------------------------
# Task 1.5.5 — PrinterError → Job structured error fields
# ---------------------------------------------------------------------------


class _MismatchPrinter:
    id = "p1"

    async def print_image(self, image: Image.Image, *, tape_mm: int, **_options: object) -> None:
        from app.printer_backends.exceptions import TapeMismatchError

        raise TapeMismatchError(expected_mm=tape_mm, loaded_mm=12)


@pytest.mark.asyncio
async def test_worker_records_printer_error_fields() -> None:
    queue = PrintQueue(printers=[_MismatchPrinter()])
    await queue.start()
    try:
        image = Image.new("1", (200, 128))
        job_id = await queue.submit("p1", image, tape_mm=24)
        job = await queue.wait_for_job(job_id, timeout_s=2.0)
        assert job.state == JobState.FAILED
        assert job.error_code == "tape_mismatch"
        assert job.error_message
        assert job.error_detail == {"expected_mm": 24, "loaded_mm": 12}
    finally:
        await queue.stop(timeout_s=2.0)


# ---------------------------------------------------------------------------
# Finding #7 — on_state_change callback must fire for ALL transitions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_does_not_fire_on_state_change_callback() -> None:
    """submit() must NOT fire the on_state_change callback.

    Bug (Finding #1 / bot-review 2026-05-16): submit() called
    _notify_state_change with from_state==to_state==QUEUED, which is not a
    real transition (the job's initial state IS QUEUED). This polluted the
    EventBus with a fake job.state_changed event whose from_state and to_state
    were identical, causing HTMX sse-swap to render a spurious update.

    Real transitions (QUEUED→PRINTING, PRINTING→COMPLETED/FAILED,
    QUEUED→CANCELLED, etc.) still fire the callback from the worker loop and
    from cancel()/pause_job()/resume_job()/clear_queue().
    """
    transitions: list[tuple[str, str]] = []

    def _cb(job, from_state, to_state, queue_depth=0):
        transitions.append((from_state.value, to_state.value))

    fake_printer = MagicMock()
    fake_printer.id = "pt750w"
    queue = PrintQueue([fake_printer], on_state_change=_cb)

    img = Image.new("1", (300, 76))
    await queue.submit("pt750w", img, tape_mm=12)

    # submit() must NOT fire the callback — no real state transition happens
    assert not transitions, (
        f"submit() must not fire on_state_change (job starts as QUEUED, no transition), "
        f"got: {transitions}"
    )


@pytest.mark.asyncio
async def test_pause_job_fires_on_state_change_callback() -> None:
    """pause_job() must fire the on_state_change callback for PAUSED transition."""
    transitions: list[tuple[str, str]] = []

    def _cb(job, from_state, to_state, queue_depth=0):
        transitions.append((from_state.value, to_state.value))

    fake_printer = MagicMock()
    fake_printer.id = "pt750w"
    queue = PrintQueue([fake_printer], on_state_change=_cb)

    img = Image.new("1", (300, 76))
    job_id = await queue.submit("pt750w", img, tape_mm=12)
    transitions.clear()  # ignore submit() callback

    result = await queue.pause_job(job_id)
    assert result is True
    assert any(to == "paused" for _, to in transitions), (
        f"expected a PAUSED transition callback from pause_job(), got: {transitions}"
    )


@pytest.mark.asyncio
async def test_resume_job_fires_on_state_change_callback() -> None:
    """resume_job() must fire the on_state_change callback for QUEUED transition."""
    transitions: list[tuple[str, str]] = []

    def _cb(job, from_state, to_state, queue_depth=0):
        transitions.append((from_state.value, to_state.value))

    fake_printer = MagicMock()
    fake_printer.id = "pt750w"
    queue = PrintQueue([fake_printer], on_state_change=_cb)

    img = Image.new("1", (300, 76))
    job_id = await queue.submit("pt750w", img, tape_mm=12)
    await queue.pause_job(job_id)
    transitions.clear()  # ignore previous callbacks

    result = await queue.resume_job(job_id)
    assert result is True
    assert any(to == "queued" for _, to in transitions), (
        f"expected a QUEUED transition callback from resume_job(), got: {transitions}"
    )


@pytest.mark.asyncio
async def test_cancel_fires_on_state_change_callback() -> None:
    """cancel() must fire the on_state_change callback for CANCELLED transition."""
    transitions: list[tuple[str, str]] = []

    def _cb(job, from_state, to_state, queue_depth=0):
        transitions.append((from_state.value, to_state.value))

    fake_printer = MagicMock()
    fake_printer.id = "pt750w"
    queue = PrintQueue([fake_printer], on_state_change=_cb)

    img = Image.new("1", (300, 76))
    job_id = await queue.submit("pt750w", img, tape_mm=12)
    transitions.clear()

    result = await queue.cancel(job_id)
    assert result is True
    assert any(to == "cancelled" for _, to in transitions), (
        f"expected a CANCELLED transition callback from cancel(), got: {transitions}"
    )


@pytest.mark.asyncio
async def test_clear_queue_fires_on_state_change_callback() -> None:
    """clear_queue() must fire the on_state_change callback for each CANCELLED job."""
    transitions: list[tuple[str, str]] = []

    def _cb(job, from_state, to_state, queue_depth=0):
        transitions.append((from_state.value, to_state.value))

    fake_printer = MagicMock()
    fake_printer.id = "pt750w"
    queue = PrintQueue([fake_printer], on_state_change=_cb)

    img = Image.new("1", (300, 76))
    await queue.submit("pt750w", img, tape_mm=12)
    await queue.submit("pt750w", img, tape_mm=12)
    transitions.clear()

    count = await queue.clear_queue("pt750w")
    assert count == 2
    cancelled_transitions = [t for t in transitions if t[1] == "cancelled"]
    assert len(cancelled_transitions) == 2, (
        f"expected 2 CANCELLED callbacks from clear_queue(), got: {transitions}"
    )
