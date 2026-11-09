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
import contextlib
import logging
import uuid
from collections.abc import Callable, Coroutine, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from io import BytesIO
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID, uuid4

from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.job import Job as DbJob
from app.models.job import JobState as DbJobState
from app.models.printer_state import PrinterState
from app.printer_backends.exceptions import (
    PrinterCoverOpenError,
    PrinterError,
    PrinterOfflineError,
    PrintFailedError,
    StatusQueryFailedError,
    TapeEmptyError,
    TapeMismatchError,
)
from app.printer_backends.ipp.client import JobInfo
from app.printer_backends.ipp.errors import IppError, IppNotFoundError
from app.printer_backends.ipp.job_attrs import is_own_job, wire_job_name
from app.services.job_lifecycle import (
    InvalidStateTransitionError,
    Job,
    JobState,
    JobStateMachine,
)
from app.services.job_store import JobStore, MemoryJobStore
from app.services.layout_engine import LayoutEngine
from app.services.page_job_runner import Deferred, PageJobRunner
from app.services.page_jobs import (
    PageJob,
    PagePayload,
    PagePrinter,
    notify_ended,
    outcome_handler,
)
from app.sheets.errors import MediaKindMismatchError

_ON_UNKNOWN_TIMEOUT_S = 5.0
"""A handler's ``on_unknown`` runs inside ``start()``; a hanging one must not block startup."""


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


class UnrenderableJobError(Exception):
    """Raised by enqueue_persisted() when a stored job cannot be turned into an image.

    Webhook-created rows carry no ``content_type`` / ``label_data`` /
    ``rendered_tape_mm``, and a stored payload can be stale; neither can be
    printed.  The route layer maps this to HTTP 422.
    """


# Payload keys a stored job needs to be re-rendered (recovery and retry).
_REQUIRED_RERENDER_KEYS = frozenset({"content_type", "label_data", "rendered_tape_mm"})

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


PauseSource = Literal["user", "printer_error"]


@dataclass(frozen=True)
class PauseInfo:
    """Why a printer worker is paused (``user`` = manual, else hardware error)."""

    source: PauseSource
    reason_code: str
    since: datetime


