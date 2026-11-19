# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""REST endpoints for the Jobs aggregate (Phase 6a Task 3).

Routes
------
GET  /api/v1/jobs                   — list jobs with optional filters + pagination
GET  /api/v1/jobs/{id}              — single job by ID
POST /api/v1/jobs/{id}/cancel       — cancel a QUEUED job (409 for any other state)
POST /api/v1/jobs/{id}/pause        — 501 placeholder (safe mid-print pause not yet implemented)
POST /api/v1/jobs/{id}/resume       — 501 placeholder
POST /api/v1/jobs/{id}/retry        — clone a FAILED job into a fresh QUEUED job

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
  ``payload`` into a new QUEUED job and hands it to the live ``PrintQueue``, so it
  prints without a restart.  The original job remains in FAILED state (it is an
  immutable history entry).
- cancel and retry act on the ``PrintQueue`` stored in ``app.state`` (not only on
  the DB): the worker gates on the in-memory job state, so a DB-only cancel would
  still be printed.  Rows the queue does not track (e.g. webhook-created jobs)
  fall back to the DB-only path.

References:
    docs/superpowers/specs/2026-05-16-phase6a-rest-api-design.md — Jobs section
    docs/superpowers/plans/2026-05-16-phase6a-rest-api.md — Task 3
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.identity_hold import ensure_not_held
from app.api.routes.sheet_common import actor
from app.auth.dependencies import AuthContext
from app.auth.ownership import may_see, owner_only
from app.auth.scope_deps import require_print, require_read
from app.db import engine as db_engine
from app.db.session import get_session
from app.models.job import Job, JobState, is_page_payload
from app.repositories import jobs as jobs_repo
from app.repositories import printers as printers_repo
from app.repositories import sheet_types as types_repo
from app.schemas.content_type import ContentType
from app.schemas.grocy_label import grocycode_ref, is_grocycode
from app.schemas.job import JobRead
from app.schemas.print_request import RawLabelData
from app.schemas.problem import ProblemDetail
from app.services.page_jobs import IDENTITY_HELD_KINDS, PagePayload
from app.services.print_queue import UnrenderableJobError
from app.services.producers.print_queue_producer import publish_job_state_changed
from app.sheets import print_service
from app.sheets.errors import (
    IdPlacementMismatchError,
    MediaKindMismatchError,
    PageJobNotRetryableError,
    SheetApiError,
    SheetDiscardedError,
    SheetPrinterDisabledError,
    SheetTypeArchivedError,
)
from app.sheets.grocy_sheet import is_deferred_sheet

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])

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
OrderQuery = Annotated[
    Literal["oldest", "newest"],
    Query(
        description=(
            "Sort by creation time: ``oldest`` first (default) or ``newest`` first. With "
            "``newest`` and a ``limit`` the latest jobs come back, not the first ones."
        )
    ),
]
LimitQuery = Annotated[
    int,
    Query(ge=1, le=200, description="Maximum number of jobs to return (1-200, default 50)"),
]


# ---------------------------------------------------------------------------
# Helper: 404 on unknown job
# ---------------------------------------------------------------------------


async def _get_job_or_404(
    session: AsyncSession, job_id: UUID, auth: AuthContext | None = None
) -> Job:
    """Return the Job row or raise HTTP 404.

    A job on a printer outside the caller's ``allowed_printer_ids`` answers the
    same 404 as an unknown job, so its existence is not disclosed.  An empty
    allowed list means all printers.  For a plain API key the same holds for a job
    another key submitted, or one without an owner key (#294).
    """
    job = await jobs_repo.get(session, job_id)
    if (
        job is not None
        and auth is not None
        and auth.allowed_printer_ids
        and str(job.printer_id) not in auth.allowed_printer_ids
    ):
        job = None
    if job is not None and not may_see(auth, job.api_key_id):
        job = None
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"job {job_id} not found",
        )
    return job


