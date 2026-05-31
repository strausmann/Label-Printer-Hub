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
from typing import Protocol, runtime_checkable
from uuid import UUID

from app.models.job import Job, JobState

_NON_TERMINAL = (JobState.QUEUED.value, JobState.PRINTING.value)
_TERMINAL = (
    JobState.DONE.value,
    JobState.FAILED.value,
    JobState.FAILED_RESTART.value,
    JobState.CANCELLED.value,
)


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

    async def mark_printing(self, job_id: UUID) -> None:
        """Transition QUEUED -> PRINTING. Called by worker when it picks up the job."""

    async def mark_done(self, job_id: UUID) -> None:
        """Transition PRINTING -> DONE. Called by worker after successful print."""

    async def mark_failed(self, job_id: UUID, error: str) -> None:
        """Transition any non-terminal -> FAILED with given error message."""

    async def mark_interrupted(self, printer_id: UUID) -> int:
        """Recovery: set all PRINTING jobs of this printer to FAILED_RESTART
        with error='printer_interrupted'.

        Called from PrintQueue.start() BEFORE list_pending.

        Returns the count of affected rows.
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


class MemoryJobStore:
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

    async def mark_printing(self, job_id: UUID) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.state = JobState.PRINTING.value
        job.started_at = datetime.now(UTC)

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

    async def mark_interrupted(self, printer_id: UUID) -> int:
        count = 0
        for job in self._jobs.values():
            if job.printer_id == printer_id and job.state == JobState.PRINTING.value:
                job.state = JobState.FAILED_RESTART.value
                job.error = "printer_interrupted"
                job.finished_at = datetime.now(UTC)
                count += 1
        return count

    async def list_pending(self, printer_id: UUID) -> list[Job]:
        items = [
            j for j in self._jobs.values()
            if j.printer_id == printer_id and j.state in _NON_TERMINAL
        ]
        return sorted(items, key=lambda j: j.created_at)

    async def evict_terminal_older_than(self, age: timedelta) -> int:
        cutoff = datetime.now(UTC) - age
        to_delete = [
            jid for jid, j in self._jobs.items()
            if j.state in _TERMINAL and j.finished_at is not None and j.finished_at < cutoff
        ]
        for jid in to_delete:
            del self._jobs[jid]
        return len(to_delete)
