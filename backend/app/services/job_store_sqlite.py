"""SQLite-backed JobStore — delegates to jobs_repo for actual SQL.

Uses async_sessionmaker für per-operation sessions so we get clean
transactions and no connection-pool starvation.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.job import Job, JobState
from app.repositories import jobs as jobs_repo
from app.services.job_store import JobStore

logger = logging.getLogger(__name__)


class SQLiteJobStore(JobStore):
    """SQLite-backed JobStore implementation.

    Delegates alle State-Übergänge an jobs_repo. Jede Operation öffnet
    eine eigene Session (per-operation pattern) — kein Session-Sharing
    zwischen parallelen asyncio-Tasks.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save_queued(self, job: Job) -> None:
        """Persist a newly-created QUEUED job via session.add + commit + refresh."""
        async with self._session_factory() as session:
            session.add(job)
            await session.commit()
            await session.refresh(job)

    async def get(self, job_id: UUID) -> Job | None:
        """Load a job by ID. None if not found."""
        async with self._session_factory() as session:
            return await jobs_repo.get(session, job_id)

    async def mark_printing(self, job_id: UUID) -> None:
        """Transition QUEUED -> PRINTING. Silently no-op if job not found."""
        async with self._session_factory() as session:
            job = await jobs_repo.get(session, job_id)
            if job is None:
                return  # silent no-op (Protocol contract)
            if job.state != JobState.QUEUED.value:
                logger.warning(
                    "mark_printing called on job %s in state %s (expected queued)",
                    job_id,
                    job.state,
                )
                return
            await jobs_repo.mark_printing(session, job_id)

    async def mark_done(self, job_id: UUID) -> None:
        """Transition PRINTING -> DONE.

        Delegiert an jobs_repo.mark_done mit result={} — JobStore-Protocol
        speichert kein structured result (Phase-2 YAGNI; ergänzbar via
        `set_result` Methode wenn Hangar das später braucht).
        """
        async with self._session_factory() as session:
            job = await jobs_repo.get(session, job_id)
            if job is None:
                return  # silent no-op (Protocol contract)
            if job.state != JobState.PRINTING.value:
                logger.warning(
                    "mark_done called on job %s in state %s (expected printing)",
                    job_id,
                    job.state,
                )
                return
            await jobs_repo.mark_done(session, job_id, result={})

    async def mark_failed(self, job_id: UUID, error: str) -> None:
        """Transition any non-terminal -> FAILED. Silently no-op if job not found."""
        _terminal = {
            JobState.DONE.value,
            JobState.FAILED.value,
            JobState.CANCELLED.value,
            JobState.FAILED_RESTART.value,
        }
        async with self._session_factory() as session:
            job = await jobs_repo.get(session, job_id)
            if job is None:
                return  # silent no-op (Protocol contract)
            if job.state in _terminal:
                logger.warning(
                    "mark_failed called on job %s in terminal state %s",
                    job_id,
                    job.state,
                )
                return
            await jobs_repo.mark_failed(session, job_id, error)

    async def mark_interrupted(self, printer_id: UUID) -> int:
        """Recovery: mark all PRINTING jobs of this printer as FAILED_RESTART."""
        async with self._session_factory() as session:
            return await jobs_repo.mark_printing_as_failed_restart(session, printer_id)

    async def list_pending(self, printer_id: UUID) -> list[Job]:
        """Return all non-terminal jobs for this printer, sorted by created_at (FIFO)."""
        async with self._session_factory() as session:
            return await jobs_repo.list_active(session, printer_id=printer_id)

    async def evict_terminal_older_than(self, age: timedelta) -> int:
        """Delete terminal jobs older than age. Returns count of deleted rows."""
        async with self._session_factory() as session:
            return await jobs_repo.evict_terminal_older_than(session, age)