# ---------------------------------------------------------------------------
# GET /api/v1/jobs
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
        "instant are returned.  ``limit`` caps the result (default 50, max 200).  "
        "``order`` is ``oldest`` (default) or ``newest``, which returns the latest jobs first.  "
        "An API key without ``admin`` scope, and a browser session signed in with one, sees "
        "only the jobs that key submitted; SSO users and admin keys see every job of their "
        "printers."
    ),
)
async def list_jobs(
    session: SessionDep,
    _auth: ReadAuthDep,
    state: StateQuery = None,
    printer_id: PrinterIdQuery = None,
    since: SinceQuery = None,
    limit: LimitQuery = 50,
    order: OrderQuery = "oldest",
) -> list[JobRead]:
    """Return jobs matching the given filters."""
    # Per-printer ACL: restrict to the caller's printers (empty list = all).
    allowed = [UUID(p) for p in _auth.allowed_printer_ids] if _auth is not None else []
    if printer_id is not None and allowed and printer_id not in allowed:
        return []
    # #294: a plain API key lists the jobs it submitted, nothing else.
    owner: UUID | None = None
    if owner_only(_auth):
        if _auth.api_key_id is None:
            return []
        owner = _auth.api_key_id
    rows = await jobs_repo.list_by_filter(
        session,
        state=state,
        printer_id=printer_id,
        since=since,
        limit=limit,
        allowed_printer_ids=allowed,
        api_key_id=owner,
        order=order,
    )
    return [JobRead.model_validate(r, from_attributes=True) for r in rows]


# ---------------------------------------------------------------------------
# GET /api/v1/jobs/{id}
# ---------------------------------------------------------------------------


@router.get(
    "/{job_id}",
    response_model=JobRead,
    summary="Get a single job",
    description=(
        "Return the full job record for the given UUID.  Returns 404 if not found; for an "
        "API key without ``admin`` scope also for a job another key (or a browser, SSO user "
        "or webhook) submitted.  Cancel, retry, pause and resume answer the same 404."
    ),
)
async def get_job(
    job_id: UUID,
    session: SessionDep,
    _auth: ReadAuthDep,
) -> JobRead:
    """Return a single job by ID."""
    job = await _get_job_or_404(session, job_id, _auth)
    return JobRead.model_validate(job, from_attributes=True)


# ---------------------------------------------------------------------------
# POST /api/v1/jobs/{id}/cancel
# ---------------------------------------------------------------------------


