"""SQLite-backed JobStore — delegates to jobs_repo for actual SQL.

Uses async_sessionmaker für per-operation sessions so we get clean
transactions and no connection-pool starvation.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any
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

    async def mark_printing(self, job_id: UUID) -> bool:
        """Transition QUEUED -> PRINTING.

        Returns True if the transition happened or the job is unknown (no veto);
        False if the row exists but is no longer QUEUED (the worker must not print).
        """
        async with self._session_factory() as session:
            job = await jobs_repo.get(session, job_id)
            if job is None:
                return True  # nothing could have cancelled it (Protocol contract)
            if job.state != JobState.QUEUED.value:
                logger.warning(
                    "mark_printing refused for job %s in state %s (expected queued); "
                    "the worker will not print it",
                    job_id,
                    job.state,
                )
                return False
            await jobs_repo.mark_printing(session, job_id)
            return True

    async def mark_done(self, job_id: UUID) -> None:
        """Transition PRINTING -> DONE.

        Keeps the stored ``result`` (page jobs write it through ``set_result``);
        a job without one ends with ``result={}`` as before.
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
            await jobs_repo.mark_done(session, job_id, result=job.result or {})

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

    async def mark_cancelled(self, job_id: UUID, *, allow_printing: bool = False) -> None:
        """Transition QUEUED -> CANCELLED (page jobs: also PRINTING, ``allow_printing``).

        Silently no-op if not found or in another state.
        """
        allowed = {JobState.QUEUED.value}
        if allow_printing:
            allowed.add(JobState.PRINTING.value)
        async with self._session_factory() as session:
            job = await jobs_repo.get(session, job_id)
            if job is None:
                return  # silent no-op (Protocol contract)
            if job.state not in allowed:
                logger.warning(
                    "mark_cancelled called on job %s in state %s (expected queued)",
                    job_id,
                    job.state,
                )
                return
            await jobs_repo.mark_cancelled(session, job_id)

    async def set_result(self, job_id: UUID, result: dict[str, Any]) -> None:
        """Replace the job's ``result``. Silently no-op if not found."""
        async with self._session_factory() as session:
            await jobs_repo.set_result(session, job_id, result)

    async def mark_failed_code(
        self, job_id: UUID, code: str, message: str, detail: dict[str, Any] | None
    ) -> None:
        """Non-terminal -> FAILED with ``"<code>: <message>"``; ``detail`` into ``result``."""
        async with self._session_factory() as session:
            job = await jobs_repo.get(session, job_id)
            if job is None:
                return
            if job.state not in (JobState.QUEUED.value, JobState.PRINTING.value):
                logger.warning(
                    "mark_failed_code called on job %s in terminal state %s", job_id, job.state
                )
                return
            if detail is not None:
                await jobs_repo.set_result(
                    session, job_id, {**(job.result or {}), "error_detail": dict(detail)}
                )
            await jobs_repo.mark_failed(session, job_id, f"{code}: {message}")

    async def mark_interrupted(self, printer_id: UUID) -> int:
        """Recovery: mark all PRINTING tape jobs of this printer as FAILED_RESTART."""
        async with self._session_factory() as session:
            return await jobs_repo.mark_printing_as_failed_restart(session, printer_id)

    async def list_page_jobs_in_flight(self, printer_id: UUID | None = None) -> list[Job]:
        """PRINTING page jobs of this printer (``None``: of every printer), oldest first."""
        async with self._session_factory() as session:
            return await jobs_repo.list_page_jobs_in_flight(session, printer_id)

    async def mark_failed_restart(self, job_id: UUID, error: str) -> None:
        """PRINTING -> FAILED_RESTART with *error*. Silently no-op otherwise."""
        async with self._session_factory() as session:
            await jobs_repo.mark_failed_restart(session, job_id, error)

    async def list_pending(self, printer_id: UUID) -> list[Job]:
        """Return all non-terminal jobs for this printer, sorted by created_at (FIFO)."""
        async with self._session_factory() as session:
            return await jobs_repo.list_active(session, printer_id=printer_id)

    async def evict_terminal_older_than(self, age: timedelta) -> int:
        """Delete terminal jobs older than age. Returns count of deleted rows."""
        async with self._session_factory() as session:
            return await jobs_repo.evict_terminal_older_than(session, age)
