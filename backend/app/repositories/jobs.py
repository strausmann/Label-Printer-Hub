# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Repository for Job aggregate — state-machine transitions + queries."""

from __future__ import annotations

import json
from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, NamedTuple
from uuid import UUID

from sqlalchemy import and_, delete, exists, func, literal_column, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.job import PAGE_KIND_EXPR, Job, JobState, is_page_payload, json_at
from app.models.sheet import Sheet, SheetCell


async def get(session: AsyncSession, job_id: UUID) -> Job | None:
    """Return the Job row for ``job_id``, or ``None`` if not found."""
    return await session.get(Job, job_id)


async def list_by_filter(
    session: AsyncSession,
    *,
    state: str | None = None,
    printer_id: UUID | None = None,
    since: datetime | None = None,
    limit: int = 50,
    allowed_printer_ids: list[UUID] | None = None,
    api_key_id: UUID | None = None,
    order: Literal["oldest", "newest"] = "oldest",
) -> list[Job]:
    """Return jobs matching the optional filters, ordered by creation time.

    All filters are ANDed. ``limit`` caps the result set (default 50).
    ``allowed_printer_ids`` restricts to those printers (``None`` or empty = no
    restriction); it is applied in SQL so ``limit`` counts only visible jobs.
    ``api_key_id`` keeps only the jobs that key submitted (``None`` = no restriction).
    ``order`` is ``oldest`` (default: the first ``limit`` jobs) or ``newest`` (the latest
    ``limit`` jobs, newest first); every filter above applies before the cut.
    """
    stmt = select(Job)
    if state is not None:
        stmt = stmt.where(col(Job.state) == state)
    if printer_id is not None:
        stmt = stmt.where(col(Job.printer_id) == printer_id)
    if allowed_printer_ids:
        stmt = stmt.where(col(Job.printer_id).in_(allowed_printer_ids))
    if api_key_id is not None:
        stmt = stmt.where(col(Job.api_key_id) == api_key_id)
    if since is not None:
        stmt = stmt.where(col(Job.created_at) >= since)
    created = col(Job.created_at)
    # ``id`` breaks ties, so equal timestamps keep one stable order and a ``limit`` cut is exact.
    ident = col(Job.id)
    if order == "newest":
        stmt = stmt.order_by(created.desc(), ident.desc())
    else:
        stmt = stmt.order_by(created, ident)
    stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars())