@router.post(
    "/{job_id}/cancel",
    response_model=JobRead,
    summary="Cancel a queued job",
    description=(
        "Cancels a job that is in ``queued`` state.  "
        "Returns 409 ProblemDetail when the job is in ``printing`` (or any other "
        "non-QUEUED) state — mid-print abort is unsafe over TCP/9100 because the "
        "raster data is already on the wire.  "
        "Exception: a page job (IPP printer) that the printer already holds is cancelled "
        "at the printer: the hub sends Cancel-Job and answers ``202`` with the job still "
        "``printing``; the job ends ``cancelled`` (or ``failed``/``interrupted`` when the "
        "page had started) once the printer confirms."
    ),
    responses={
        202: {"model": JobRead, "description": "Cancel requested at the printer (page job)"},
    },
)
async def cancel_job(
    request: Request,
    job_id: UUID,
    session: SessionDep,
    _auth: PrintAuthDep,
) -> JobRead | JSONResponse:
    """Cancel a QUEUED job (or ask the printer to cancel a page job); 409 otherwise."""
    job = await _get_job_or_404(session, job_id, _auth)
    job_state: str = job.state
    queue = getattr(request.app.state, "print_queue", None)
    tracked = queue is not None and queue.has_job(job_id)
    at_printer = (
        queue is not None
        and tracked
        and queue.is_page_job(job_id)
        and job_state == JobState.PRINTING.value
    )
    if job_state != JobState.QUEUED.value and not at_printer:
        raise _cancel_conflict(job_state)
    if tracked and queue is not None:
        return await _cancel_tracked(session, job, queue, job_id)
    # The queue does not hold the job (a deferred Grocy job before its hand-off, #281). The
    # write is guarded: if the task handed the job to the queue since ``has_job`` above, the
    # row is not touched and the cancel goes through the queue (review I-1). The hand-off
    # registers the job just before or just after its payload write, so a short, read-only wait
    # covers it (review N-2); at its end one more guarded write cancels a row nothing took.
    cancelled = await jobs_repo.cancel_queued_unhanded(session, job_id)
    deadline = asyncio.get_running_loop().time() + _HAND_OFF_WAIT_S
    while cancelled is None:
        if queue is not None and queue.has_job(job_id):
            await session.refresh(job)
            return await _cancel_tracked(session, job, queue, job_id)
        await session.refresh(job)
        if job.state != JobState.QUEUED.value:
            raise _cancel_conflict(job.state)
        if asyncio.get_running_loop().time() > deadline:
            # A completed payload the queue still does not hold (a hand-off held up, or one
            # that failed): cancel the row if it is still queued; a later pick-up refuses a
            # row that is not. Only the write that wins answers 200 and announces it (N-1).
            cancelled = await jobs_repo.cancel_queued_unhanded(session, job_id, unhanded_only=False)
            if cancelled is None:
                await session.refresh(job)
                raise _cancel_conflict(job.state)
            break
        await asyncio.sleep(0.01)
    # No worker transition announces it, so a watcher would keep it ``queued`` (review N4).
    publish_job_state_changed(
        getattr(request.app.state, "event_bus", None),
        printer_id=cancelled.printer_id,
        job_id=cancelled.id,
        from_state=JobState.QUEUED.value,
        to_state=JobState.CANCELLED.value,
    )
    return JobRead.model_validate(cancelled, from_attributes=True)


_HAND_OFF_WAIT_S = 1.0


async def _cancel_tracked(
    session: AsyncSession, job: Job, queue: Any, job_id: UUID
) -> JobRead | JSONResponse:
    # The queue transitions the in-memory job (the state the worker gates on)
    # and persists the cancellation.  False = the worker took the job first
    # (tape) or the page job already ended.
    if not await queue.cancel(str(job_id)):
        live = await queue.get(job_id)
        raise _cancel_conflict(live.state.value)
    await session.refresh(job)
    read = JobRead.model_validate(job, from_attributes=True)
    # Requested at the printer, not yet final. The row may still say ``queued``: the worker
    # moved the page job to PRINTING in memory and has not written it yet (265-07).
    requested = job.state == JobState.PRINTING.value or (
        queue.is_page_job(job_id)
        and (await queue.get(job_id)).state.value == JobState.PRINTING.value
    )
    if requested:
        read = read.model_copy(update={"state": JobState.PRINTING.value})
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=jsonable_encoder(read))
    return read


def _cancel_conflict(job_state: str) -> HTTPException:
    problem = ProblemDetail(
        type="invalid-job-state",
        title="Cannot cancel job in current state",
        status=409,
        detail=(
            f"Job is in state '{job_state}' — only QUEUED jobs can be cancelled "
            "(mid-print abort is unsafe over TCP/9100)"
        ),
    )
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=problem.model_dump(exclude_none=True),
    )


# ---------------------------------------------------------------------------
# POST /api/v1/jobs/{id}/pause
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
    _auth: PrintAuthDep,
) -> ProblemDetail:
    """Return 501 — pause is not yet implemented."""
    # Verify the job exists so we return 404 rather than 501 for unknown jobs
    await _get_job_or_404(session, job_id, _auth)
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
# POST /api/v1/jobs/{id}/resume
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
    _auth: PrintAuthDep,
) -> ProblemDetail:
    """Return 501 — resume is not yet implemented."""
    # Verify the job exists so we return 404 rather than 501 for unknown jobs
    await _get_job_or_404(session, job_id, _auth)
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
# POST /api/v1/jobs/{id}/retry
# ---------------------------------------------------------------------------


