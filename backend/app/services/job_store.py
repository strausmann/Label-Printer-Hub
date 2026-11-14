# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Phase 2: JobStore Protocol + MemoryJobStore in-memory Implementation.

JobStore ist die Persistierungs-Boundary die PrintQueue nutzt um Job-State-Transitionen
zu speichern. SQLiteJobStore (Produktion) implementiert dieses Protocol durch Delegation
an jobs_repo. MemoryJobStore ist die Test/Migration-Impl.

Klärung (R2-C1): Alle Store-Methoden arbeiten auf app.models.job.Job
(SQLModel, UUID-id). Der Worker-Code in print_queue.py verwendet
app.services.job_lifecycle.Job (Dataclass, str-id). Bridge:
  Worker ruft self._store.mark_printing(UUID(job.id))
  Store arbeitet intern auf UUID-Schlüsseln.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from app.models.job import Job, JobState, is_page_payload

_NON_TERMINAL = (JobState.QUEUED.value, JobState.PRINTING.value)
_CANCELLABLE_PAGE = (JobState.QUEUED.value, JobState.PRINTING.value)
_TERMINAL = (
    JobState.DONE.value,
    JobState.FAILED.value,
    JobState.FAILED_RESTART.value,
    JobState.CANCELLED.value,
)


def _with_detail(
    result: dict[str, Any] | None, detail: dict[str, Any] | None
) -> dict[str, Any] | None:
    """``result`` with ``error_detail`` merged in (unchanged when there is no detail)."""
    if detail is None:
        return result
    return {**(result or {}), "error_detail": dict(detail)}


@runtime_checkable
class JobStore(Protocol):
    """Persistente Backing-Store für Jobs.

    Alle Methoden sind async und können I/O durchführen. Implementierungen müssen
    sicher für gleichzeitige Aufrufe aus mehreren asyncio-Tasks sein.
    """

    async def save_queued(self, job: Job) -> None:
        """Persist a newly-created QUEUED job (insert).

        Called from PrintService.submit_print_job BEFORE handing off
        to the queue. After this returns, the job is durable.
        """

    async def get(self, job_id: UUID) -> Job | None:
        """Load a job by ID. None if not found."""

    async def mark_printing(self, job_id: UUID) -> bool:
        """Transition QUEUED -> PRINTING. Called by worker when it picks up the job.

        Returns True when the worker may print: the transition happened, or the
        store does not know the job at all (callers may race against eviction, and
        a job submitted without a row has nothing that could have cancelled it).
        Returns False when the row exists but is no longer QUEUED (e.g. cancelled
        through the API): the worker must NOT print such a job.

        Must NOT raise on missing jobs.
        """

    async def mark_done(self, job_id: UUID) -> None:
        """Transition PRINTING -> DONE. Called by worker after successful print.

        Silently no-op if job_id does not exist in the store. Implementations
        must NOT raise on missing jobs — callers may race against eviction.
        """

    async def mark_failed(self, job_id: UUID, error: str) -> None:
        """Transition any non-terminal -> FAILED with given error message.

        Silently no-op if job_id does not exist in the store. Implementations
        must NOT raise on missing jobs — callers may race against eviction.
        """

    async def mark_cancelled(self, job_id: UUID, *, allow_printing: bool = False) -> None:
        """Transition QUEUED -> CANCELLED. Called by PrintQueue.cancel()/clear_queue().

        Only a QUEUED job can be cancelled: a PRINTING tape job is already on the wire
        (mid-print abort is unsafe over TCP/9100) and terminal jobs stay as they
        are.  Silently no-op if job_id does not exist or is not QUEUED.

        ``allow_printing=True`` also ends a PRINTING row: only the page-job runner passes
        it, after the IPP printer confirmed the cancel of a job that never started.
        """

    async def set_result(self, job_id: UUID, result: dict[str, Any]) -> None:
        """Replace the job's ``result`` (page jobs: phase, IPP job id, ``started``).

        Silently no-op if job_id does not exist.
        """

    async def mark_failed_code(
        self,
        job_id: UUID,
        code: str,
        message: str,
        detail: dict[str, Any] | None,
        *,
        result: dict[str, Any] | None = None,
    ) -> None:
        """Transition any non-terminal -> FAILED with ``error = "<code>: <message>"``.

        ``result`` (when given) replaces the stored result, and ``detail`` (when given) is
        merged into it as ``error_detail`` — all in the same write as the state change, so a
        crash leaves either the old row or the finished one, never a half-written mix.
        Silently no-op if job_id does not exist or the row is already terminal.
        """

    async def mark_interrupted(self, printer_id: UUID) -> int:
        """Recovery: set all PRINTING *tape* jobs of this printer to FAILED_RESTART
        with error='printer_interrupted'.

        Page jobs (``payload.kind`` set) are left alone: the IPP printer still holds them
        and ``PrintQueue.start()`` resumes or settles each one (``list_page_jobs_in_flight``,
        ``mark_failed_restart``).

        Called from PrintQueue.start() BEFORE list_pending.

        Returns the count of affected rows.
        """

    async def list_page_jobs_in_flight(self, printer_id: UUID | None = None) -> list[Job]:
        """PRINTING page jobs (``payload.kind`` set) of this printer (``None``: of every
        printer), oldest first."""

    async def mark_failed_restart(self, job_id: UUID, error: str) -> None:
        """PRINTING -> FAILED_RESTART with *error* (a page job whose outcome is unknown).

        Silently no-op if job_id does not exist or the row is not PRINTING.
        """

    async def list_pending(self, printer_id: UUID) -> list[Job]:
        """Return all non-terminal jobs for this printer, sorted by created_at (FIFO).

        Called from PrintQueue.start() AFTER mark_interrupted to find
        QUEUED jobs that need to be re-enqueued.
        """

    async def evict_terminal_older_than(self, age: timedelta) -> int:
        """Delete terminal jobs (DONE/FAILED/FAILED_RESTART/CANCELLED) with
        finished_at older than `age` ago. Used by CleanupTask.

        Returns the count of deleted rows.
        """


