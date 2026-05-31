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
from enum import StrEnum
from io import BytesIO
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
from uuid import UUID

from PIL import Image
from pydantic import ValidationError

from app.models.job import Job as DbJob
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

# TYPE_CHECKING-Block verhindert zirkuläre Imports zur Laufzeit.
# LabelRenderer und TemplateLoader sind nur für die Recovery-Methode nötig.
if TYPE_CHECKING:
    from app.services.label_renderer import LabelRenderer
    from app.services.template_loader import TemplateLoader

# TemplateNotFoundError wird zur Laufzeit benötigt (Recovery-Loop catch), daher
# kein TYPE_CHECKING-Block — aber lazy import um Zirkel zu vermeiden.
from app.services.template_loader import TemplateNotFoundError


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
    PrinterModel Protocol (PR #48). The queue depends only on `id` and
    `print_image`. `tape_mm` is required as a keyword-only argument so mypy
    strict can verify that conforming printer plugins accept it explicitly;
    `**options` carries driver-specific extras that vary per plugin.
    """

    id: UUID

    async def print_image(self, image: Image.Image, *, tape_mm: int, **options: Any) -> None: ...


class PrintQueue:
    """Per-printer async work queue with submit/pause/resume/cancel/retry."""

    def __init__(
        self,
        printers: list[_PrinterLike],
        on_state_change: _StateChangeCallback | None = None,
        store: JobStore | None = None,
        renderer: LabelRenderer | None = None,
        loader: type[TemplateLoader] | None = None,
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
            renderer: LabelRenderer-Instanz für Recovery in start().
                Optional — wenn None, wirft _rerender_from_db_job() RuntimeError.
            loader: TemplateLoader-Klasse für Recovery in start().
                Optional — wenn None, wirft _rerender_from_db_job() RuntimeError.
        """
        self._on_state_change = on_state_change
        self._store: JobStore = store if store is not None else MemoryJobStore()
        self._renderer: LabelRenderer | None = renderer
        self._loader: type[TemplateLoader] | None = loader
        self._printers: dict[UUID, _PrinterLike] = {p.id: p for p in printers}
        # Queue type is Job | None — None is the sentinel used by stop() to wake
        # workers that are blocked at queue.get().
        self._queues: dict[UUID, asyncio.Queue[Job | None]] = {
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
                    # KeyError (fehlendes label_data), ValidationError (ungültige Struktur),
                    # TemplateNotFoundError (Template inzwischen gelöscht) → Job FAILED markieren
                    # und mit dem nächsten Job weitermachen.
                    try:
                        image = await self._rerender_from_db_job(db_job)
                    except (KeyError, ValidationError, TemplateNotFoundError) as exc:
                        logger.warning(
                            "Recovery: Job %s rerender fehlgeschlagen (%s), FAILED",
                            db_job.id,
                            exc.__class__.__name__,
                        )
                        await self._store.mark_failed(db_job.id, f"recovery_rerender_failed: {exc}")
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

    async def _rerender_from_db_job(self, db_job: DbJob) -> Image.Image:
        """Phase 2: Label-Bild aus persistiertem template_key + payload neu rendern.

        Wird während start() Recovery aufgerufen. Benötigt renderer + loader,
        die via PrintQueue-Konstruktor verdrahtet werden müssen (Production-Lifespan).

        Raises:
            RuntimeError: wenn renderer oder loader nicht gesetzt sind.
        """
        if self._renderer is None or self._loader is None:
            raise RuntimeError(
                "PrintQueue Recovery benötigt renderer + loader "
                "(via Konstruktor übergeben — siehe Lifespan-Konfiguration)"
            )
        template = self._loader.get(db_job.template_key)
        # R2-C4: payload["label_data"] ist ein rohes dict (model_dump()).
        # LabelRenderer.render() erwartet ein LabelData-Objekt — KEIN dict.
        from app.schemas.label_data import LabelData

        label_data = LabelData.model_validate(db_job.payload["label_data"])
        return self._renderer.render(template, label_data)

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

    async def submit_paused_with_id(
        self,
        job_id: UUID,
        printer_id: UUID,
        image: Image.Image,
        tape_mm: int,
        **options: Any,
    ) -> UUID:
        """Phase 2: Wie submit_paused(), aber mit extern erzeugter job_id.

        Wird von PrintService für den on_tape_mismatch='queue'-Pfad genutzt.
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
        JobStateMachine.transition(job, JobState.PAUSED)
        self._jobs[str(job_id)] = job
        logger.info("Job %s (extern-id) created paused on %s", job_id, printer_id)
        return job_id

    async def submit_paused(
        self,
        printer_id: UUID,
        image: Image.Image,
        tape_mm: int,
        **options: Any,
    ) -> str:
        """Create a job in PAUSED state without enqueuing it.

        Use this instead of ``submit()`` + ``JobStateMachine.transition(PAUSED)``
        whenever the caller wants the job to start life paused — typically the
        on_tape_mismatch='queue' path in PrintService.

        The job is registered in ``_jobs`` and immediately transitioned to PAUSED
        via JobStateMachine so all side-effects (timestamp, _done_event) are
        consistent. Crucially, it is **not** placed in the asyncio.Queue, so the
        worker can never dequeue it before the caller has a chance to attach
        error metadata.  Only ``resume_job()`` can promote the job to QUEUED and
        enqueue it later.
        """
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
        JobStateMachine.transition(job, JobState.PAUSED)
        self._jobs[job.id] = job
        logger.info("Job %s created paused on %s", job.id, printer_id)
        return job.id

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
