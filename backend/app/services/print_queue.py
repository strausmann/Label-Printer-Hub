"""Per-printer async work queue mit Persistierungs-Boundary.

Brother PT/QL printers expose TCP/9100 as a single-stream channel — there is
no on-device multi-job queue. The hub serialises jobs per printer by running
one asyncio worker task per printer and feeding it from an asyncio.Queue.

In-Memory dataclass `Job` Instanzen (mit image_payload bytes und
asyncio.Event) leben in `_jobs` während des Worker-Loops. Parallel
persistiert der `JobStore` die SQLModel-Job-Rows in SQLite — siehe
`app/services/job_store.py` (Phase 2).

Internal dependency note: the worker reads `job._done_event` (a private field
on `Job`) to signal completion to `wait_for_job`. `PrintQueue` and
`wait_for_job` are the intended and only legitimate consumers of that event;
the underscore signals "don't touch without thinking".
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from enum import StrEnum
from io import BytesIO
from typing import Any, Protocol, runtime_checkable
from uuid import UUID, uuid4

from PIL import Image

from app.models.job import JobState as DbJobState
from app.printer_backends.exceptions import (
    PrinterCoverOpenError,
    PrinterError,
    PrinterOfflineError,
    PrintFailedError,
    StatusQueryFailedError,
    TapeEmptyError,
    TapeMismatchError,
)
from app.services.job_lifecycle import (
    InvalidStateTransitionError,
    Job,
    JobState,
    JobStateMachine,
)
from app.services.job_store import JobStore, MemoryJobStore
from app.services.layout_engine import LayoutEngine


# Callback type: called after each state transition.  The optional queue_depth
# kwarg carries the number of non-terminal jobs still in the printer queue at
# the moment of the transition so the event payload reflects the real queue size.
class _StateChangeCallback(Protocol):
    def __call__(
        self,
        job: Job,
        from_state: JobState,
        to_state: JobState,
        queue_depth: int = ...,
    ) -> None: ...


logger = logging.getLogger(__name__)


class PrinterAlreadyActiveError(Exception):
    """Raised by resume_printer() when the printer worker is already ACTIVE.

    The route layer maps this to HTTP 409 with error_code='already_active' so
    clients can distinguish "was paused, now active" (200) from "already active"
    (409) without relying on response body inspection.
    """

    def __init__(self, printer_id: UUID) -> None:
        super().__init__(f"Printer {printer_id!r} is already active")
        self.printer_id = printer_id


_RECOVERABLE_PRINTER_ERRORS: tuple[type[PrinterError], ...] = (
    TapeMismatchError,
    TapeEmptyError,
    PrinterCoverOpenError,
    PrinterOfflineError,
)

_ERROR_CODE_MAP: dict[type[PrinterError], str] = {
    TapeMismatchError: "tape_mismatch",
    TapeEmptyError: "tape_empty",
    PrinterCoverOpenError: "printer_cover_open",
    PrinterOfflineError: "printer_offline",
    StatusQueryFailedError: "printer_status_unavailable",
    PrintFailedError: "print_failed",
}


def _printer_error_to_record(exc: PrinterError) -> tuple[str, str, dict[str, Any] | None]:
    """Map a PrinterError subclass to (error_code, error_message, error_detail)."""
    code = _ERROR_CODE_MAP.get(type(exc), "print_failed")
    detail: dict[str, Any] | None = None
    if isinstance(exc, TapeMismatchError):
        detail = {"expected_mm": exc.expected_mm, "loaded_mm": exc.loaded_mm}
    return code, str(exc) or code, detail


def _serialize_image_to_png(image: Image.Image) -> bytes:
    """Encode *image* as PNG bytes (CPU-bound; intended for asyncio.to_thread)."""
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


class PrinterWorkerState(StrEnum):
    """Per-printer worker state, orthogonal to per-job state."""

    ACTIVE = "active"
    PAUSED = "paused"


@runtime_checkable
class _PrinterLike(Protocol):
    """Minimal printer contract this queue depends on.

    Real printer plugins (PR for Tasks 2.1/2.2) implement the richer
    PrinterModel Protocol (PR #48). The queue depends only on `id`,
    `print_image`, and (Phase 1k.2) `print_images`.
    `tape_mm` is required as a keyword-only argument so mypy
    strict can verify that conforming printer plugins accept it explicitly;
    `**options` carries driver-specific extras that vary per plugin.
    """

    id: UUID

    async def print_image(self, image: Image.Image, *, tape_mm: int, **options: Any) -> None: ...

    async def print_images(
        self, images: list[Image.Image], *, tape_mm: int, **options: Any
    ) -> None: ...


@dataclass(frozen=False)
class BatchJob:
    """Queue-Item das mehrere Labels in einer Backend-Operation druckt.

    Phase 1k.2: BatchJob ist orthogonal zu Job — der Worker dispatched per
    isinstance. Auf success/failure werden alle job_ids gemeinsam markiert
    (atomic semantics, User-Entscheidung Option 1).
    """

    batch_id: UUID
    printer_id: UUID
    image_payloads: list[bytes]  # PNG-encoded für DB-Konsistenz mit Job.image_payload
    job_ids: list[UUID]
    tape_mm: int
    options: dict[str, Any]


class PrintQueue:
    """Per-printer async work queue with submit/pause/resume/cancel/retry."""

    def __init__(
        self,
        printers: list[_PrinterLike],
        on_state_change: _StateChangeCallback | None = None,
        store: JobStore | None = None,
        engine: LayoutEngine | None = None,
    ) -> None:
        """Konstruktor.

        Args:
            printers: Liste der Drucker-Objekte (jeder mit ``id`` UUID und
                ``print_image`` Coroutine-Methode).
            on_state_change: Optionaler Callback für SSE-Events. Wird nach
                jeder Job-State-Transition aufgerufen; None deaktiviert das
                Callback ohne sonstige Seiteneffekte.
            store: JobStore für DB-Persistierung der Job-Transitionen.
                Default ist ``MemoryJobStore()`` für Backward-Compat mit
                Pre-Phase-2-Tests — Production-Code wired in Lifespan
                explizit ``SQLiteJobStore`` ein (Task 9).
            engine: LayoutEngine-Instanz für Recovery in start().
                Default ist eine neue ``LayoutEngine()`` — stateless, sicher
                als Singleton.
        """
        self._on_state_change = on_state_change
        self._store: JobStore = store if store is not None else MemoryJobStore()
        self._engine: LayoutEngine = engine if engine is not None else LayoutEngine()
        self._printers: dict[UUID, _PrinterLike] = {p.id: p for p in printers}
        # Queue type is Job | BatchJob | None — None is the sentinel used by
        # stop() to wake workers that are blocked at queue.get().
        self._queues: dict[UUID, asyncio.Queue[Job | BatchJob | None]] = {
            p.id: asyncio.Queue() for p in printers
        }
        self._worker_states: dict[UUID, PrinterWorkerState] = {
            p.id: PrinterWorkerState.ACTIVE for p in printers
        }
        self._worker_resume_events: dict[UUID, asyncio.Event] = {
            p.id: asyncio.Event() for p in printers
        }
        # All resume events start "set" so a never-paused worker doesn't block.
        for ev in self._worker_resume_events.values():
            ev.set()
        # TODO(phase5): _jobs grows unbounded over the service lifetime; evict
        #               terminal jobs older than a configurable window once
        #               persistence lands.
        self._jobs: dict[str, Job] = {}
        self._workers: dict[UUID, asyncio.Task[None]] = {}
        self._running: bool = False
        self._stopping: bool = False

    # --- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return
        # I-1: Race-Guard — sofort setzen bevor erster await, damit ein zweiter
        # gleichzeitiger start()-Aufruf am Guard oben scheitert.
        self._running = True
        try:
            # Phase 2 Recovery: unterbrochene PRINTING-Jobs markieren + QUEUED re-enqueuen.
            # mark_interrupted MUSS vor list_pending aufgerufen werden, damit die alten
            # PRINTING-Jobs NICHT in list_pending zurückkommen.
            for printer_id in self._queues:
                interrupted = await self._store.mark_interrupted(printer_id)
                if interrupted > 0:
                    logger.warning(
                        "Recovery: %d PRINTING-Jobs auf Drucker %s als FAILED_RESTART markiert",
                        interrupted,
                        printer_id,
                    )
                pending_db_jobs = await self._store.list_pending(printer_id)
                for db_job in pending_db_jobs:
                    # S-1: StrEnum-Konsistenz — DbJobState.QUEUED.value statt String-Literal
                    if db_job.state != DbJobState.QUEUED.value:
                        continue
                    # C-1/I-2: fehlerhafte/veraltete Rows dürfen die Recovery nicht abbrechen.
                    # KeyError (fehlendes label_data/content_type), ValidationError
                    # (ungültige Struktur), ValueError (ungültiger ContentType-Wert) →
                    # Job FAILED markieren und mit dem nächsten Job weitermachen.
                    # MED-1/R2-1: Webhook-generated jobs (spoolman/<id>, grocy/<id>) have
                    # template_key but NO content_type/label_data/rendered_tape_mm in
                    # their payload. Skip gracefully before attempting rerender.
                    # R2-1: check all three required keys — a job with content_type +
                    # label_data but missing rendered_tape_mm would still fail in
                    # _rerender_from_db_payload; guard must cover the full set.
                    _required_rerender_keys = {"content_type", "label_data", "rendered_tape_mm"}
                    _missing_keys = _required_rerender_keys - db_job.payload.keys()
                    if _missing_keys:
                        skip_msg = (
                            f"Recovery: Skipping job {db_job.id} — payload lacks "
                            f"{sorted(_missing_keys)} "
                            f"(template_key={db_job.template_key!r}). "
                            f"Legacy/webhook-generated jobs cannot be re-rendered."
                        )
                        logger.info(skip_msg)
                        await self._store.mark_failed(
                            db_job.id,
                            f"recovery_skip_legacy_payload: {skip_msg}",
                        )
                        continue
                    try:
                        image = self._rerender_from_db_payload(db_job.payload)
                    except Exception as exc:  # defensive: per-job failure must not abort startup
                        logger.warning(
                            "Recovery: Job %s rerender fehlgeschlagen (%s),"
                            " wird als FAILED markiert und übersprungen",
                            db_job.id,
                            exc.__class__.__name__,
                            exc_info=True,
                        )
                        await self._store.mark_failed(
                            db_job.id,
                            f"recovery_rerender_failed: {exc.__class__.__name__}",
                        )
                        continue
                    payload_bytes = await asyncio.to_thread(_serialize_image_to_png, image)
                    wrapper = Job(
                        id=str(db_job.id),
                        printer_id=db_job.printer_id,
                        image_payload=payload_bytes,
                        tape_mm=db_job.payload.get("tape_mm"),
                        options=db_job.payload.get("options", {}),
                    )
                    self._jobs[str(db_job.id)] = wrapper
                    await self._queues[printer_id].put(wrapper)
                    logger.info(
                        "Recovery: QUEUED-Job %s auf Drucker %s re-enqueued",
                        db_job.id,
                        printer_id,
                    )

            for printer_id in self._queues:
                self._workers[printer_id] = asyncio.create_task(
                    self._worker(printer_id), name=f"printer-worker-{printer_id}"
                )
        except Exception:
            # I-1: Bei Recovery-Fehler _running zurücksetzen, damit ein erneuter
            # start()-Aufruf nicht am Guard scheitert.
            self._running = False
            raise

    def _rerender_from_db_payload(self, payload: dict[str, Any]) -> Image.Image:
        """Reconstruct a PIL Image from a stored job payload.

        Used during startup recovery for QUEUED jobs persisted before crash.
        The payload was produced by PrintService.submit_print_job (Task 15)
        and contains content_type, rendered_tape_mm, and label_data snapshot.

        Raises:
            KeyError: wenn ``label_data`` oder ``content_type`` fehlt.
            ValidationError: wenn ``label_data`` nicht in LabelData passt.
            ValueError: wenn ``content_type`` kein gültiger ContentType-Wert ist.
        """
        from app.schemas.content_type import ContentType
        from app.schemas.label_data import LabelData

        label_data = LabelData(**payload["label_data"])
        content_type = ContentType(payload["content_type"])
        tape_mm = int(payload["rendered_tape_mm"])
        return self._engine.render(
            tape_mm=tape_mm,
            content_type=content_type,
            data=label_data,
        )

    async def stop(self, timeout_s: float = 30.0) -> None:
        """Stop all workers.

        Workers are signalled to exit and given up to *timeout_s* seconds to
        finish the job they are currently printing. After the timeout, they are
        cancelled forcibly — that leaves the printer in an undefined state for
        that one job. Callers should pass enough timeout to cover a normal
        print.

        After all workers have stopped (gracefully or via cancellation), any
        job still in PRINTING state is transitioned to FAILED with
        error_code='shutdown' and its _done_event is set. This releases any
        caller blocked in wait_for_job() so they receive a FAILED result
        immediately instead of hanging until their own timeout fires.
        """
        self._stopping = True
        # Wake up any worker waiting on a paused resume event so it sees the
        # stop signal.
        for ev in self._worker_resume_events.values():
            ev.set()
        # Put a sentinel (None) onto each queue so workers blocked at queue.get()
        # wake up and see the stop flag.
        for q in self._queues.values():
            await q.put(None)
        if self._workers:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._workers.values(), return_exceptions=True),
                    timeout=timeout_s,
                )
            except TimeoutError:
                for task in self._workers.values():
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*self._workers.values(), return_exceptions=True)
        self._workers.clear()
        self._running = False
        self._stopping = False

        # Release any wait_for_job() callers that are still waiting on a
        # PRINTING job whose worker was cancelled before completion.
        # Transition those jobs to FAILED so their _done_event is set.
        for job in self._jobs.values():
            if job.state == JobState.PRINTING:
                job.error_code = "shutdown"
                job.error_message = "Print queue stopped during job execution"
                job.error_msg = job.error_message  # keep legacy field in sync (see line 466)
                try:
                    JobStateMachine.transition(job, JobState.FAILED)
                    await self._store.mark_failed(UUID(job.id), "shutdown")
                except InvalidStateTransitionError:
                    # Defensive: job already moved to a terminal state by the
                    # worker — just ensure _done_event is set.
                    job._done_event.set()
                logger.warning(
                    "Job %s left in PRINTING state after stop(); marked FAILED(shutdown)",
                    job.id,
                )

    # --- job CRUD -----------------------------------------------------------

    async def submit(
        self,
        printer_id: UUID,
        image: Image.Image,
        tape_mm: int,
        **options: Any,
    ) -> str:
        if printer_id not in self._queues:
            raise KeyError(f"Unknown printer: {printer_id}")
        payload = await asyncio.to_thread(_serialize_image_to_png, image)
        job = Job(
            id=str(uuid.uuid4()),
            printer_id=printer_id,
            image_payload=payload,
            tape_mm=tape_mm,
            options=dict(options),
        )
        self._jobs[job.id] = job
        await self._queues[printer_id].put(job)
        logger.info("Job %s queued on %s", job.id, printer_id)
        # No _notify_state_change here: submit() sets the initial state to QUEUED
        # (the default), so there is no real state *transition* to report.
        # Calling _notify_state_change with from_state==to_state==QUEUED would
        # emit a fake job.state_changed event on the EventBus and pollute the SSE
        # stream with spurious HTMX sse-swap updates (bot-review Finding F1).
        return job.id

    async def submit_with_id(
        self,
        job_id: UUID,
        printer_id: UUID,
        image: Image.Image,
        tape_mm: int,
        **options: Any,
    ) -> UUID:
        """Phase 2: Wie submit(), aber mit extern erzeugter job_id.

        Wird von PrintService genutzt, der die DB-Row zuerst anlegt (via
        store.save_queued) und die resultierende UUID hier weitergibt.
        Gibt die job_id unverändert zurück.
        """
        if printer_id not in self._queues:
            raise KeyError(f"Unknown printer: {printer_id}")
        payload = await asyncio.to_thread(_serialize_image_to_png, image)
        job = Job(
            id=str(job_id),
            printer_id=printer_id,
            image_payload=payload,
            tape_mm=tape_mm,
            options=dict(options),
        )
        self._jobs[str(job_id)] = job
        await self._queues[printer_id].put(job)
        logger.info("Job %s (extern-id) queued on %s", job_id, printer_id)
        return job_id

    async def enqueue_batch(
        self,
        *,
        printer_id: UUID,
        images: list[Image.Image],
        job_ids: list[UUID],
        tape_mm: int,
        options: dict[str, Any],
    ) -> UUID:
        """Phase 1k.2: Submit N images as ONE BatchJob (atomic print_multi call).

        Args:
            printer_id: Target printer (must be registered in self._queues).
            images: PIL Images in print order, len(images) >= 1.
            job_ids: Pre-allocated job UUIDs, one per image. Must be len(images) long.
            tape_mm: Shared tape width (12/18/24/62).
            options: Collective options (auto_cut, high_resolution, half_cut).

        Returns:
            batch_id: New UUID identifying this batch.

        Raises:
            KeyError: unknown printer_id.
            ValueError: len(images) != len(job_ids), or len(images) == 0.
        """
        if printer_id not in self._queues:
            raise KeyError(f"Unknown printer: {printer_id}")
        if not images:
            raise ValueError("enqueue_batch requires at least one image")
        if len(images) != len(job_ids):
            raise ValueError(f"images and job_ids length mismatch: {len(images)} vs {len(job_ids)}")

        # Gemini-Review G1 (PR #106): Parallel PNG-Serialisierung
        payloads = await asyncio.gather(
            *[asyncio.to_thread(_serialize_image_to_png, img) for img in images]
        )

        # Gemini-Review G1 (PR #106): In-Memory Job-Registrierung pro item.
        # OHNE diese Schleife wirft get(job_id)/wait_for_job KeyError, weil
        # die individuellen Jobs nie in self._jobs landen. SSE-Frontend und
        # Hangar-Polling brauchen pro-Item-Job-Records (alle teilen das BatchJob
        # als Owner, aber jeder Job hat eigene id/state/_done_event).
        for jid, payload in zip(job_ids, payloads, strict=True):
            job = Job(
                id=str(jid),
                printer_id=printer_id,
                image_payload=payload,
                tape_mm=tape_mm,
                options=dict(options),
            )
            self._jobs[str(jid)] = job

        batch_id = uuid4()
        batch = BatchJob(
            batch_id=batch_id,
            printer_id=printer_id,
            image_payloads=list(payloads),
            job_ids=list(job_ids),
            tape_mm=tape_mm,
            options=dict(options),
        )
        await self._queues[printer_id].put(batch)
        logger.info("Batch %s queued on %s with %d items", batch_id, printer_id, len(images))
        return batch_id

    async def get(self, job_id: str | UUID) -> Job:
        return self._jobs[str(job_id)]

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
        from_state = job.state
        try:
            JobStateMachine.transition(job, JobState.CANCELLED)
        except InvalidStateTransitionError:
            return False
        self._notify_state_change(
            job,
            from_state,
            JobState.CANCELLED,
            queue_depth=self._queue_depth(job.printer_id),
        )
        return True

    async def pause_job(self, job_id: str) -> bool:
        """Pause a queued job — worker skips it when it pops the queue."""
        job = self._jobs[job_id]
        if job.state != JobState.QUEUED:
            return False
        JobStateMachine.transition(job, JobState.PAUSED)
        self._notify_state_change(
            job,
            JobState.QUEUED,
            JobState.PAUSED,
            queue_depth=self._queue_depth(job.printer_id),
        )
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
        self._notify_state_change(
            job,
            JobState.PAUSED,
            JobState.QUEUED,
            queue_depth=self._queue_depth(job.printer_id),
        )
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

    async def pause_printer(self, printer_id: UUID, reason: str = "") -> None:
        """Pause the worker for a printer. Any in-flight job completes first."""
        if printer_id not in self._worker_states:
            raise KeyError(f"Unknown printer: {printer_id}")
        self._worker_states[printer_id] = PrinterWorkerState.PAUSED
        self._worker_resume_events[printer_id].clear()
        logger.info("Printer %s paused: %s", printer_id, reason)

    async def resume_printer(self, printer_id: UUID) -> None:
        """Resume a paused printer worker.

        Raises:
            KeyError: if *printer_id* is not known.
            PrinterAlreadyActiveError: if the printer is already ACTIVE.
                The route layer maps this to HTTP 409 with
                ``error_code='already_active'``.
        """
        if printer_id not in self._worker_states:
            raise KeyError(f"Unknown printer: {printer_id}")
        if self._worker_states[printer_id] == PrinterWorkerState.ACTIVE:
            raise PrinterAlreadyActiveError(printer_id)
        self._worker_states[printer_id] = PrinterWorkerState.ACTIVE
        self._worker_resume_events[printer_id].set()
        logger.info("Printer %s resumed", printer_id)

    def _queue_depth(self, printer_id: UUID) -> int:
        """Count non-terminal jobs for *printer_id* (QUEUED + PAUSED + PRINTING).

        O(N) over all-time jobs — acceptable at MVP scale. Used to populate
        the queue_depth field in job.state_changed SSE events (Finding #6).
        """
        non_terminal = (JobState.QUEUED, JobState.PAUSED, JobState.PRINTING)
        return sum(
            1 for j in self._jobs.values() if j.printer_id == printer_id and j.state in non_terminal
        )

    async def list_queue(self, printer_id: UUID) -> list[Job]:
        """All non-terminal jobs for a printer (queued + paused + printing).

        O(N) over all-time jobs — acceptable at MVP scale; see TODO(phase5)
        on the _jobs declaration in __init__.
        """
        if printer_id not in self._queues:
            raise KeyError(f"Unknown printer: {printer_id}")
        non_terminal = (JobState.QUEUED, JobState.PAUSED, JobState.PRINTING)
        return [
            j for j in self._jobs.values() if j.printer_id == printer_id and j.state in non_terminal
        ]

    async def clear_queue(self, printer_id: UUID) -> int:
        """Cancel all queued + paused jobs for a printer. Returns the count.

        O(N) over all-time jobs — acceptable at MVP scale; see TODO(phase5)
        on the _jobs declaration in __init__.
        """
        if printer_id not in self._queues:
            raise KeyError(f"Unknown printer: {printer_id}")
        cancelled = 0
        for job in self._jobs.values():
            if job.printer_id == printer_id and job.state in (
                JobState.QUEUED,
                JobState.PAUSED,
            ):
                from_state = job.state
                JobStateMachine.transition(job, JobState.CANCELLED)
                cancelled += 1
                self._notify_state_change(
                    job,
                    from_state,
                    JobState.CANCELLED,
                    queue_depth=self._queue_depth(printer_id),
                )
        return cancelled

    # --- worker loop -------------------------------------------------------

    def _notify_state_change(
        self,
        job: Job,
        from_state: JobState,
        to_state: JobState,
        queue_depth: int = 0,
    ) -> None:
        """Call the on_state_change callback if one is registered.

        ``queue_depth`` is the number of non-terminal jobs in the printer queue
        at the moment of the transition.  It is passed through to the callback
        (PrintQueueProducer.handle_transition) so the SSE event payload carries
        the real queue size rather than always 0 (Finding #6).

        Guarded with try/except so a bug in the callback never crashes the
        worker. The callback is expected to be PrintQueueProducer.handle_transition
        which already has its own internal guard, but defence in depth applies.
        """
        if self._on_state_change is not None:
            try:
                self._on_state_change(job, from_state, to_state, queue_depth=queue_depth)
            except Exception:
                logger.exception(
                    "on_state_change callback raised for job=%s %s->%s",
                    job.id,
                    from_state.value,
                    to_state.value,
                )

    async def _worker(self, printer_id: UUID) -> None:
        """Consume the queue for one printer, one job at a time.

        After popping a job the worker checks the pause state — this handles
        the race where pause_printer() is called while the worker is blocked at
        queue.get(). A sentinel value of None signals that stop() wants the
        worker to exit cleanly.
        """
        printer = self._printers[printer_id]
        queue = self._queues[printer_id]
        while True:
            item = await queue.get()

            if item is None:  # sentinel — stop() requested a clean exit
                return

            # Phase 1k.2: BatchJob vs Job — dispatch per isinstance
            if isinstance(item, BatchJob):
                await self._process_batch(printer, printer_id, item)
                continue

            job = item

            # Wait while paused — pause may have been set while we were idle at
            # queue.get(), so this check must come AFTER the pop.
            while self._worker_states[printer_id] == PrinterWorkerState.PAUSED:
                if self._stopping:
                    return
                await self._worker_resume_events[printer_id].wait()

            # Job may have been cancelled or paused between submit and pop.
            if job.state != JobState.QUEUED:
                continue

            # Phase 2: DB-State QUEUED->PRINTING persistieren (bridge: dataclass.id ist str)
            await self._store.mark_printing(UUID(job.id))

            try:
                _from = job.state
                JobStateMachine.transition(job, JobState.PRINTING)
                self._notify_state_change(
                    job,
                    _from,
                    JobState.PRINTING,
                    queue_depth=self._queue_depth(printer_id),
                )
                if job.tape_mm is None:
                    raise RuntimeError(
                        f"Job {job.id} has no tape_mm — submit() and retry_job() must populate it"
                    )
                if job.image_payload is None:
                    raise RuntimeError(f"Job {job.id} has no image payload")
                image = await asyncio.to_thread(Image.open, BytesIO(job.image_payload))
                await printer.print_image(image, tape_mm=job.tape_mm, **job.options)
                _from = job.state
                JobStateMachine.transition(job, JobState.COMPLETED)
                await self._store.mark_done(UUID(job.id))  # Phase 2: DB-State persistieren
                self._notify_state_change(
                    job,
                    _from,
                    JobState.COMPLETED,
                    queue_depth=self._queue_depth(printer_id),
                )
                logger.info("Job %s completed on %s", job.id, printer_id)
            except asyncio.CancelledError:
                # Forcible cancel after stop() timeout — re-raise so the task exits.
                raise
            except PrinterError as exc:
                code, msg, detail = _printer_error_to_record(exc)
                job.error_code = code
                job.error_message = msg
                job.error_detail = detail
                job.error_msg = msg  # legacy field kept in sync
                _from = job.state
                try:
                    JobStateMachine.transition(job, JobState.FAILED)
                    self._notify_state_change(
                        job,
                        _from,
                        JobState.FAILED,
                        queue_depth=self._queue_depth(printer_id),
                    )
                except InvalidStateTransitionError:
                    logger.warning(
                        "Job %s: unexpected state %s after PrinterError; error was: %s",
                        job.id,
                        job.state,
                        exc,
                    )
                # Phase 2: DB-State persistieren (auch wenn Transition fehlschlug)
                await self._store.mark_failed(UUID(job.id), f"{code}: {msg}")
                logger.exception("Job %s failed on %s (printer error)", job.id, printer_id)
                if isinstance(exc, _RECOVERABLE_PRINTER_ERRORS):
                    # Halt the whole printer queue — user must change tape /
                    # close cover / fix connectivity, then POST /printer/resume
                    # to release the queue.
                    await self.pause_printer(printer_id, reason=code)
            except Exception as exc:
                job.error_msg = str(exc)
                _from = job.state
                try:
                    JobStateMachine.transition(job, JobState.FAILED)
                    self._notify_state_change(
                        job,
                        _from,
                        JobState.FAILED,
                        queue_depth=self._queue_depth(printer_id),
                    )
                except InvalidStateTransitionError:
                    # Job was already moved to a terminal state externally.
                    logger.warning(
                        "Job %s: unexpected state %s after exception; error was: %s",
                        job.id,
                        job.state,
                        exc,
                    )
                # Phase 2: DB-State persistieren (auch wenn Transition fehlschlug)
                await self._store.mark_failed(UUID(job.id), str(exc))
                logger.exception("Job %s failed on %s", job.id, printer_id)

    async def _process_batch(
        self,
        printer: _PrinterLike,
        printer_id: UUID,
        batch: BatchJob,
    ) -> None:
        """Phase 1k.2: Handle BatchJob — atomic success/failure for all job_ids.

        Decodes payloads, calls printer.print_images() once. On exception,
        marks all job_ids as failed with a shared error_message.

        Gemini-Review G2 (PR #106): Pro item MUSS JobStateMachine.transition
        gerufen werden, sonst:
        - _done_event wird nie gesetzt → wait_for_job(job_id) hängt unendlich
        - _notify_state_change wird nie gerufen → SSE-Frontend (Hangar) bekommt
          keine Updates und zeigt Jobs als ewig 'queued' an
        - started_at/finished_at Timestamps bleiben None (UI-Probleme)
        """
        # Wait while paused (mirror _worker semantics)
        while self._worker_states[printer_id] == PrinterWorkerState.PAUSED:
            if self._stopping:
                return
            await self._worker_resume_events[printer_id].wait()

        # Gemini-Review G2: in-memory transitions + SSE-Events + DB persist.
        # QUEUED -> PRINTING für jeden Job.
        #
        # Gemini-Review G-R2-2 (PR #106): Wenn JobStateMachine.transition fails
        # (z.B. job already CANCELLED), darf NICHT noch _store.mark_printing
        # gerufen werden — sonst inkonsistent (in-memory CANCELLED vs DB PRINTING).
        # Wir sammeln nur successfully transitioned jobs in active_jobs[] und
        # nutzen die für alle folgenden DB-Calls + post-print transitions.
        #
        # Task 8 follow-up (G-R2-2): active_indices[] tracks the payload index of
        # each active_job so we can filter batch.image_payloads to match.
        # Without this, cancelled jobs would cause phantom prints (their payload
        # would still be sent to the printer even though the job was cancelled).
        active_jobs: list[Job] = []
        active_indices: list[int] = []
        for idx, jid in enumerate(batch.job_ids):
            job = self._jobs.get(str(jid))
            if job is None:
                logger.warning("Batch %s: job_id %s not in _jobs (cancelled?)", batch.batch_id, jid)
                continue
            try:
                JobStateMachine.transition(job, JobState.PRINTING)
                self._notify_state_change(
                    job,
                    JobState.QUEUED,
                    JobState.PRINTING,
                    queue_depth=self._queue_depth(printer_id),
                )
                await self._store.mark_printing(UUID(job.id))
                active_jobs.append(job)
                active_indices.append(idx)
            except InvalidStateTransitionError:
                logger.warning(
                    "Batch %s: job %s skipped — state already %s (cancelled?)",
                    batch.batch_id,
                    job.id,
                    job.state,
                )

        if not active_jobs:
            logger.warning(
                "Batch %s: 0 active jobs after transitions — skipping print", batch.batch_id
            )
            return

        # Gemini-Review G1 (PR #106): Parallel image decode
        # Task 8 follow-up: decode ONLY payloads of active_jobs to avoid phantom
        # prints for jobs that were cancelled between enqueue_batch and worker pickup.
        # cast to list[Image.Image]: Image.open returns ImageFile (subtype); list
        # is invariant so mypy needs an explicit cast here.
        active_payloads = [batch.image_payloads[i] for i in active_indices]
        raw_images = await asyncio.gather(
            *[asyncio.to_thread(Image.open, BytesIO(p)) for p in active_payloads]
        )
        images: list[Image.Image] = list(raw_images)

        try:
            await printer.print_images(
                images,
                tape_mm=batch.tape_mm,
                **batch.options,
            )
            # Success: alle active_jobs PRINTING -> COMPLETED.
            # Gemini-Review G-R2-2 (PR #106): nur active_jobs, NICHT alle jobs —
            # cancelled-mid-flight darf nicht überschrieben werden.
            for job in active_jobs:
                try:
                    JobStateMachine.transition(job, JobState.COMPLETED)
                    self._notify_state_change(
                        job,
                        JobState.PRINTING,
                        JobState.COMPLETED,
                        queue_depth=self._queue_depth(printer_id),
                    )
                    await self._store.mark_done(UUID(job.id))
                except InvalidStateTransitionError:
                    logger.warning(
                        "Batch %s: success-transition of %s failed (state=%s)",
                        batch.batch_id,
                        job.id,
                        job.state,
                    )
            logger.info("Batch %s completed on %s", batch.batch_id, printer_id)
        except asyncio.CancelledError:
            raise
        except PrinterError as exc:
            # Copilot-Review C6 (PR #106): Konsistenz mit existing _worker —
            # PrinterError-Subtypes müssen via _printer_error_to_record auf
            # strukturierte error_code/error_detail gemapped werden. Plus:
            # recoverable hardware errors (tape_mismatch, cover_open, offline)
            # MÜSSEN den Printer pausieren, sonst laufen Folge-Jobs ins gleiche
            # Problem.
            code, msg, detail = _printer_error_to_record(exc)
            # Gemini-Review G-R2-2 (PR #106): nur active_jobs, NICHT alle jobs.
            for job in active_jobs:
                job.error_code = code
                job.error_message = msg
                job.error_detail = detail
                job.error_msg = msg  # legacy field sync
                try:
                    JobStateMachine.transition(job, JobState.FAILED)
                    self._notify_state_change(
                        job,
                        JobState.PRINTING,
                        JobState.FAILED,
                        queue_depth=self._queue_depth(printer_id),
                    )
                    await self._store.mark_failed(UUID(job.id), f"{code}: {msg}")
                except InvalidStateTransitionError:
                    logger.warning(
                        "Batch %s: failure-transition of %s failed (state=%s)",
                        batch.batch_id,
                        job.id,
                        job.state,
                    )
            logger.exception(
                "Batch %s: PrinterError on %s — %d items marked failed (%s)",
                batch.batch_id,
                printer_id,
                len(active_jobs),
                code,
            )
            # Recoverable hardware error -> Printer pausieren (User-Interaktion nötig)
            if isinstance(exc, _RECOVERABLE_PRINTER_ERRORS):
                await self.pause_printer(printer_id, reason=code)
        except Exception as exc:
            # Fallback für non-PrinterError exceptions
            error_msg = f"batch print failed: {exc}"
            # Gemini-Review G-R2-2 (PR #106): nur active_jobs.
            for job in active_jobs:
                job.error_code = "batch_failed"
                job.error_message = error_msg
                job.error_msg = error_msg  # legacy field sync
                try:
                    JobStateMachine.transition(job, JobState.FAILED)
                    self._notify_state_change(
                        job,
                        JobState.PRINTING,
                        JobState.FAILED,
                        queue_depth=self._queue_depth(printer_id),
                    )
                    await self._store.mark_failed(UUID(job.id), error_msg)
                except InvalidStateTransitionError:
                    logger.warning(
                        "Batch %s: failure-transition of %s failed (state=%s)",
                        batch.batch_id,
                        job.id,
                        job.state,
                    )
            logger.exception(
                "Batch %s failed on %s — %d items marked failed",
                batch.batch_id,
                printer_id,
                len(active_jobs),
            )