class MemoryJobStore(JobStore):
    """In-Memory JobStore für Tests und PrintService Boot-Phase.

    Hält Job-Objekte in einem Dict mit id als Schlüssel. Nicht thread-safe, aber
    sicher für asyncio Single-Event-Loop-Nutzung.
    """

    def __init__(self) -> None:
        self._jobs: dict[UUID, Job] = {}

    async def save_queued(self, job: Job) -> None:
        self._jobs[job.id] = job

    async def get(self, job_id: UUID) -> Job | None:
        return self._jobs.get(job_id)

    async def mark_printing(self, job_id: UUID) -> bool:
        job = self._jobs.get(job_id)
        if job is None:
            return True
        if job.state != JobState.QUEUED.value:
            return False
        job.state = JobState.PRINTING.value
        job.started_at = datetime.now(UTC)
        return True

    async def mark_done(self, job_id: UUID) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.state = JobState.DONE.value
        job.finished_at = datetime.now(UTC)

    async def mark_failed(self, job_id: UUID, error: str) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.state = JobState.FAILED.value
        job.error = error
        job.finished_at = datetime.now(UTC)

    async def mark_cancelled(self, job_id: UUID, *, allow_printing: bool = False) -> None:
        job = self._jobs.get(job_id)
        allowed = _CANCELLABLE_PAGE if allow_printing else (JobState.QUEUED.value,)
        if job is None or job.state not in allowed:
            return
        job.state = JobState.CANCELLED.value
        job.finished_at = datetime.now(UTC)

    async def set_result(self, job_id: UUID, result: dict[str, Any]) -> None:
        job = self._jobs.get(job_id)
        if job is not None:
            job.result = dict(result)

    async def mark_failed_code(
        self,
        job_id: UUID,
        code: str,
        message: str,
        detail: dict[str, Any] | None,
        *,
        result: dict[str, Any] | None = None,
    ) -> None:
        job = self._jobs.get(job_id)
        if job is None or job.state in _TERMINAL:
            return
        job.state = JobState.FAILED.value
        job.error = f"{code}: {message}"
        job.result = _with_detail(dict(result) if result is not None else job.result, detail)
        job.finished_at = datetime.now(UTC)

    async def mark_interrupted(self, printer_id: UUID) -> int:
        count = 0
        for job in self._jobs.values():
            if (
                job.printer_id == printer_id
                and job.state == JobState.PRINTING.value
                and not is_page_payload(job.payload)
            ):
                job.state = JobState.FAILED_RESTART.value
                job.error = "printer_interrupted"
                job.finished_at = datetime.now(UTC)
                count += 1
        return count

    async def list_page_jobs_in_flight(self, printer_id: UUID | None = None) -> list[Job]:
        items = [
            j
            for j in self._jobs.values()
            if (printer_id is None or j.printer_id == printer_id)
            and j.state == JobState.PRINTING.value
            and is_page_payload(j.payload)
        ]
        return sorted(items, key=lambda j: j.created_at)

    async def mark_failed_restart(self, job_id: UUID, error: str) -> None:
        job = self._jobs.get(job_id)
        if job is None or job.state != JobState.PRINTING.value:
            return
        job.state = JobState.FAILED_RESTART.value
        job.error = error
        job.finished_at = datetime.now(UTC)

    async def list_pending(self, printer_id: UUID) -> list[Job]:
        items = [
            j
            for j in self._jobs.values()
            if j.printer_id == printer_id and j.state in _NON_TERMINAL
        ]
        return sorted(items, key=lambda j: j.created_at)

    async def evict_terminal_older_than(self, age: timedelta) -> int:
        cutoff = datetime.now(UTC) - age
        to_delete = [
            jid
            for jid, j in self._jobs.items()
            if j.state in _TERMINAL and j.finished_at is not None and j.finished_at < cutoff
        ]
        for jid in to_delete:
            del self._jobs[jid]
        return len(to_delete)
