"""Per-printer async work queue.

Brother PT/QL printers expose TCP/9100 as a single-stream channel — there is
no on-device multi-job queue. The hub serialises jobs per printer by running
one asyncio worker task per printer and feeding it from an asyncio.Queue.

Jobs live in-memory (MVP). Phase 5 will add SQLite persistence behind a
JobStore protocol that this module will accept by dependency injection.

Internal dependency note: the worker reads `job._done_event` (a private field
on `Job`) to signal completion to `wait_for_job`. `PrintQueue` and
`wait_for_job` are the intended and only legitimate consumers of that event;
the underscore signals "don't touch without thinking".
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from enum import StrEnum
from io import BytesIO
from typing import Any, Protocol

from PIL import Image

from app.services.job_lifecycle import (
    InvalidStateTransitionError,
    Job,
    JobState,
    JobStateMachine,
)

logger = logging.getLogger(__name__)


class PrinterWorkerState(StrEnum):
    """Per-printer worker state, orthogonal to per-job state."""

    ACTIVE = "active"
    PAUSED = "paused"


class _PrinterLike(Protocol):
    """Minimal printer contract this queue depends on.

    Real printer plugins (PR for Tasks 2.1/2.2) implement the richer
    PrinterModel Protocol (PR #48). The queue depends only on `id` and
    `print_image`. `tape_mm` is required as a keyword-only argument so mypy
    strict can verify that conforming printer plugins accept it explicitly;
    `**options` carries driver-specific extras that vary per plugin.
    """

    id: str

    async def print_image(self, image: Image.Image, *, tape_mm: int, **options: Any) -> None: ...


class PrintQueue:
    """Per-printer async work queue with submit/pause/resume/cancel/retry."""

    def __init__(self, printers: list[_PrinterLike]) -> None:
        self._printers: dict[str, _PrinterLike] = {p.id: p for p in printers}
        self._queues: dict[str, asyncio.Queue[Job]] = {p.id: asyncio.Queue() for p in printers}
        self._worker_states: dict[str, PrinterWorkerState] = {
            p.id: PrinterWorkerState.ACTIVE for p in printers
        }
        self._worker_resume_events: dict[str, asyncio.Event] = {
            p.id: asyncio.Event() for p in printers
        }
        # All resume events start "set" so a never-paused worker doesn't block.
        for ev in self._worker_resume_events.values():
            ev.set()
        # TODO(phase5): _jobs grows unbounded over the service lifetime; evict
        #               terminal jobs older than a configurable window once
        #               persistence lands.
        self._jobs: dict[str, Job] = {}
        self._workers: dict[str, asyncio.Task[None]] = {}
        self._running: bool = False

    # --- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return
        for printer_id in self._queues:
            self._workers[printer_id] = asyncio.create_task(
                self._worker(printer_id), name=f"printer-worker-{printer_id}"
            )
        self._running = True

    async def stop(self) -> None:
        for task in self._workers.values():
            task.cancel()
        if self._workers:
            await asyncio.gather(*self._workers.values(), return_exceptions=True)
        self._workers.clear()
        self._running = False

    # --- job CRUD -----------------------------------------------------------

    async def submit(
        self,
        printer_id: str,
        image: Image.Image,
        tape_mm: int,
        **options: Any,
    ) -> str:
        if printer_id not in self._queues:
            raise KeyError(f"Unknown printer: {printer_id}")
        buf = BytesIO()
        image.save(buf, format="PNG")
        job = Job(
            id=str(uuid.uuid4()),
            printer_id=printer_id,
            image_payload=buf.getvalue(),
            tape_mm=tape_mm,
            options=dict(options),
        )
        self._jobs[job.id] = job
        await self._queues[printer_id].put(job)
        logger.info("Job %s queued on %s", job.id, printer_id)
        return job.id

    async def get(self, job_id: str) -> Job:
        return self._jobs[job_id]

    async def wait_for_job(self, job_id: str, timeout_s: float = 60.0) -> Job:
        job = self._jobs[job_id]
        # TODO(phase5): expose Job.wait_done() to remove this cross-module
        #               private access to _done_event.
        await asyncio.wait_for(job._done_event.wait(), timeout=timeout_s)
        return job

    # --- per-job control ---------------------------------------------------

    async def cancel(self, job_id: str) -> bool:
        """Cancel a queued or paused job. Returns False for non-cancellable states."""
        job = self._jobs[job_id]
        if job.state not in (JobState.QUEUED, JobState.PAUSED):
            return False
        try:
            JobStateMachine.transition(job, JobState.CANCELLED)
        except InvalidStateTransitionError:
            return False
        return True

    async def pause_job(self, job_id: str) -> bool:
        """Pause a queued job — worker skips it when it pops the queue."""
        job = self._jobs[job_id]
        if job.state != JobState.QUEUED:
            return False
        JobStateMachine.transition(job, JobState.PAUSED)
        return True

    async def resume_job(self, job_id: str) -> bool:
        """Re-enqueue a paused job at the tail of the queue (FIFO preserved).

        Note: the job's original reference remains in the asyncio.Queue from
        when it was first submitted. After resume, a new reference is appended
        at the tail. The worker filters by state on pop, so the stale reference
        drains cleanly (state != QUEUED on the second pop). asyncio.Queue.qsize()
        will be +1 high until that drain happens — use list_queue() for accurate
        active-job counts.
        """
        job = self._jobs[job_id]
        if job.state != JobState.PAUSED:
            return False
        JobStateMachine.transition(job, JobState.QUEUED)
        await self._queues[job.printer_id].put(job)
        return True

    async def retry_job(self, job_id: str) -> str | None:
        """Submit a fresh copy of a FAILED job. Returns new job id or None."""
        original = self._jobs[job_id]
        if original.state != JobState.FAILED:
            return None
        new_job = Job(
            id=str(uuid.uuid4()),
            printer_id=original.printer_id,
            image_payload=original.image_payload,
            tape_mm=original.tape_mm,
            options=dict(original.options),
            retry_count=original.retry_count + 1,
        )
        new_job.options["parent_job_id"] = original.id
        self._jobs[new_job.id] = new_job
        await self._queues[new_job.printer_id].put(new_job)
        return new_job.id

    # --- per-printer control -----------------------------------------------

    async def pause_printer(self, printer_id: str, reason: str = "") -> None:
        """Pause the worker for a printer. Any in-flight job completes first."""
        if printer_id not in self._worker_states:
            raise KeyError(f"Unknown printer: {printer_id}")
        self._worker_states[printer_id] = PrinterWorkerState.PAUSED
        self._worker_resume_events[printer_id].clear()
        logger.info("Printer %s paused: %s", printer_id, reason)

    async def resume_printer(self, printer_id: str) -> None:
        """Resume a paused printer worker."""
        if printer_id not in self._worker_states:
            raise KeyError(f"Unknown printer: {printer_id}")
        self._worker_states[printer_id] = PrinterWorkerState.ACTIVE
        self._worker_resume_events[printer_id].set()
        logger.info("Printer %s resumed", printer_id)

    async def list_queue(self, printer_id: str) -> list[Job]:
        """All non-terminal jobs for a printer (queued + paused + printing)."""
        if printer_id not in self._queues:
            raise KeyError(f"Unknown printer: {printer_id}")
        non_terminal = (JobState.QUEUED, JobState.PAUSED, JobState.PRINTING)
        return [
            j for j in self._jobs.values() if j.printer_id == printer_id and j.state in non_terminal
        ]

    async def clear_queue(self, printer_id: str) -> int:
        """Cancel all queued + paused jobs for a printer. Returns the count."""
        if printer_id not in self._queues:
            raise KeyError(f"Unknown printer: {printer_id}")
        cancelled = 0
        for job in self._jobs.values():
            if job.printer_id == printer_id and job.state in (
                JobState.QUEUED,
                JobState.PAUSED,
            ):
                JobStateMachine.transition(job, JobState.CANCELLED)
                cancelled += 1
        return cancelled

    # --- worker loop -------------------------------------------------------

    async def _worker(self, printer_id: str) -> None:
        """Consume the queue for one printer, one job at a time.

        The worker waits on `_worker_resume_events[printer_id]` when the
        printer is paused, so no jobs are dequeued until the printer is
        resumed. Each job is checked again after dequeue — it may have been
        cancelled or paused between submit and the worker picking it up.
        """
        printer = self._printers[printer_id]
        queue = self._queues[printer_id]
        while True:
            # Block here if the printer is paused; resume_printer() sets the event.
            if self._worker_states[printer_id] == PrinterWorkerState.PAUSED:
                await self._worker_resume_events[printer_id].wait()

            job = await queue.get()

            # Job may have been cancelled or paused between submit and pop.
            if job.state != JobState.QUEUED:
                continue

            try:
                JobStateMachine.transition(job, JobState.PRINTING)
                if job.tape_mm is None:
                    raise RuntimeError(
                        f"Job {job.id} has no tape_mm — submit() and retry_job() must populate it"
                    )
                if job.image_payload is None:
                    raise RuntimeError(f"Job {job.id} has no image payload")
                image = Image.open(BytesIO(job.image_payload))
                await printer.print_image(image, tape_mm=job.tape_mm, **job.options)
                JobStateMachine.transition(job, JobState.COMPLETED)
                logger.info("Job %s completed on %s", job.id, printer_id)
            except asyncio.CancelledError:
                # queue.stop() cancelled this task — re-raise so the task exits.
                raise
            except Exception as exc:
                job.error_msg = str(exc)
                try:
                    JobStateMachine.transition(job, JobState.FAILED)
                except InvalidStateTransitionError:
                    # Job was already moved to a terminal state externally.
                    logger.warning(
                        "Job %s: unexpected state %s after exception; error was: %s",
                        job.id,
                        job.state,
                        exc,
                    )
                logger.exception("Job %s failed on %s", job.id, printer_id)