# Called with (printer_id, info) after a pause and (printer_id, None) after a resume.
_PauseChangeCallback = Callable[[UUID, "PauseInfo | None"], None]


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
        on_pause_change: _PauseChangeCallback | None = None,
        page_printers: Sequence[PagePrinter] = (),
        page_runner: PageJobRunner | None = None,
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
        self._on_pause_change = on_pause_change
        self._pause_info: dict[UUID, PauseInfo] = {}
        self._store: JobStore = store if store is not None else MemoryJobStore()
        self._engine: LayoutEngine = engine if engine is not None else LayoutEngine()
        self._printers: dict[UUID, _PrinterLike] = {p.id: p for p in printers}
        # D18: page printers (IPP) get their own queues and worker; tape printers keep theirs.
        self._page_printers: dict[UUID, PagePrinter] = {p.id: p for p in page_printers}
        self._page_runner: PageJobRunner = page_runner or PageJobRunner(
            store=self._store, notify=self._notify_page_change
        )
        # Per page printer: the job a pre-flight deferred, drained before queue.get().
        self._held: dict[UUID, PageJob | None] = dict.fromkeys(self._page_printers)
        # Per page printer: jobs the printer already holds after a restart; the worker
        # resumes their tracking before it takes anything else.
        self._to_resume: dict[UUID, list[PageJob]] = {}
        # Job ids waiting in ``_to_resume`` -> a cancel arrived before the tracking resumed.
        self._resuming: dict[UUID, bool] = {}
        all_ids = [*self._printers, *self._page_printers]
        # Queue type is Job | BatchJob | PageJob | None — None is the sentinel used by
        # stop() to wake workers that are blocked at queue.get().
        self._queues: dict[UUID, asyncio.Queue[Job | BatchJob | PageJob | None]] = {
            pid: asyncio.Queue() for pid in all_ids
        }
        self._worker_states: dict[UUID, PrinterWorkerState] = dict.fromkeys(
            all_ids, PrinterWorkerState.ACTIVE
        )
        self._worker_resume_events: dict[UUID, asyncio.Event] = {
            pid: asyncio.Event() for pid in all_ids
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
        # #224: printers being removed at runtime. Their workers leave a taken job untouched
        # (it stays ``queued`` in the store) and exit; submits for them are refused.
        self._stopping_printers: set[UUID] = set()
        # A removal in progress, per printer: set when it is done (a second remove or an add
        # of the same id waits for it).
        self._removals: dict[UUID, asyncio.Event] = {}
        # An add (or start()'s recovery) in progress, per printer: a remove of the same id
        # waits for it, so it never purges a printer whose recovery or worker is still coming.
        self._adds: dict[UUID, asyncio.Event] = {}

    # --- lifecycle ----------------------------------------------------------

    async def start(self, initially_paused: Mapping[UUID, datetime] | None = None) -> None:
        """Start the workers, recover persisted jobs.

        *initially_paused* (printer id -> pause time) is applied BEFORE any worker
        task exists, so a printer the user stopped never prints a recovered job.
        """
        if self._running:
            return
        # I-1: Race-Guard — sofort setzen bevor erster await, damit ein zweiter
        # gleichzeitiger start()-Aufruf am Guard oben scheitert.
        self._running = True
        ids = list(self._queues)
        # Each printer of the snapshot counts as "being added" until its worker exists: a
        # remove that lands during the recovery below waits instead of purging under it.
        starting = {pid: asyncio.Event() for pid in ids if pid not in self._adds}
        self._adds.update(starting)
        try:
            for paused_id, since in (initially_paused or {}).items():
                if paused_id in self._worker_states:
                    # No real suspension here: state is set before any worker is created.
                    await self.pause_printer(paused_id, reason="user", source="user", since=since)
            # A PRINTING page job whose printer is not a page printer of this run (disabled,
            # deleted, or its backend changed) is not seen by the loop below: its outcome is
            # unknown, as it would be for a tape job (R1).
            for orphan in await self._store.list_page_jobs_in_flight():
                if orphan.printer_id not in self._page_printers:
                    await self._settle_unknown_page_job(orphan)
            # Phase 2 Recovery: unterbrochene PRINTING-Jobs markieren + QUEUED re-enqueuen,
            # one printer at a time (``_recover_printer``, shared with a runtime add). A
            # printer added while this runs is not in the snapshot: its add recovers it.
            for printer_id in ids:
                if printer_id in self._queues:  # not removed meanwhile
                    await self._recover_printer(printer_id)

            for printer_id in ids:
                if printer_id in self._workers or printer_id not in self._queues:
                    continue
                self._workers[printer_id] = asyncio.create_task(
                    self._worker_for(printer_id), name=f"printer-worker-{printer_id}"
                )
        except Exception:
            # I-1: Bei Recovery-Fehler _running zurücksetzen, damit ein erneuter
            # start()-Aufruf nicht am Guard scheitert.
            self._running = False
            raise
        finally:
            self._end_adds(starting)

    # --- membership (#224) --------------------------------------------------

    async def add_printer(
        self, printer: _PrinterLike, *, paused_since: datetime | None = None
    ) -> None:
        """Add a tape printer; on a running queue its jobs are recovered and it starts.

        *paused_since* is the persisted manual pause (``printer_state``); it is applied before
        anything of this printer can print. The same object again is a no-op; another object
        under a known id raises ``ValueError``.
        """
        await self._add(printer, page=False, paused_since=paused_since)

    async def add_page_printer(
        self, printer: PagePrinter, *, paused_since: datetime | None = None
    ) -> None:
        """Add a page (IPP) printer; see ``add_printer``."""
        await self._add(printer, page=True, paused_since=paused_since)

    async def _add(
        self, printer: _PrinterLike | PagePrinter, *, page: bool, paused_since: datetime | None
    ) -> None:
        printer_id = printer.id
        await self._await_membership(printer_id)
        # No await from here to the registration of ``_adds``: the checks below and the
        # claim are atomic against another add or a remove of the same id.
        known: _PrinterLike | PagePrinter | None = self._printers.get(
            printer_id
        ) or self._page_printers.get(printer_id)
        if known is not None:
            if known is printer and (printer_id in self._page_printers) == page:
                return
            raise ValueError(f"Another printer is registered under {printer_id}")
        adding = asyncio.Event()
        self._adds[printer_id] = adding
        try:
            await self._add_claimed(printer, printer_id, page=page, paused_since=paused_since)
        finally:
            self._end_adds({printer_id: adding})

    async def _add_claimed(
        self,
        printer: _PrinterLike | PagePrinter,
        printer_id: UUID,
        *,
        page: bool,
        paused_since: datetime | None,
    ) -> None:
        # Registered before the first await: a submit from here on is accepted; it waits in
        # the queue until the worker starts after the recovery.
        if page:
            self._page_printers[printer_id] = printer  # type: ignore[assignment]
            self._held[printer_id] = None
        else:
            self._printers[printer_id] = printer  # type: ignore[assignment]
        self._queues[printer_id] = asyncio.Queue()
        self._worker_states[printer_id] = PrinterWorkerState.ACTIVE
        resume = asyncio.Event()
        resume.set()
        self._worker_resume_events[printer_id] = resume
        try:
            # 1. the pause, so no recovered job can print
            if paused_since is not None:
                await self.pause_printer(
                    printer_id, reason="user", source="user", since=paused_since
                )
            if not self._running:
                return  # start() recovers and starts it
            # 2. recovery (fills ``_to_resume``), 3. the worker last: it takes ``_to_resume``
            # once, before its loop.
            await self._recover_printer(printer_id)
        except BaseException:
            self._purge(printer_id)
            raise
        self._workers[printer_id] = asyncio.create_task(
            self._worker_for(printer_id), name=f"printer-worker-{printer_id}"
        )
        logger.info("Printer %s added to the running queue", printer_id)

    async def remove_printer(self, printer_id: UUID, timeout_s: float) -> None:
        """Remove a printer from the queue without losing its jobs.

        A job printing now may finish within *timeout_s*; past it the worker is cancelled: a
        tape job still printing ends interrupted (as after a restart), a page job at the
        printer stays ``printing`` and the next add resumes its tracking. Jobs waiting behind
        it are not printed: their rows stay ``queued`` and a later add recovers them. Removing
        an unknown printer is a no-op.
        """
        while True:
            pending = self._removals.get(printer_id)
            if pending is not None:
                await pending.wait()  # a removal of this id is running: it does the work
                return
            adding = self._adds.get(printer_id)
            if adding is None:
                break
            await adding.wait()  # let the add finish (recovery, worker), then remove it
        if printer_id not in self._queues:
            return
        done = asyncio.Event()
        self._removals[printer_id] = done
        self._stopping_printers.add(printer_id)
        try:
            # Wake the worker: out of the pause loop, or out of queue.get() (the sentinel
            # lies behind any waiting job; the worker sees the flag on whatever it takes).
            self._worker_resume_events[printer_id].set()
            self._queues[printer_id].put_nowait(None)
            task = self._workers.pop(printer_id, None)
            if task is not None:
                try:
                    await asyncio.wait({task}, timeout=timeout_s)
                finally:
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
            await self._end_removed_in_flight(printer_id)
        finally:
            self._purge(printer_id)
            self._stopping_printers.discard(printer_id)
            del self._removals[printer_id]
            done.set()
        logger.info("Printer %s removed from the queue", printer_id)

    async def _end_removed_in_flight(self, printer_id: UUID) -> None:
        """End what the cancelled worker left PRINTING, as ``stop()`` and a restart do."""
        interrupted = False
        for job in list(self._jobs.values()):
            if job.printer_id != printer_id or job.state != JobState.PRINTING:
                continue
            if job.kind is not None:
                continue  # page job at the printer: the row stays ``printing``
            job.error_code = "interrupted"
            job.error_message = "Printer removed during job execution"
            job.error_msg = job.error_message
            with contextlib.suppress(InvalidStateTransitionError):
                JobStateMachine.transition(job, JobState.FAILED)
            interrupted = True
        if interrupted:
            await self._store.mark_interrupted(printer_id)

    def _purge(self, printer_id: UUID) -> None:
        """Forget every per-printer entry; waiting jobs stay persisted as ``queued``."""
        for job_id, job in list(self._jobs.items()):
            if job.printer_id == printer_id and job.state in (
                JobState.QUEUED,
                JobState.PAUSED,
                JobState.PRINTING,
            ):
                self._resuming.pop(UUID(job_id), None)
                job._done_event.set()  # release wait_for_job(), as stop() does
                del self._jobs[job_id]
        self._queues.pop(printer_id, None)
        self._worker_states.pop(printer_id, None)
        self._worker_resume_events.pop(printer_id, None)
        self._pause_info.pop(printer_id, None)
        self._held.pop(printer_id, None)
        self._to_resume.pop(printer_id, None)
        self._printers.pop(printer_id, None)
        self._page_printers.pop(printer_id, None)

    async def _await_membership(self, printer_id: UUID) -> None:
        """Wait until no add or remove of *printer_id* is in progress."""
        while True:
            busy = self._adds.get(printer_id) or self._removals.get(printer_id)
            if busy is None:
                return
            await busy.wait()

    def _end_adds(self, events: Mapping[UUID, asyncio.Event]) -> None:
        for printer_id, event in events.items():
            if self._adds.get(printer_id) is event:
                del self._adds[printer_id]
            event.set()

    def _removing(self, printer_id: UUID) -> bool:
        return printer_id in self._stopping_printers

    def _worker_for(self, printer_id: UUID) -> Coroutine[Any, Any, None]:
        """The worker coroutine of *printer_id* (D18: tape and page printers differ)."""
        if printer_id in self._page_printers:
            return self._page_worker(printer_id)
        return self._worker(printer_id)

    async def _recover_printer(self, printer_id: UUID) -> None:
        """Restart recovery of one printer, before its worker exists.

        Shared by ``start()`` and a runtime add (``_add``). It does not apply a pause: the
        caller does that first, so no recovered job can print on a printer the user stopped.
        The worker is created afterwards: ``_page_worker`` takes ``_to_resume`` once.
        """
        # mark_interrupted MUSS vor list_pending aufgerufen werden, damit die alten
        # PRINTING-*Tape*-Jobs NICHT in list_pending zurückkommen. PRINTING *page* jobs
        # bleiben (mark_interrupted lässt sie aus) und kommen zurück: _recover_page_jobs
        # nimmt sie auf und filtert den Rest nach QUEUED.
        interrupted = await self._store.mark_interrupted(printer_id)
        if interrupted > 0:
            logger.warning(
                "Recovery: %d PRINTING-Jobs auf Drucker %s als FAILED_RESTART markiert",
                interrupted,
                printer_id,
            )
        pending_db_jobs = await self._store.list_pending(printer_id)
        if printer_id in self._page_printers:  # D18: page jobs render at send time
            await self._recover_page_jobs(printer_id, pending_db_jobs)
            return
        for db_job in pending_db_jobs:
            # S-1: StrEnum-Konsistenz — DbJobState.QUEUED.value statt String-Literal
            if db_job.state != DbJobState.QUEUED.value:
                continue
            # A row handed over via enqueue_persisted() before start() is
            # already known; enqueueing it again would print it twice.
            if str(db_job.id) in self._jobs:
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
            _missing_keys = _REQUIRED_RERENDER_KEYS - db_job.payload.keys()
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

    async def _recover_page_jobs(self, printer_id: UUID, pending: list[DbJob]) -> None:
        """Restart recovery of one page printer's jobs.

        In-flight (PRINTING) jobs are untouched by ``mark_interrupted``: one with an IPP job
        id is handed to the worker for resumed tracking; one without may have been taken by
        the printer (the upload was under way), its outcome is unknown. QUEUED jobs are
        re-enqueued from their payload (rendered at send, not here).
        """
        await self._recover_in_flight_page_jobs(printer_id)
        for db_job in pending:
            if db_job.state != DbJobState.QUEUED.value or str(db_job.id) in self._jobs:
                continue
            try:
                payload = PagePayload.model_validate(db_job.payload)
            except ValueError:
                logger.warning("Recovery: page job %s has an invalid payload", db_job.id)
                await self._store.mark_failed(db_job.id, "recovery_invalid_page_payload")
                continue
            job = self._new_page_job(db_job.id, printer_id, payload)
            await self._queues[printer_id].put(PageJob(job=job, payload=payload))
            logger.info("Recovery: page job %s re-enqueued on %s", db_job.id, printer_id)

    async def _recover_in_flight_page_jobs(self, printer_id: UUID) -> None:
        resumable: list[PageJob] = []
        for row in await self._store.list_page_jobs_in_flight(printer_id):
            result = dict(row.result or {})
            ipp_job_id = result.get("ipp_job_id")
            try:
                payload = PagePayload.model_validate(row.payload)
            except ValueError:
                payload = None
            # "uploading" is an unknown outcome even if the hub never saw the printer accept
            # the document: it may have (R1). Same for a job without an IPP job id.
            if (
                payload is None
                or result.get("phase") == "uploading"
                or not isinstance(ipp_job_id, int)
                or isinstance(ipp_job_id, bool)
            ):
                await self._settle_unknown_page_job(row)
                continue
            job = self._new_page_job(row.id, printer_id, payload)
            JobStateMachine.transition(job, JobState.PRINTING)
            resumable.append(PageJob(job=job, payload=payload, resume_result=result))
            self._resuming[row.id] = False
            logger.info("Recovery: page job %s on %s resumes tracking", row.id, printer_id)
        self._to_resume[printer_id] = resumable

    async def settle_page_jobs_in_flight(self, printer_id: UUID) -> int:
        """End the PRINTING page jobs of *printer_id* as unknown when it is no page printer.

        A page printer re-wired as a tape printer at runtime (#224) never resumes the tracking
        of a page job the printer may still hold: ``start()`` settles such a job at the next
        restart (an orphan of a non-page printer); this does it at once. A no-op while
        *printer_id* is a page printer. Returns the number of jobs settled.
        """
        if printer_id in self._page_printers:
            return 0
        rows = await self._store.list_page_jobs_in_flight(printer_id)
        for row in rows:
            await self._settle_unknown_page_job(row)
        return len(rows)

    async def _settle_unknown_page_job(self, row: DbJob) -> None:
        """A page job that may or may not have printed: ``failed_restart`` and ``on_unknown``."""
        logger.warning("Recovery: page job %s has an unknown outcome", row.id)
        await self._store.mark_failed_restart(row.id, "page_outcome_unknown")
        kind = str((row.payload or {}).get("kind"))
        try:
            async with asyncio.timeout(_ON_UNKNOWN_TIMEOUT_S):
                await outcome_handler(kind).on_unknown(row.id)
        except Exception:
            logger.exception("Page outcome handler on_unknown failed for job %s", row.id)

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
        # D18: a page worker may be tracking a job at the printer, which can take minutes.
        # The printer keeps the job; it is cancelled here at once instead of being waited
        # for; the next start() resumes the tracking (``_resume_page_jobs``).
        for printer_id in self._page_printers:
            page_task = self._workers.get(printer_id)
            if page_task is not None and not page_task.done():
                page_task.cancel()
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
        for job in list(self._jobs.values()):
            if job.state == JobState.PRINTING and job.kind is not None:
                # Page job at the printer: the row stays ``printing`` (the printer may
                # still print it); only the in-memory waiters are released.
                job._done_event.set()
                continue
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
        self._require_tape(printer_id)
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
        self._require_tape(printer_id)
        if str(job_id) in self._jobs:
            # The caller saved the row before this call; an add's recovery (or start()) read
            # it in between and already queued it from its payload. Queuing it again would
            # replace the in-memory job: the label prints once, but the caller's job would
            # end ``cancelled_before_print`` (the row's pick-up refuses the second copy).
            return job_id
        # Register BEFORE the first await: the caller has already persisted the row as
        # QUEUED, so from now on a cancel/clear can arrive.  If the queue did not track
        # the job yet it would only touch the DB row, answer success, and the job would
        # then be registered and printed anyway (audit R3-1).  The image is attached
        # after the (threaded) serialisation.
        job = Job(
            id=str(job_id),
            printer_id=printer_id,
            tape_mm=tape_mm,
            options=dict(options),
        )
        self._jobs[str(job_id)] = job
        try:
            job.image_payload = await asyncio.to_thread(_serialize_image_to_png, image)
        except BaseException:
            self._drop_unqueued(job)
            raise
        if job.state != JobState.QUEUED:
            return job_id  # cancelled while serialising; cancel() already persisted that
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
        self._require_tape(printer_id)
        if not images:
            raise ValueError("enqueue_batch requires at least one image")
        if len(images) != len(job_ids):
            raise ValueError(f"images and job_ids length mismatch: {len(images)} vs {len(job_ids)}")

        # Gemini-Review G1 (PR #106): In-Memory Job-Registrierung pro item.
        # OHNE diese Schleife wirft get(job_id)/wait_for_job KeyError, weil
        # die individuellen Jobs nie in self._jobs landen. SSE-Frontend und
        # Hangar-Polling brauchen pro-Item-Job-Records (alle teilen das BatchJob
        # als Owner, aber jeder Job hat eigene id/state/_done_event).
        #
        # Registered BEFORE the first await (audit R3-1): the rows are already QUEUED
        # in the DB, so a cancel/clear during the serialisation below must reach the
        # in-memory jobs instead of only the DB.  The images are attached afterwards.
        registered: list[Job] = []  # jobs this call creates; claimed ones are not ours
        for jid in job_ids:
            if str(jid) in self._jobs:
                # Recovery already queued this row (see submit_with_id): the batch shares
                # the in-memory job, whichever entry reaches the worker first prints it.
                continue
            job = Job(
                id=str(jid),
                printer_id=printer_id,
                tape_mm=tape_mm,
                options=dict(options),
            )
            self._jobs[str(jid)] = job
            registered.append(job)

        # Gemini-Review G1 (PR #106): Parallel PNG-Serialisierung
        try:
            payloads = await asyncio.gather(
                *[asyncio.to_thread(_serialize_image_to_png, img) for img in images]
            )
        except BaseException:
            for job in registered:
                self._drop_unqueued(job)
            raise
        by_id = {own.id: own for own in registered}
        for jid, payload in zip(job_ids, payloads, strict=True):
            if (own := by_id.get(str(jid))) is not None:
                own.image_payload = payload

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

    def _require_tape(self, printer_id: UUID) -> None:
        """D18: tape submission paths refuse page printers; a printer being removed is unknown."""
        if self._removing(printer_id):
            raise KeyError(f"Unknown printer: {printer_id}")
        if printer_id in self._page_printers:
            raise MediaKindMismatchError()
        if printer_id not in self._queues:
            raise KeyError(f"Unknown printer: {printer_id}")

    def _new_page_job(self, job_id: UUID, printer_id: UUID, payload: PagePayload) -> Job:
        """Register the in-memory job of a page job (before any await, like the tape paths)."""
        job = Job(
            id=str(job_id),
            printer_id=printer_id,
            kind=payload.kind,
            summary=payload.detail.get("job_summary"),
        )
        self._jobs[job.id] = job
        return job

    async def submit_page_job(
        self,
        printer_id: UUID,
        payload: PagePayload,
        *,
        api_key_id: UUID | None,
        source_ip: str | None,
        job_id: UUID | None = None,
    ) -> UUID:
        """Persist a QUEUED page job and hand it to the printer's worker.

        Raises:
            MediaKindMismatchError: *printer_id* is a tape printer.
            KeyError: *printer_id* is unknown to the queue.
        """
        if self._removing(printer_id):
            raise KeyError(f"Unknown printer: {printer_id}")
        if printer_id in self._printers:
            raise MediaKindMismatchError()
        if printer_id not in self._page_printers:
            raise KeyError(f"Unknown printer: {printer_id}")
        row = DbJob(
            id=job_id or uuid4(),
            printer_id=printer_id,
            template_key=None,
            payload=payload.model_dump(mode="json"),
            api_key_id=api_key_id,
            source_ip=source_ip,
        )
        job = self._new_page_job(row.id, printer_id, payload)
        try:
            await self._store.save_queued(row)
        except BaseException:
            self._drop_unqueued(job)
            raise
        if job.state != JobState.QUEUED:
            # Cancelled (or cleared) while the row was being saved. The cancellation found no
            # row to persist then, and the insert has just written it as ``queued``: persist
            # it again, or a restart would resurrect the cancelled job. (The tape paths save
            # the row first, so their cancel always finds it.)
            if job.state == JobState.CANCELLED:
                await self._store.mark_cancelled(row.id)
            return row.id
        await self._queues[printer_id].put(PageJob(job=job, payload=payload))
        logger.info("Page job %s queued on %s", row.id, printer_id)
        return row.id

    def is_page_job(self, job_id: str | UUID) -> bool:
        """True if the queue tracks *job_id* as a page job."""
        job = self._jobs.get(str(job_id))
        return job is not None and job.kind is not None

    def is_page_printer(self, printer_id: UUID) -> bool:
        return printer_id in self._page_printers

    async def get(self, job_id: str | UUID) -> Job:
        return self._jobs[str(job_id)]

    async def wait_for_job(self, job_id: str, timeout_s: float = 60.0) -> Job:
        job = self._jobs[job_id]
        # TODO(phase5): expose Job.wait_done() to remove this cross-module
        #               private access to _done_event.
        await asyncio.wait_for(job._done_event.wait(), timeout=timeout_s)
        return job

    # --- per-job control ---------------------------------------------------

    def has_job(self, job_id: str | UUID) -> bool:
        """True if the queue tracks *job_id* in memory (any state)."""
        return str(job_id) in self._jobs

    async def cancel(self, job_id: str) -> bool:
        """Cancel a queued or paused job. Returns False for non-cancellable states.

        The in-memory transition happens before the first ``await`` so it is atomic
        with respect to the worker: the worker either still sees QUEUED (and this
        call then wins the check below) or already moved the job to PRINTING (and
        this call returns False).  The cancellation is then persisted, so the DB
        and the in-memory state cannot disagree about a job that was cancelled.

        Raises:
            KeyError: *job_id* is unknown to the queue.
        """
        job = self._jobs[job_id]
        if job.kind is not None and job.state == JobState.PRINTING:
            # A page job at the printer: send Cancel-Job; the tracking decides the outcome
            # (cancelled, or failed/interrupted when the page had started). The job stays
            # PRINTING until then. A tape job on the wire is never cancelled (ADR 0005).
            if UUID(job_id) in self._resuming:
                # Recovered, tracking not resumed yet: the runner sends Cancel-Job when it
                # picks the job up (``_resume_page_jobs``).
                self._resuming[UUID(job_id)] = True
                return True
            return await self._page_runner.request_cancel(UUID(job_id))
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
        # A store failure propagates (the route answers 5xx instead of a false
        # success); the job stays cancelled in memory, so this process never prints it.
        await self._store.mark_cancelled(UUID(job.id))
        if job.kind is not None:
            await notify_ended(
                job.kind, UUID(job.id), state="cancelled", started=False, error_code="cancelled"
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

    async def pause_printer(
        self,
        printer_id: UUID,
        reason: str = "",
        source: PauseSource = "printer_error",
        since: datetime | None = None,
    ) -> None:
        """Pause the worker for a printer. Any in-flight job completes first.

        *source* records who paused (``user`` for the API, ``printer_error`` for
        the automatic pause after a recoverable hardware error); *reason* is the
        machine-readable code shown in the UI.  A user pause replaces an
        automatic one; repeating the same source keeps the original timestamp.
        """
        if printer_id not in self._worker_states:
            raise KeyError(f"Unknown printer: {printer_id}")
        self._worker_states[printer_id] = PrinterWorkerState.PAUSED
        self._worker_resume_events[printer_id].clear()
        previous = self._pause_info.get(printer_id)
        # A user pause is never turned into an automatic one (which the status producer may
        # lift on its own); an automatic pause may become a user pause.
        keep_user = previous is not None and previous.source == "user"
        if previous is None or (previous.source != source and not keep_user):
            info = PauseInfo(
                source=source,
                reason_code="user" if source == "user" else (reason or "unknown"),
                since=since or datetime.now(UTC),
            )
            self._pause_info[printer_id] = info
            self._notify_pause_change(printer_id, info)
        logger.info("Printer %s paused: %s", printer_id, reason)

    def pause_info(self, printer_id: UUID) -> PauseInfo | None:
        """Pause details while the worker is paused, else ``None``."""
        if self._worker_states.get(printer_id) != PrinterWorkerState.PAUSED:
            return None
        return self._pause_info.get(printer_id)

    def is_paused(self, printer_id: UUID) -> bool:
        """True while the worker for *printer_id* is paused."""
        return self._worker_states.get(printer_id) == PrinterWorkerState.PAUSED

    def _notify_pause_change(self, printer_id: UUID, info: PauseInfo | None) -> None:
        if self._on_pause_change is None:
            return
        try:
            self._on_pause_change(printer_id, info)
        except Exception:
            logger.exception("on_pause_change callback failed for %s", printer_id)

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
        self._pause_info.pop(printer_id, None)
        self._worker_resume_events[printer_id].set()
        self._notify_pause_change(printer_id, None)
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

        Like ``cancel()``, every in-memory transition happens before the first
        ``await`` (so the worker cannot pick up a job that is being cleared), and
        the cancellations are persisted afterwards.  A job the worker already took
        (PRINTING) is left alone.

        O(N) over all-time jobs — acceptable at MVP scale; see TODO(phase5)
        on the _jobs declaration in __init__.
        """
        if printer_id not in self._queues:
            raise KeyError(f"Unknown printer: {printer_id}")
        cleared: list[Job] = []
        for job in self._jobs.values():
            if job.printer_id == printer_id and job.state in (
                JobState.QUEUED,
                JobState.PAUSED,
            ):
                from_state = job.state
                JobStateMachine.transition(job, JobState.CANCELLED)
                cleared.append(job)
                self._notify_state_change(
                    job,
                    from_state,
                    JobState.CANCELLED,
                    queue_depth=self._queue_depth(printer_id),
                )
        # One DB fault must not leave the remaining rows QUEUED: persist every job,
        # then surface the first failure (the route answers 5xx, never a false 204).
        first_error: Exception | None = None
        for job in cleared:
            try:
                await self._store.mark_cancelled(UUID(job.id))
            except Exception as exc:
                logger.exception("clear_queue: persisting cancellation of %s failed", job.id)
                first_error = first_error or exc
        for job in cleared:
            if job.kind is not None:  # queued and held page jobs; tracked ones are PRINTING
                await notify_ended(
                    job.kind,
                    UUID(job.id),
                    state="cancelled",
                    started=False,
                    error_code="cancelled",
                )
        if first_error is not None:
            raise first_error
        return len(cleared)

    async def enqueue_persisted(self, db_job: DbJob) -> None:
        """Hand an already-persisted QUEUED row to the worker (used by retry).

        The row is re-rendered from its stored payload exactly like startup
        recovery does.  Idempotent: a row the queue already tracks is not
        enqueued a second time, so neither a repeated call nor a later
        ``start()`` recovery can print it twice.

        Raises:
            KeyError: the row's printer is not known to the queue.
            UnrenderableJobError: the payload cannot be re-rendered (e.g. a
                webhook-created row, or a payload that no longer validates).
        """
        printer_id = db_job.printer_id
        self._require_tape(printer_id)
        job_key = str(db_job.id)
        if job_key in self._jobs:
            return
        missing = _REQUIRED_RERENDER_KEYS - db_job.payload.keys()
        if missing:
            raise UnrenderableJobError(
                f"Job {db_job.id} payload lacks {sorted(missing)} and cannot be re-rendered"
            )
        # Claim the row BEFORE the slow re-render: from here on the queue tracks it
        # (has_job() is True), so a concurrent cancel()/clear_queue() reaches the
        # in-memory job instead of cancelling only the DB row and then losing the
        # race against the enqueue below.  The image is attached after rendering.
        job = Job(
            id=job_key,
            printer_id=printer_id,
            tape_mm=db_job.payload.get("tape_mm"),
            options=db_job.payload.get("options", {}),
        )
        self._jobs[job_key] = job
        try:
            image = await asyncio.to_thread(self._rerender_from_db_payload, db_job.payload)
            job.image_payload = await asyncio.to_thread(_serialize_image_to_png, image)
        except Exception as exc:
            self._drop_unqueued(job)
            raise UnrenderableJobError(
                f"Job {db_job.id} could not be re-rendered ({exc.__class__.__name__})"
            ) from exc
        except BaseException:
            # CancelledError (client went away): never leave a claimed, never-queued job.
            self._drop_unqueued(job)
            raise
        try:
            persisted = await self._store.get(db_job.id)
        except BaseException:
            self._drop_unqueued(job)
            raise
        # No await from here to the put: the checks and the enqueue are atomic.
        if job.state != JobState.QUEUED:
            return  # cancelled while rendering; cancel() already persisted that
        if persisted is None or persisted.state != DbJobState.QUEUED.value:
            # Cancelled in the DB before the claim (e.g. by a client that saw the row).
            JobStateMachine.transition(job, JobState.CANCELLED)
            self._notify_state_change(
                job,
                JobState.QUEUED,
                JobState.CANCELLED,
                queue_depth=self._queue_depth(printer_id),
            )
            return
        self._queues[printer_id].put_nowait(job)
        logger.info("Job %s (persisted) queued on %s", job_key, printer_id)

    def _veto_print(self, job: Job, printer_id: UUID) -> None:
        """End an in-memory PRINTING job whose DB row refused the pick-up."""
        job.error_code = "cancelled_before_print"
        job.error_msg = "cancelled_before_print"
        JobStateMachine.transition(job, JobState.FAILED)
        self._notify_state_change(
            job,
            JobState.PRINTING,
            JobState.FAILED,
            queue_depth=self._queue_depth(printer_id),
        )
        logger.warning("Job %s not printed: its row is no longer queued", job.id)

    def _drop_unqueued(self, job: Job) -> None:
        """Forget a claimed job that never reached the queue (re-render failed)."""
        if self._jobs.get(job.id) is job:
            del self._jobs[job.id]

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
            if self._removing(printer_id):
                # #224: taken, not started: the job (or batch) stays ``queued`` in the store.
                return

            # Phase 1k.2: BatchJob vs Job — dispatch per isinstance
            if isinstance(item, BatchJob):
                await self._process_batch(printer, printer_id, item)
                continue
            if isinstance(item, PageJob):  # pragma: no cover - D18: submit paths refuse this
                logger.error("Tape printer %s got a page job; dropped", printer_id)
                continue

            job = item

            # Wait while paused — pause may have been set while we were idle at
            # queue.get(), so this check must come AFTER the pop.
            while self._worker_states[printer_id] == PrinterWorkerState.PAUSED:
                if self._stopping or self._removing(printer_id):
                    return
                await self._worker_resume_events[printer_id].wait()
            if self._removing(printer_id):
                return  # resumed and removed at once

            # Job may have been cancelled or paused between submit and pop.
            if job.state != JobState.QUEUED:
                continue

            # Take the job in memory FIRST, with no await between the check above
            # and this transition: a concurrent cancel()/clear_queue() either ran
            # before (state != QUEUED, skipped above) or now sees PRINTING and
            # refuses.  Persisting first left a window (the DB await) in which a
            # cancel was accepted and the job was printed anyway.
            _from = job.state
            JobStateMachine.transition(job, JobState.PRINTING)
            self._notify_state_change(
                job,
                _from,
                JobState.PRINTING,
                queue_depth=self._queue_depth(printer_id),
            )

            try:
                # Phase 2: DB-State QUEUED->PRINTING persistieren (bridge: dataclass.id ist str)
                if not await self._store.mark_printing(UUID(job.id)):
                    # The row is no longer QUEUED (cancelled through the API): the DB
                    # is authoritative, never print.  The state machine has no
                    # PRINTING -> CANCELLED edge, so the in-memory job ends FAILED
                    # (which also releases wait_for_job); the terminal row is untouched.
                    self._veto_print(job, printer_id)
                    continue
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
                    # close cover / fix connectivity, then POST /api/v1/printer/resume
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

    def _notify_page_change(self, job: Job, from_state: JobState, to_state: JobState) -> None:
        """Event hook of the page-job runner (``from == to`` = ``at_printer`` changed)."""
        self._notify_state_change(
            job, from_state, to_state, queue_depth=self._queue_depth(job.printer_id)
        )

    async def _page_worker(self, printer_id: UUID) -> None:
        """D18: consume a page printer's queue, one page job at the printer at a time.

        A job the pre-flight deferred waits in the held slot and is taken before anything
        from the queue, so it keeps its place; the printer is paused with
        ``source="printer_error"`` until the status producer (or the user) resumes it.
        """
        printer = self._page_printers[printer_id]
        queue = self._queues[printer_id]
        await self._resume_page_jobs(printer, printer_id)
        while True:
            item = self._held[printer_id]
            if item is not None:
                self._held[printer_id] = None
            else:
                got = await queue.get()
                if got is None:  # sentinel — stop() requested a clean exit
                    return
                if not isinstance(got, PageJob):  # pragma: no cover - submit paths guard this
                    logger.error("Page printer %s got a tape item; dropped", printer_id)
                    continue
                item = got
            if self._removing(printer_id):
                return  # #224: taken, not started: the row stays ``queued``
            while self._worker_states[printer_id] == PrinterWorkerState.PAUSED:
                if self._stopping or self._removing(printer_id):
                    return
                await self._worker_resume_events[printer_id].wait()
            if self._stopping or self._removing(printer_id):
                return
            if item.job.state != JobState.QUEUED:
                continue  # cancelled (or cleared) while waiting
            try:
                await self._page_runner.run(printer, item)
            except Deferred as deferred:
                if _state_of(item.job) != JobState.QUEUED:
                    continue  # cancelled during the pre-flight: nothing to hold, no pause
                self._held[printer_id] = item
                await self.pause_printer(
                    printer_id, reason=deferred.reason_code, source="printer_error"
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                await self._page_backstop(item, printer_id)

    async def _page_backstop(self, item: PageJob, printer_id: UUID) -> None:
        """The runner ends every job itself; this is the backstop for a bug in it."""
        logger.exception("Page job %s: runner failed on %s", item.job.id, printer_id)
        if _state_of(item.job) == JobState.PRINTING:
            message = "The printer may have printed the page; its outcome is unknown."
            # 1. persist, best effort
            try:
                await self._store.mark_failed_code(UUID(item.job.id), "interrupted", message, None)
            except Exception:
                # The database is failing too; the row stays ``printing`` and the next
                # start settles it. The worker must not die of it.
                logger.exception("Page job %s: backstop could not persist the end", item.job.id)
            # 2. the terminal state in memory (this releases the waiters), 3. the same event a
            # normal failure emits, 4. the outcome handler: the page may have printed.
            item.job.error_code = "interrupted"
            item.job.error_message = message
            item.job.error_msg = message
            with contextlib.suppress(InvalidStateTransitionError):
                JobStateMachine.transition(item.job, JobState.FAILED)
            if _state_of(item.job) == JobState.FAILED:
                self._notify_page_change(item.job, JobState.PRINTING, JobState.FAILED)
                try:
                    await notify_ended(
                        item.payload.kind,
                        UUID(item.job.id),
                        state="failed",
                        started=True,
                        error_code="interrupted",
                    )
                except Exception:
                    logger.exception("Page job %s: backstop outcome call failed", item.job.id)

    async def _resume_page_jobs(self, printer: PagePrinter, printer_id: UUID) -> None:
        """Resume tracking of the jobs the printer held across a hub restart.

        Runs before the worker takes anything from its queue, and whether or not the printer
        is paused: the job is at the printer already. One Get-Jobs ``not-completed`` asks what
        the printer still holds; a tracked id it does not list is looked up once, and ends
        ``interrupted`` only if the printer no longer knows it. If the printer cannot be
        asked, nothing is failed: the tracking resumes and waits like any tracked job (OC-23).
        """
        items = self._to_resume.pop(printer_id, [])
        if not items:
            return
        try:
            await self._resume_listed(printer, printer_id, items)
        finally:
            for item in items:
                self._resuming.pop(UUID(item.job.id), None)

    async def _resume_listed(
        self, printer: PagePrinter, printer_id: UUID, items: list[PageJob]
    ) -> None:
        try:
            listed: dict[int, JobInfo] | None = {
                j.job_id: j for j in await printer.client.get_jobs()
            }
        except IppError as exc:
            logger.info("Recovery: %s could not list its jobs (%s)", printer_id, type(exc).__name__)
            listed = None
        for item in items:
            if self._stopping or self._removing(printer_id):
                return
            ipp_job_id = (item.resume_result or {})["ipp_job_id"]
            expected = wire_job_name(item.payload.job_name, item.job.id)
            try:
                if listed is not None:
                    seen = listed.get(ipp_job_id)
                    if seen is not None:
                        # Listed under the stored id: ours only if the name and user are the
                        # hub's (the printer may have reused the id after a reboot).
                        foreign = not is_own_job(seen.name, seen.originating_user, expected)
                    else:
                        foreign = await self._printer_forgot(printer, ipp_job_id, expected)
                    if foreign:
                        await self._page_runner.end_forgotten(item)
                        continue
                # No await between this read and ``resume`` registering the job: a cancel
                # either landed before (and is passed on) or finds the job active.
                cancel = self._resuming.pop(UUID(item.job.id), False)
                await self._page_runner.resume(printer, item, cancel_requested=cancel)
            except asyncio.CancelledError:
                raise
            except Exception:
                await self._page_backstop(item, printer_id)

    @staticmethod
    async def _printer_forgot(printer: PagePrinter, ipp_job_id: int, expected_name: str) -> bool:
        """True when the printer has no such job, or the id now belongs to another job."""
        try:
            info = await printer.client.get_job(ipp_job_id)
        except IppNotFoundError:
            return True
        except IppError:
            return False
        return not is_own_job(info.name, info.originating_user, expected_name)

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
        waited = False
        while self._worker_states[printer_id] == PrinterWorkerState.PAUSED:
            if self._stopping or self._removing(printer_id):
                return
            waited = True
            await self._worker_resume_events[printer_id].wait()
        if waited and self._removing(printer_id):
            return  # resumed and removed at once

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
            if idx > 0 and self._removing(printer_id):
                # #224: removed while the items were taken: the rest stays ``queued``; the
                # items already taken (rows ``printing``) print together.
                break
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
                if not await self._store.mark_printing(UUID(job.id)):
                    self._veto_print(job, printer_id)  # row cancelled via the API: skip item
                    continue
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


def _state_of(job: Job) -> JobState:
    """The job's current state (read through a call: it changes across awaits)."""
    return job.state


async def load_manual_pauses(session: AsyncSession) -> dict[UUID, datetime]:
    """Printers whose ``printer_state.paused`` flag is set, with the time it was set.

    Pass the result to ``PrintQueue.start(initially_paused=...)``: a fresh queue
    starts every worker ACTIVE, so without it a printer the user stopped would
    print recovered jobs again after a restart while the UI still says Paused.
    """
    result = await session.execute(select(PrinterState).where(col(PrinterState.paused).is_(True)))
    paused: dict[UUID, datetime] = {}
    for row in result.scalars().all():
        since = row.updated_at
        paused[row.printer_id] = since if since.tzinfo else since.replace(tzinfo=UTC)
    return paused