@router.post(
    "/{job_id}/retry",
    response_model=JobRead,
    status_code=status.HTTP_201_CREATED,
    summary="Retry a failed job",
    description=(
        "Clones a ``failed`` (or ``failed_restart`` / ``cancelled``) job into a "
        "new ``queued`` job with a fresh UUID.  The original job is untouched and "
        "remains as an immutable history entry.  The new job is handed to the print "
        "queue immediately — no restart needed.  Returns 409 when the original job "
        "is still in an active state (``queued`` or ``printing``) or its printer is "
        "not available, and 422 when the stored payload cannot be re-rendered "
        "(e.g. webhook-created jobs).  A Grocy label job that failed before its render "
        "(printer offline, no tape) is accepted again on its printer and completes in the "
        "background, like the webhook; a Grocy label that could not be built answers 422 "
        "and creates no row.  A Grocy label for a sheet that ended before it reached the "
        "printer is accepted again the same way: a new job takes a free cell of the sheet type, "
        "chosen like a new label; it answers 409 ``printer_disabled``, ``media_kind_mismatch`` "
        "or ``sheet_type_archived``, 409 ``printer-identity-mismatch`` for a held printer, and "
        "409 ``job_not_retryable`` when the sheet type was deleted, without creating a row.  "
        "Page jobs: a calibration page is re-submitted from "
        "its payload, so retry prints the same page again with its original calibration "
        "snapshot and date; a fresh check print with the current calibration is a new "
        "calibration-page request.  A sheet page is retried onto the same cells of the same "
        "sheet as a new job, with a fresh calibration snapshot and the margin ID and feed "
        "mark decided again for the printer.  It answers 409 ``job_not_retryable`` for a "
        "``done`` job (or an ID-only job whose ID was printed since), 409 "
        "``cells_unconfirmed`` while a cell of the job waits for confirmation, 409 "
        "``cells_taken`` (with the cell numbers) when a cell is no longer free, 409 "
        "``printer_disabled`` for a disabled printer (a calibration page too), 422 "
        "``tray_unknown`` when the tray was removed or disabled since, and 409 "
        "``sheet_discarded`` for a discarded sheet; nothing is reserved or created in any of "
        "these cases.  A page with the sheet code on the back is re-sent from its payload "
        "(same strip, date and turn) while its sheet is active and still has its code on the "
        "back, else 409 ``sheet_discarded`` or ``id_placement_mismatch``; the job never marks "
        "the code as printed.  A tray loading test page is re-sent like a test page.  The new "
        "job's payload carries ``retry_of``, the id of the job it "
        "repeats; that job may have been cleaned up since, so the id may no longer resolve."
    ),
)
async def retry_job(
    request: Request,
    job_id: UUID,
    session: SessionDep,
    _auth: PrintAuthDep,
) -> JobRead:
    """Clone a terminal job into a fresh QUEUED job."""
    job = await _get_job_or_404(session, job_id, _auth)
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
    queue = getattr(request.app.state, "print_queue", None)
    if is_page_payload(job.payload):
        return await _retry_page_job(request, session, queue, job, _auth)
    if is_deferred_sheet(job.payload):
        return await _retry_deferred_sheet(request, session, queue, job, _auth)
    if _is_unfinished_deferred(job.payload):
        return await _retry_deferred_job(request, session, job, _auth)
    new_job = await jobs_repo.create_queued(
        session,
        printer_id=job.printer_id,
        template_key=job.template_key,
        # #389: the retry records the roll it is sent to, never the original's.
        payload={
            **{k: v for k, v in job.payload.items() if k != "loaded_roll"},
            "retry_of": str(job.id),
        },
        # #294: the clone belongs to the caller that asked for it, like a page retry.
        api_key_id=_auth.api_key_id if _auth is not None else None,
        source_ip=_auth.ip if _auth is not None else None,
    )
    if queue is not None:
        try:
            await queue.enqueue_persisted(new_job)
        except UnrenderableJobError as exc:
            await _fail_unqueued(session, new_job.id, "retry_unrenderable_payload")
            raise _retry_rejected(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "job-not-retryable",
                "Job payload cannot be re-rendered",
                str(exc),
            ) from exc
        except MediaKindMismatchError as exc:
            # A tape row whose printer is now a page printer (D18).
            await _fail_unqueued(session, new_job.id, "retry_media_kind_mismatch")
            raise exc.to_http() from exc
        except KeyError as exc:
            await _fail_unqueued(session, new_job.id, "retry_printer_unavailable")
            raise _retry_rejected(
                status.HTTP_409_CONFLICT,
                "printer-unavailable",
                "Printer is not available to the print queue",
                f"Printer {job.printer_id} is not known to the print queue",
            ) from exc
    return JobRead.model_validate(new_job, from_attributes=True)


