"""REST endpoints for the Jobs aggregate (Phase 6a Task 3).

Routes
------
GET  /api/jobs                   — list jobs with optional filters + pagination
GET  /api/jobs/{id}              — single job by ID
POST /api/jobs/{id}/cancel       — cancel a QUEUED job (409 for any other state)
POST /api/jobs/{id}/pause        — 501 placeholder (safe mid-print pause not yet implemented)
POST /api/jobs/{id}/resume       — 501 placeholder
POST /api/jobs/{id}/retry        — clone a FAILED job into a fresh QUEUED job

Design notes
------------
- cancel is restricted to QUEUED state.  Mid-print abort over TCP/9100 is
  unsafe because the raster data stream is already on the wire; the Brother
  PT-series firmware does not support a cancel command once printing starts.
  The 409 response body is a ProblemDetail (RFC 7807) with type
  ``invalid-job-state`` and an explicit detail explaining why PRINTING jobs
  cannot be cancelled.
- pause / resume return 501 ProblemDetail — they exist in the OpenAPI schema
  so the Phase 7 UI can wire to stable URLs; the implementation follows in a
  later phase when the queue worker gains mid-job control.
- retry clones the failed job's ``printer_id``, ``template_key``, and
  ``payload`` into a new QUEUED job.  The original job remains in FAILED state
  (it is an immutable history entry).

References:
    docs/superpowers/specs/2026-05-16-phase6a-rest-api-design.md — Jobs section
    docs/superpowers/plans/2026-05-16-phase6a-rest-api.md — Task 3
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_print, require_read
from app.db.session import get_session
from app.models.job import Job, JobState
from app.repositories import jobs as jobs_repo
from app.schemas.job import JobRead
from app.schemas.problem import ProblemDetail

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

# Type alias for the session dependency
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ReadAuthDep = Annotated[AuthContext, Depends(require_read)]
PrintAuthDep = Annotated[AuthContext, Depends(require_print)]

# Query parameter type aliases (Annotated avoids B008 on Query() in arg defaults)
StateQuery = Annotated[
    str | None,
    Query(description="Filter by job state (queued / printing / done / failed / …)"),
]
PrinterIdQuery = Annotated[
    UUID | None,
    Query(description="Filter by printer UUID"),
]
SinceQuery = Annotated[
    datetime | None,
    Query(description="Return only jobs created at or after this ISO-8601 datetime"),
]
LimitQuery = Annotated[
    int,
    Query(ge=1, le=200, description="Maximum number of jobs to return (1-200, default 50)"),
]


# ---------------------------------------------------------------------------
# Helper: 404 on unknown job
# ---------------------------------------------------------------------------


async def _get_job_or_404(session: AsyncSession, job_id: UUID) -> Job:
    """Return the Job row or raise HTTP 404."""
    job = await jobs_repo.get(session, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"job {job_id} not found",
        )
    return job


# ---------------------------------------------------------------------------
# GET /api/jobs
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=list[JobRead],
    summary="List jobs",
    description=(
        "Returns jobs matching the optional filters, ordered by creation time.  "
        "``state`` accepts any valid JobState value (``queued``, ``printing``, "
        "``done``, ``failed``, ``cancelled``, ``failed_restart``).  "
        "``since`` is an ISO-8601 datetime; only jobs created at or after that "
        "instant are returned.  ``limit`` caps the result (default 50, max 200)."
    ),
)
async def list_jobs(
    session: SessionDep,
    _auth: ReadAuthDep,
    state: StateQuery = None,
    printer_id: PrinterIdQuery = None,
    since: SinceQuery = None,
    limit: LimitQuery = 50,
) -> list[JobRead]:
    """Return jobs matching the given filters."""
    rows = await jobs_repo.list_by_filter(
        session,
        state=state,
        printer_id=printer_id,
        since=since,
        limit=limit,
    )
    return [JobRead.model_validate(r, from_attributes=True) for r in rows]


# ---------------------------------------------------------------------------
# GET /api/jobs/{id}
# ---------------------------------------------------------------------------


@router.get(
    "/{job_id}",
    response_model=JobRead,
    summary="Get a single job",
    description="Return the full job record for the given UUID.  Returns 404 if not found.",
)
async def get_job(
    job_id: UUID,
    session: SessionDep,
    _auth: ReadAuthDep,
) -> JobRead:
    """Return a single job by ID."""
    job = await _get_job_or_404(session, job_id)
    return JobRead.model_validate(job, from_attributes=True)


# ---------------------------------------------------------------------------
# POST /api/jobs/{id}/cancel
# ---------------------------------------------------------------------------


@router.post(
    "/{job_id}/cancel",
    response_model=JobRead,
    summary="Cancel a queued job",
    description=(
        "Cancels a job that is in ``queued`` state.  "
        "Returns 409 ProblemDetail when the job is in ``printing`` (or any other "
        "non-QUEUED) state — mid-print abort is unsafe over TCP/9100 because the "
        "raster data is already on the wire."
    ),
)
async def cancel_job(
    job_id: UUID,
    session: SessionDep,
    _auth: PrintAuthDep,
) -> JobRead:
    """Cancel a QUEUED job; reject with 409 for any other state."""
    job = await _get_job_or_404(session, job_id)
    job_state: str = job.state
    if job_state != JobState.QUEUED.value:
        problem = ProblemDetail(
            type="invalid-job-state",
            title="Cannot cancel job in current state",
            status=409,
            detail=(
                f"Job is in state '{job_state}' — only QUEUED jobs can be cancelled "
                "(mid-print abort is unsafe over TCP/9100)"
            ),
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=problem.model_dump(exclude_none=True),
        )
    cancelled = await jobs_repo.mark_cancelled(session, job_id)
    return JobRead.model_validate(cancelled, from_attributes=True)


# ---------------------------------------------------------------------------
# POST /api/jobs/{id}/pause
# ---------------------------------------------------------------------------


@router.post(
    "/{job_id}/pause",
    response_model=ProblemDetail,
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    summary="Pause a job (not yet implemented)",
    description=(
        "Placeholder — returns 501 ProblemDetail.  "
        "Mid-job pause will be implemented when the queue worker gains "
        "control-plane support for pausing an in-progress raster stream.  "
        "This endpoint exists so the Phase 7 UI can wire to a stable URL."
    ),
)
async def pause_job(
    job_id: UUID,
    session: SessionDep,
) -> ProblemDetail:
    """Return 501 — pause is not yet implemented."""
    # Verify the job exists so we return 404 rather than 501 for unknown jobs
    await _get_job_or_404(session, job_id)
    return ProblemDetail(
        type="not-implemented",
        title="Pause not implemented",
        status=501,
        detail=(
            "Mid-job pause over TCP/9100 is not yet supported.  "
            "This endpoint is a placeholder for Phase 7 UI integration."
        ),
    )


# ---------------------------------------------------------------------------
# POST /api/jobs/{id}/resume
# ---------------------------------------------------------------------------


@router.post(
    "/{job_id}/resume",
    response_model=ProblemDetail,
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    summary="Resume a paused job (not yet implemented)",
    description=(
        "Placeholder — returns 501 ProblemDetail.  "
        "Resume will be implemented alongside pause in a later phase.  "
        "This endpoint exists so the Phase 7 UI can wire to a stable URL."
    ),
)
async def resume_job(
    job_id: UUID,
    session: SessionDep,
) -> ProblemDetail:
    """Return 501 — resume is not yet implemented."""
    # Verify the job exists so we return 404 rather than 501 for unknown jobs
    await _get_job_or_404(session, job_id)
    return ProblemDetail(
        type="not-implemented",
        title="Resume not implemented",
        status=501,
        detail=(
            "Resume is a placeholder — it will be implemented alongside "
            "pause support in a later phase."
        ),
    )


# ---------------------------------------------------------------------------
# POST /api/jobs/{id}/retry
# ---------------------------------------------------------------------------


@router.post(
    "/{job_id}/retry",
    response_model=JobRead,
    status_code=status.HTTP_201_CREATED,
    summary="Retry a failed job",
    description=(
        "Clones a ``failed`` (or ``failed_restart`` / ``cancelled``) job into a "
        "new ``queued`` job with a fresh UUID.  The original job is untouched and "
        "remains as an immutable history entry.  Returns 409 when the original job "
        "is still in an active state (``queued`` or ``printing``)."
    ),
)
async def retry_job(
    job_id: UUID,
    session: SessionDep,
) -> JobRead:
    """Clone a terminal job into a fresh QUEUED job."""
    job = await _get_job_or_404(session, job_id)
    job_state: str = job.state
    # Only allow retry for terminal states — refuse if the job is still active
    active_states = {JobState.QUEUED.value, JobState.PRINTING.value}
    if job_state in active_states:
        problem = ProblemDetail(
            type="invalid-job-state",
            title="Cannot retry an active job",
            status=409,
            detail=(
                f"Job is in state '{job_state}' — retry is only allowed for "
                "terminal jobs (failed / failed_restart / cancelled / done)"
            ),
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=problem.model_dump(exclude_none=True),
        )
    new_job = await jobs_repo.create_queued(
        session,
        printer_id=job.printer_id,
        template_key=job.template_key,
        payload=dict(job.payload),
    )
    return JobRead.model_validate(new_job, from_attributes=True)