async def create_queued(
    session: AsyncSession,
    *,
    printer_id: UUID,
    template_key: str | None,
    payload: dict[str, Any],
    api_key_id: UUID | None = None,
    source_ip: str | None = None,
) -> Job:
    """Insert a new job in QUEUED state and return it."""
    job = Job(
        printer_id=printer_id,
        template_key=template_key,
        payload=payload,
        state=JobState.QUEUED.value,
        api_key_id=api_key_id,
        source_ip=source_ip,
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


async def mark_printing_if_queued(session: AsyncSession, job_id: UUID) -> bool:
    """QUEUED -> PRINTING in one guarded statement; ``False``: the row is unknown or no longer
    ``queued``, nothing written.

    The test and the write are one statement, so a cancel that commits between a caller's
    read and this write is never overwritten (re-review R2-1): the worker must not print then.
    """
    stmt = (
        update(Job)
        .where(col(Job.id) == job_id, col(Job.state) == JobState.QUEUED.value)
        .values(state=JobState.PRINTING.value, started_at=datetime.now(UTC))
        .execution_options(synchronize_session=False)
    )
    result = await session.execute(stmt)
    await session.commit()
    return int(result.rowcount) > 0  # type: ignore[attr-defined]


async def mark_printing(session: AsyncSession, job_id: UUID) -> Job:
    """Transition QUEUED → PRINTING. Sets started_at. Raises ``ValueError`` otherwise."""
    if not await mark_printing_if_queued(session, job_id):
        current = await _get_or_raise(session, job_id)
        raise ValueError(
            f"Cannot mark_printing: job {job_id} is in state '{current.state}', expected 'queued'"
        )
    job = await session.get(Job, job_id, populate_existing=True)
    assert job is not None  # just written
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


async def mark_failed(
    session: AsyncSession, job_id: UUID, error: str, *, result: dict[str, Any] | None = None
) -> Job:
    """Transition QUEUED|PRINTING → FAILED. Sets finished_at.

    ``result`` (when given) replaces the stored result in the same commit as the state.
    """
    job = await _get_or_raise(session, job_id)
    if job.state not in (JobState.QUEUED.value, JobState.PRINTING.value):
        raise ValueError(
            f"Cannot mark_failed: job {job_id} is in state '{job.state}', "
            "expected 'queued' or 'printing'"
        )
    job.state = JobState.FAILED.value
    job.error = error
    if result is not None:
        job.result = dict(result)
    job.finished_at = datetime.now(UTC)
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def set_result(session: AsyncSession, job_id: UUID, result: dict[str, Any]) -> Job | None:
    """Replace ``result`` of a job (any state). Returns ``None`` when the job is unknown."""
    job = await session.get(Job, job_id)
    if job is None:
        return None
    job.result = dict(result)
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def set_loaded_roll(session: AsyncSession, job_id: UUID, roll: dict[str, Any]) -> bool:
    """Set ``payload.loaded_roll`` of a job (any state, #389): the roll it was sent to.

    ``False`` when the job is unknown. The rest of the payload is kept.
    """
    job = await session.get(Job, job_id)
    if job is None:
        return False
    job.payload = {**(job.payload or {}), "loaded_roll": dict(roll)}
    session.add(job)
    await session.commit()
    return True


async def set_queued_payload(session: AsyncSession, job_id: UUID, payload: dict[str, Any]) -> bool:
    """Replace the payload of a QUEUED job (a deferred job completed, #281). ``False``: the job
    is unknown or no longer QUEUED (cancelled meanwhile), nothing written."""
    stmt = (
        update(Job)
        .where(col(Job.id) == job_id, col(Job.state) == JobState.QUEUED.value)
        .values(payload=dict(payload))
        .execution_options(synchronize_session="fetch")
    )
    result = await session.execute(stmt)
    await session.commit()
    return int(result.rowcount) > 0  # type: ignore[attr-defined]


async def mark_queued_failed_restart(session: AsyncSession, job_id: UUID, error: str) -> bool:
    """One QUEUED job -> FAILED_RESTART with *error* (a deferred job a restart interrupted)."""
    stmt = (
        update(Job)
        .where(col(Job.id) == job_id, col(Job.state) == JobState.QUEUED.value)
        .values(
            state=JobState.FAILED_RESTART.value,
            error=error,
            finished_at=datetime.now(UTC),
        )
        .execution_options(synchronize_session="fetch")
    )
    result = await session.execute(stmt)
    await session.commit()
    return int(result.rowcount) > 0  # type: ignore[attr-defined]


async def mark_queued_many_failed_restart(
    session: AsyncSession, job_ids: list[UUID], error: str
) -> list[UUID]:
    """The QUEUED ones of ``job_ids`` -> FAILED_RESTART with *error*, in one statement.

    Returns the ids that changed (a job cancelled meanwhile is left alone).
    """
    if not job_ids:
        return []
    stmt = (
        update(Job)
        .where(col(Job.id).in_(job_ids), col(Job.state) == JobState.QUEUED.value)
        .values(
            state=JobState.FAILED_RESTART.value,
            error=error,
            finished_at=datetime.now(UTC),
        )
        .returning(col(Job.id))
        .execution_options(synchronize_session=False)
    )
    changed = [row[0] for row in (await session.execute(stmt)).all()]
    await session.commit()
    return changed


def _handed_off() -> Any:
    """A row the queue holds or is about to hold, so only the queue may cancel it.

    A page payload (``kind``: a Grocy sheet row after its payload swap, #281, or any page job,
    which the queue registers before its row exists), or a deferred tape row whose payload is
    complete (``rendered_tape_mm``). An ordinary untracked row (a webhook row the queue never
    saw) stays cancellable here.
    """
    # COALESCE: a payload without ``deferred`` must read as false, not NULL (``NOT NULL`` would
    # exclude every ordinary row from the guarded update).
    deferred = func.coalesce(literal_column(json_at("$.deferred")), 0) == 1
    page = literal_column(json_at("$.kind")).is_not(None)
    rendered = literal_column(json_at("$.rendered_tape_mm")).is_not(None)
    return page | (deferred & rendered)


async def cancel_queued_unhanded(
    session: AsyncSession, job_id: UUID, *, unhanded_only: bool = True
) -> Job | None:
    """QUEUED -> CANCELLED for a job the queue does not hold, in one guarded statement.

    Not written (``None``) when the row is no longer ``queued`` or, with ``unhanded_only``, is
    a row the queue holds or is about to hold (review I-1): the cancel then has to go through
    the queue, or the in-memory job would print a row that says ``cancelled``. Without it only
    the state is checked (the last resort after the wait). Either way the statement is the
    test and the write at once: of two cancels, one writes.
    """
    guards = [col(Job.id) == job_id, col(Job.state) == JobState.QUEUED.value]
    if unhanded_only:
        guards.append(~_handed_off())
    stmt = (
        update(Job)
        .where(*guards)
        .values(state=JobState.CANCELLED.value, finished_at=datetime.now(UTC))
        .execution_options(synchronize_session=False)
    )
    result = await session.execute(stmt)
    await session.commit()
    if int(result.rowcount) == 0:  # type: ignore[attr-defined]
        return None
    return await session.get(Job, job_id, populate_existing=True)


async def mark_cancelled(
    session: AsyncSession, job_id: UUID, *, states: Collection[str]
) -> Job | None:
    """Move a job from one of ``states`` to CANCELLED in one guarded statement (sets finished_at).

    The statement is the check and the write at once: a row a worker moved to ``printing``
    between a caller's read and this write is not overwritten. ``None`` when no row changed
    (unknown id, or the row is in another state).
    """
    stmt = (
        update(Job)
        .where(col(Job.id) == job_id, col(Job.state).in_(tuple(states)))
        .values(state=JobState.CANCELLED.value, finished_at=datetime.now(UTC))
        .execution_options(synchronize_session=False)
    )
    result = await session.execute(stmt)
    await session.commit()
    if int(result.rowcount) == 0:  # type: ignore[attr-defined]
        return None
    return await session.get(Job, job_id, populate_existing=True)


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


async def list_active(
    session: AsyncSession,
    *,
    printer_id: UUID | None = None,
) -> list[Job]:
    """Return all jobs in QUEUED or PRINTING state (covered by ix_jobs_state).

    Phase 2: optional printer_id filter for PrintQueue.start() recovery.
    """
    inflight = (JobState.QUEUED.value, JobState.PRINTING.value)
    stmt = select(Job).where(col(Job.state).in_(inflight))
    if printer_id is not None:
        stmt = stmt.where(col(Job.printer_id) == printer_id)
    stmt = stmt.order_by(col(Job.created_at))
    result = await session.execute(stmt)
    return list(result.scalars())


async def list_page_jobs_in_flight(
    session: AsyncSession, printer_id: UUID | None = None
) -> list[Job]:
    """PRINTING page jobs (``payload.kind`` set) of one printer (``None``: of every printer),
    oldest first."""
    stmt = select(Job).where(col(Job.state) == JobState.PRINTING.value)
    if printer_id is not None:
        stmt = stmt.where(col(Job.printer_id) == printer_id)
    stmt = stmt.order_by(col(Job.created_at))
    result = await session.execute(stmt)
    return [j for j in result.scalars() if is_page_payload(j.payload)]


async def mark_printing_as_failed_restart(
    session: AsyncSession,
    printer_id: UUID,
) -> int:
    """Phase 2: UPDATE only PRINTING *tape* jobs for a specific printer to
    FAILED_RESTART with error='printer_interrupted'.

    Used at PrintQueue.start() — QUEUED jobs are NOT affected because
    they will be re-enqueued cleanly. Only PRINTING jobs are ambiguous
    (printer may have completed before crash but Hub couldn't update DB).

    PRINTING page jobs (``payload.kind``) are left alone: the IPP printer still holds
    them, and the queue resumes their tracking or settles them one by one
    (``mark_failed_restart``).

    Returns the count of affected rows.
    """
    stmt = select(Job).where(
        col(Job.printer_id) == printer_id,
        col(Job.state) == JobState.PRINTING.value,
    )
    rows = (await session.execute(stmt)).scalars()
    tape_ids = [job.id for job in rows if not is_page_payload(job.payload)]
    if not tape_ids:
        return 0
    update_stmt = (
        update(Job)
        .where(col(Job.id).in_(tape_ids), col(Job.state) == JobState.PRINTING.value)
        .values(
            state=JobState.FAILED_RESTART.value,
            error="printer_interrupted",
            finished_at=datetime.now(UTC),
        )
        .execution_options(synchronize_session="fetch")
    )
    result = await session.execute(update_stmt)
    await session.commit()
    return int(result.rowcount)  # type: ignore[attr-defined]


async def mark_failed_restart(session: AsyncSession, job_id: UUID, error: str) -> bool:
    """One PRINTING job -> FAILED_RESTART with *error*. ``False``: not found or not PRINTING."""
    stmt = (
        update(Job)
        .where(col(Job.id) == job_id, col(Job.state) == JobState.PRINTING.value)
        .values(
            state=JobState.FAILED_RESTART.value,
            error=error,
            finished_at=datetime.now(UTC),
        )
        .execution_options(synchronize_session="fetch")
    )
    result = await session.execute(stmt)
    await session.commit()
    return int(result.rowcount) > 0  # type: ignore[attr-defined]


async def list_by_ids(
    session: AsyncSession,
    job_ids: list[UUID],
) -> list[Job]:
    """Bulk-Fetch jobs by ids — order not guaranteed, caller re-orders.

    Phase 2: used by GET /api/v1/batches/{id} to load all jobs referenced
    by a PrintBatch.job_ids list in a single SQL query.
    """
    if not job_ids:
        return []
    result = await session.execute(select(Job).where(col(Job.id).in_(job_ids)))
    return list(result.scalars())


async def evict_terminal_older_than(
    session: AsyncSession,
    age: timedelta,
) -> int:
    """Phase 2 cleanup: DELETE terminal jobs older than age.

    Terminal = DONE | FAILED | FAILED_RESTART | CANCELLED.
    Comparison is on finished_at (set whenever a job leaves a non-terminal state).

    Jobs with finished_at IS NULL are NOT deleted (NULL < cutoff is SQL UNKNOWN,
    which is falsy in WHERE). This is intentional — protects pre-Phase-2 rows
    that may not have finished_at set.

    Returns the count of deleted rows.
    """
    terminal = (
        JobState.DONE.value,
        JobState.FAILED.value,
        JobState.FAILED_RESTART.value,
        JobState.CANCELLED.value,
    )
    cutoff = datetime.now(UTC) - age
    stmt = (
        delete(Job)
        .where(col(Job.state).in_(terminal))
        .where(col(Job.finished_at) < cutoff)
        # A job whose sheet cells are still reserved is not yet settled: without its row the
        # startup sweep could not tell a printed page from one that was never saved (T5-1).
        # Nor one whose cells are still unconfirmed on an active sheet: the margin ID and feed
        # mark it carried count as maybe printed, and resolving the cells as printed reads its
        # row (F3-1). A discarded sheet is never resolved, so its unconfirmed cells pin nothing
        # (#215); ``reserved`` pins whatever the sheet's state.
        .where(
            ~exists()
            .where(col(SheetCell.job_id) == col(Job.id))
            .where(col(Sheet.id) == col(SheetCell.sheet_id))
            .where(
                or_(
                    col(SheetCell.state) == "reserved",
                    and_(col(SheetCell.state) == "unconfirmed", col(Sheet.state) == "active"),
                )
            )
        )
        .execution_options(synchronize_session="fetch")
    )
    result = await session.execute(stmt)
    await session.commit()
    return int(result.rowcount)  # type: ignore[attr-defined]


class LastPageTrays(NamedTuple):
    """The trays the newest sheet and calibration page jobs of one printer used."""

    sheet_tray: str | None
    calibration_tray: str | None
    calibration_at: datetime | None


# Jobs that count as "the tray just used": a failed or cancelled job may never have reached
# the tray.
_TRAY_STATES = (JobState.QUEUED.value, JobState.PRINTING.value, JobState.DONE.value)


async def last_page_trays(session: AsyncSession, printer_id: UUID) -> LastPageTrays:
    """The tray of the newest sheet page job and the tray and time of the newest calibration page.

    One statement, scalar subqueries that each seek ``ix_jobs_printer_kind_created`` (printer,
    kind, created_at) and read the newest row without a sort. The kind is compared through
    ``PAGE_KIND_EXPR`` (the index text, or SQLite scans). No ``id`` tiebreak: two jobs of one
    printer and kind with the same ``created_at`` are a harmless tie, either tray is one just
    used, and a tiebreak outside the index would add a partial sort. The jobs of every API key
    count: the tray describes the printer's recent use, not the caller's.
    """

    def newest(kind: str, value: Any) -> Any:
        return (
            select(value)
            .where(
                col(Job.printer_id) == printer_id,
                literal_column(PAGE_KIND_EXPR) == kind,
                col(Job.state).in_(_TRAY_STATES),
            )
            .order_by(col(Job.created_at).desc())
            .limit(1)
            .scalar_subquery()
        )

    tray = json_at("$.tray")
    # Tray and time of the calibration page come out of ONE subquery, so equal ``created_at``
    # values cannot name two different jobs.
    calibration = newest(
        "calibration_page", literal_column(f"json_object('tray', {tray}, 'at', created_at)")
    )
    row = (
        await session.execute(select(newest("sheet_page", literal_column(tray)), calibration))
    ).one()
    cal: dict[str, Any] = json.loads(row[1]) if isinstance(row[1], str) else {}
    at = cal.get("at")
    return LastPageTrays(
        sheet_tray=row[0] if isinstance(row[0], str) else None,
        calibration_tray=cal["tray"] if isinstance(cal.get("tray"), str) else None,
        calibration_at=datetime.fromisoformat(at) if isinstance(at, str) else None,
    )