def _is_unfinished_deferred(payload: dict[str, Any]) -> bool:
    """A Grocy label job (#281) that ended before its render, or a label that was never built."""
    if payload.get("content_error"):
        return True
    return payload.get("deferred") is True and "rendered_tape_mm" not in payload


async def _retry_deferred_job(
    request: Request, session: AsyncSession, job: Job, auth: AuthContext | None
) -> JobRead:
    """Accept the label of a deferred job again, on its printer (#281, R-281-11).

    A deferred job that failed before its render (printer offline, no tape) has no rendered
    tape fields to re-render from: it goes through ``accept_deferred_job`` again, which
    answers at once and completes in the background. A label that could not be built (a
    content error) has nothing to print and answers 422. No extra row is created on refusal.
    """
    payload = job.payload
    label_data = payload.get("label_data")
    raw: RawLabelData | None = None
    content_type: ContentType | None = None
    if not payload.get("content_error") and isinstance(label_data, dict):
        try:
            raw = RawLabelData.model_validate(
                {k: v for k, v in label_data.items() if k in RawLabelData.model_fields}
            )
            content_type = ContentType(str(payload.get("content_type")))
        except (ValidationError, ValueError):
            raw = None
    if raw is None or content_type is None or not isinstance(label_data, dict):
        raise _retry_rejected(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "job-not-retryable",
            "Job payload cannot be re-rendered",
            "The label of this job could not be built; send it again from its source",
        )
    runtime = getattr(request.app.state, "printer_runtime", None)
    service = runtime.print_service_for(job.printer_id) if runtime is not None else None
    if service is None:
        raise _retry_rejected(
            status.HTTP_409_CONFLICT,
            "printer-unavailable",
            "Printer is not available to the print queue",
            f"Printer {job.printer_id} is not known to the print queue",
        )
    new_id = await service.accept_deferred_job(
        raw,
        content_type=content_type,
        source_app=str(label_data.get("source_app") or "manual"),
        # #294: the new job belongs to the caller that asked for it.
        api_key_id=auth.api_key_id if auth is not None else None,
        source_ip=auth.ip if auth is not None else None,
        retry_of=job.id,
    )
    new_job = await jobs_repo.get(session, new_id)
    if new_job is None:  # evicted or failed before the read: report the accepted id anyway
        raise _retry_rejected(
            status.HTTP_409_CONFLICT,
            "printer-unavailable",
            "Printer is not available to the print queue",
            f"Job {new_id} could not be read back",
        )
    return JobRead.model_validate(new_job, from_attributes=True)


_SHEET_LABEL_GONE = (
    "The sheet type of this label no longer exists; send the label again from Grocy."
)


