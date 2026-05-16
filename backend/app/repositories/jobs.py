"""Repository for Job aggregate — state-machine transitions + queries."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.job import Job, JobState


async def create_queued(
    session: AsyncSession,
    *,
    printer_id: UUID,
    template_key: str,
    payload: dict[str, Any],
) -> Job:
    """Insert a new job in QUEUED state and return it."""
    job = Job(
        printer_id=printer_id,
        template_key=template_key,
        payload=payload,
        state=JobState.QUEUED.value,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def _get_or_raise(session: AsyncSession, job_id: UUID) -> Job:
    job = await session.get(Job, job_id)
    if job is None:
        raise ValueError(f"Job {job_id} not found")
    return job


async def mark_printing(session: AsyncSession, job_id: UUID) -> Job:
    """Transition QUEUED → PRINTING. Sets started_at."""
    job = await _get_or_raise(session, job_id)
    if job.state != JobState.QUEUED.value:
        raise ValueError(
            f"Cannot mark_printing: job {job_id} is in state '{job.state}', expected 'queued'"
        )
    job.state = JobState.PRINTING.value
    job.started_at = datetime.now(UTC)
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def mark_done(
    session: AsyncSession, job_id: UUID, result: dict[str, Any] | None = None
) -> Job:
    """Transition PRINTING → DONE. Sets finished_at."""
    job = await _get_or_raise(session, job_id)
    if job.state != JobState.PRINTING.value:
        raise ValueError(
            f"Cannot mark_done: job {job_id} is in state '{job.state}', expected 'printing'"
        )
    job.state = JobState.DONE.value
    job.result = result
    job.finished_at = datetime.now(UTC)
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def mark_failed(session: AsyncSession, job_id: UUID, error: str) -> Job:
    """Transition QUEUED|PRINTING → FAILED. Sets finished_at."""
    job = await _get_or_raise(session, job_id)
    if job.state not in (JobState.QUEUED.value, JobState.PRINTING.value):
        raise ValueError(
            f"Cannot mark_failed: job {job_id} is in state '{job.state}', "
            "expected 'queued' or 'printing'"
        )
    job.state = JobState.FAILED.value
    job.error = error
    job.finished_at = datetime.now(UTC)
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def mark_cancelled(session: AsyncSession, job_id: UUID) -> Job:
    """Transition QUEUED|PRINTING → CANCELLED. Sets finished_at."""
    job = await _get_or_raise(session, job_id)
    if job.state not in (JobState.QUEUED.value, JobState.PRINTING.value):
        raise ValueError(
            f"Cannot mark_cancelled: job {job_id} is in state '{job.state}', "
            "expected 'queued' or 'printing'"
        )
    job.state = JobState.CANCELLED.value
    job.finished_at = datetime.now(UTC)
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def mark_inflight_as_failed_restart(session: AsyncSession) -> int:
    """UPDATE all QUEUED|PRINTING jobs to FAILED_RESTART at startup.

    Returns the count of affected rows.
    """
    inflight = (JobState.QUEUED.value, JobState.PRINTING.value)
    stmt = (
        update(Job)
        .where(col(Job.state).in_(inflight))  # col() gives proper Column typing for .in_()
        .values(
            state=JobState.FAILED_RESTART.value,
            error="restart_during_inflight",
            finished_at=datetime.now(UTC),
        )
        .execution_options(synchronize_session="fetch")
    )
    result = await session.execute(stmt)
    await session.commit()
    return int(result.rowcount)  # type: ignore[attr-defined]  # rowcount on UPDATE result


async def list_active(session: AsyncSession) -> list[Job]:
    """Return all jobs in QUEUED or PRINTING state (covered by ix_jobs_state)."""
    inflight = (JobState.QUEUED.value, JobState.PRINTING.value)
    result = await session.execute(
        select(Job)
        .where(col(Job.state).in_(inflight))  # col() gives proper Column typing for .in_()
        .order_by(col(Job.created_at))  # col() gives proper Column typing
    )
    return list(result.scalars())