async def _retry_deferred_sheet(
    request: Request, session: AsyncSession, queue: Any, job: Job, auth: AuthContext | None
) -> JobRead:
    """Accept a Grocy sheet label again that ended before its hand-off (#281, R-281-16).

    The label goes through ``GrocySheetLabels.accept`` like a new one from the webhook: a new
    ``queued`` row, then the sheet choice and the reservation under the per-type lock and the
    sheet write lock, so a retry never takes a cell another label takes at the same time. The
    printer and the sheet type are checked again first; a refusal creates no row.
    """
    payload = job.payload
    printer = await printers_repo.get(session, job.printer_id)
    if printer is None:
        raise _printer_unavailable(job.printer_id)
    if not printer.enabled:
        raise SheetPrinterDisabledError().to_http()
    if printer.backend != "ipp":
        raise MediaKindMismatchError().to_http()  # re-wired to a tape printer since
    ensure_not_held(queue, job.printer_id)  # #231
    sheet_type = str(payload.get("sheet_type") or "")
    known = await types_repo.get_by_key(session, sheet_type) if sheet_type else None
    if known is None:
        raise PageJobNotRetryableError(_SHEET_LABEL_GONE).to_http()
    if known.archived_at is not None:
        raise SheetTypeArchivedError().to_http()
    label_data = payload.get("label_data")
    try:
        if not isinstance(label_data, dict):
            raise ValueError("no label data")
        raw = RawLabelData.model_validate(
            {k: v for k, v in label_data.items() if k in RawLabelData.model_fields}
        )
        content_type = ContentType(str(payload.get("content_type")))
        if not is_grocycode(raw.qr_payload):
            raise ValueError("no Grocycode")
    except (ValidationError, ValueError):
        raise _retry_rejected(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "job-not-retryable",
            "Job payload cannot be re-rendered",
            "The label of this job could not be built; send it again from its source",
        ) from None
    await session.commit()  # no read transaction stays open behind the job insert
    new_id = await request.app.state.grocy_sheet_labels.accept(
        printer,
        sheet_type=sheet_type,
        raw=raw,
        content_type=content_type,
        ref=grocycode_ref(str(raw.qr_payload)),
        # #294: the new job belongs to the caller that asked for it.
        api_key_id=auth.api_key_id if auth is not None else None,
        source_ip=auth.ip if auth is not None else None,
        retry_of=job.id,
    )
    new_job = await jobs_repo.get(session, new_id)
    if new_job is None:  # pragma: no cover - the row is inserted before ``accept`` returns
        raise _printer_unavailable(job.printer_id)
    return JobRead.model_validate(new_job, from_attributes=True)


async def _retry_page_job(
    request: Request, session: AsyncSession, queue: Any, job: Job, auth: AuthContext | None
) -> JobRead:
    """Re-submit a page job through the queue (it renders at send time).

    A calibration page and a test page are re-sent from their payload. Retry means "the same
    page again": the stored payload carries the calibration snapshot and the date of the first
    submit, and both are kept on purpose. After the admin has corrected the values, a new check
    print is a new calibration-page request.

    A sheet page goes to ``print_service.retry_sheet_page``: the same cells, a new job, a fresh
    snapshot. A ``done`` sheet page is not retried (its labels came out).
    """
    kind = job.payload.get("kind")
    if kind == "sheet_page" and job.state == JobState.DONE.value:
        raise PageJobNotRetryableError().to_http()
    printer = await printers_repo.get(session, job.printer_id)
    if printer is not None and not printer.enabled:
        raise SheetPrinterDisabledError().to_http()  # pre-flight C18; #167 is the general fix
    if kind in IDENTITY_HELD_KINDS:
        ensure_not_held(queue, job.printer_id)  # #231 (a test page is never held)
    if kind == "sheet_page":
        return await _retry_sheet_page(request, session, queue, job, auth)
    if kind not in ("calibration_page", "test_page", "sheet_back_page", "tray_loading_page"):
        raise PageJobNotRetryableError().to_http()
    if kind == "sheet_back_page":
        await _ensure_back_side_sheet(session, job.payload)  # R-350-6
    try:
        payload = PagePayload.model_validate(job.payload).model_copy(update={"retry_of": job.id})
    except ValueError as exc:
        raise _stored_page_invalid() from exc
    if queue is None:
        raise _printer_unavailable(job.printer_id)
    try:
        new_id = await queue.submit_page_job(
            job.printer_id,
            payload,
            api_key_id=auth.api_key_id if auth is not None else None,
            source_ip=auth.ip if auth is not None else None,
        )
    except MediaKindMismatchError as exc:
        raise exc.to_http() from exc
    except KeyError as exc:
        raise _printer_unavailable(job.printer_id) from exc
    return await _read_new_job(session, new_id, job.printer_id)


async def _retry_sheet_page(
    request: Request, session: AsyncSession, queue: Any, job: Job, auth: AuthContext | None
) -> JobRead:
    if queue is None:
        raise _printer_unavailable(job.printer_id)
    # End this request's read transaction first: the service opens its own sessions (the
    # R10-1 class). The loaded job stays usable (expire_on_commit=False); the session starts
    # again when the new job is read.
    await session.commit()
    try:
        new_id = await print_service.retry_sheet_page(
            db_engine.async_session,
            queue,
            job,
            actor=actor(auth) if auth is not None else "hub",
            settings_store=request.app.state.settings_store,
            api_key_id=auth.api_key_id if auth is not None else None,
            source_ip=auth.ip if auth is not None else None,
            bus=getattr(request.app.state, "event_bus", None),
        )
    except SheetApiError as exc:
        if exc.error_code == "printer-unavailable":
            raise _printer_unavailable(job.printer_id) from exc
        raise exc.to_http() from None
    except ValueError as exc:  # the stored payload does not describe a sheet page
        raise _stored_page_invalid() from exc
    return await _read_new_job(session, new_id, job.printer_id)


async def _ensure_back_side_sheet(session: AsyncSession, payload: dict[str, Any]) -> None:
    """A back-side page prints again only onto a sheet that is still active and has a code on
    the back (R-350-6): a ``back_side`` sheet, or one that asked for an extra code on the back
    (``back_side_state`` set) and keeps its own placement. A discarded code never prints again."""
    from app.models.sheet import Sheet

    detail = payload.get("detail")
    raw_id = detail.get("sheet_id") if isinstance(detail, dict) else None
    try:
        sheet_id = UUID(str(raw_id))
    except ValueError:
        raise _stored_page_invalid() from None
    sheet = await session.get(Sheet, sheet_id)
    if sheet is None or sheet.state == "discarded":
        raise SheetDiscardedError().to_http()
    if sheet.id_placement != "back_side" and sheet.back_side_state is None:
        raise IdPlacementMismatchError().to_http()


def _stored_page_invalid() -> HTTPException:
    return _retry_rejected(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "job-not-retryable",
        "Job payload cannot be re-rendered",
        "The stored page payload is not valid",
    )


async def _read_new_job(session: AsyncSession, new_id: UUID, printer_id: UUID) -> JobRead:
    new_job = await jobs_repo.get(session, new_id)
    if new_job is None:  # pragma: no cover - the queue persisted it before returning
        raise _printer_unavailable(printer_id)
    return JobRead.model_validate(new_job, from_attributes=True)


def _printer_unavailable(printer_id: UUID) -> HTTPException:
    return _retry_rejected(
        status.HTTP_409_CONFLICT,
        "printer-unavailable",
        "Printer is not available to the print queue",
        f"Printer {printer_id} is not known to the print queue",
    )


async def _fail_unqueued(session: AsyncSession, job_id: UUID, error: str) -> None:
    """Mark a retry row that never reached the queue as failed (not left QUEUED).

    A concurrent cancel may already have made it terminal; that is fine.
    """
    with contextlib.suppress(ValueError):
        await jobs_repo.mark_failed(session, job_id, error)


def _retry_rejected(http_status: int, type_: str, title: str, detail: str) -> HTTPException:
    problem = ProblemDetail(type=type_, title=title, status=http_status, detail=detail)
    return HTTPException(status_code=http_status, detail=problem.model_dump(exclude_none=True))
