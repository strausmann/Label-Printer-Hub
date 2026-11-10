"""GET /api/v1/batches/{id}, and the tape run actions continue and reprint (#277)."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import AuthContext, check_printer_access
from app.auth.scope_deps import require_print, require_read
from app.db.session import get_session
from app.models.job import JobState
from app.models.print_batch import PrintBatch
from app.repositories import jobs as jobs_repo
from app.repositories import print_batches as batches_repo
from app.schemas.batch_read import (
    BatchRead,
    BatchSummary,
    ReprintRequest,
    ReprintResponse,
    TapeRunRead,
)
from app.schemas.job import JobRead
from app.services.print_queue import PrintQueue, RunInfo, RunStateError

router = APIRouter(prefix="/api/v1/batches", tags=["batches"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ReadAuthDep = Annotated[AuthContext, Depends(require_read)]
PrintAuthDep = Annotated[AuthContext, Depends(require_print)]


def _run_read(info: RunInfo | None) -> TapeRunRead | None:
    if info is None:
        return None
    return TapeRunRead(
        state=info.state,
        current_sub_job=info.current_sub_job,
        sub_jobs=info.sub_jobs,
        sub_job_size=info.sub_job_size,
        sub_job_starts=info.sub_job_starts,
        job_ids=info.job_ids,
        confirmed_job_ids=info.confirmed_job_ids,
        unknown_from=info.unknown_from,
        unknown_to=info.unknown_to,
        stop_code=info.stop_code,
    )


def _queue(http: Request) -> PrintQueue | None:
    return getattr(http.app.state, "print_queue", None)


async def _visible_batch(session: AsyncSession, batch_id: UUID, auth: AuthContext) -> PrintBatch:
    """The batch, or 404 when it does not exist or belongs to a printer the caller may not use."""
    batch = await batches_repo.get(session, batch_id)
    # Per-printer ACL: a batch of a foreign printer is indistinguishable from a
    # missing one (404).  Empty allowed list = all printers.
    if (
        batch is not None
        and auth is not None
        and auth.allowed_printer_ids
        and str(batch.printer_id) not in auth.allowed_printer_ids
    ):
        batch = None
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    return batch


@router.get("/{batch_id}", response_model=BatchRead)
async def get_batch(
    batch_id: UUID,
    http: Request,
    session: SessionDep,
    _auth: ReadAuthDep,
) -> BatchRead:
    """Snapshot eines Batches + aller aktuellen Job-States.

    Wird von Hangar's /admin/print/result/{batch_id} für das initiale
    Rendering genutzt. summary.all_terminal == False bedeutet, dass Hangar
    den JSON-Stream /api/v1/events verfolgen sollte für
    Live-Updates. ``run`` shows a tape run that prints, waits for a
    confirmation, or stopped (#277).
    """
    batch = await _visible_batch(session, batch_id, _auth)

    # batch.job_ids is list[str] — convert to UUID for repo query
    job_uuids = [UUID(jid) for jid in batch.job_ids]
    fetched_jobs = await jobs_repo.list_by_ids(session, job_uuids)
    job_map = {str(j.id): j for j in fetched_jobs}

    # Reihenfolge entspricht batch.job_ids; cleanup-evicted Jobs werden übersprungen
    ordered = [job_map[jid] for jid in batch.job_ids if jid in job_map]

    summary = BatchSummary(
        total=len(ordered),
        queued=sum(1 for j in ordered if j.state == JobState.QUEUED.value),
        printing=sum(1 for j in ordered if j.state == JobState.PRINTING.value),
        done=sum(1 for j in ordered if j.state == JobState.DONE.value),
        failed=sum(
            1 for j in ordered if j.state in (JobState.FAILED.value, JobState.FAILED_RESTART.value)
        ),
        cancelled=sum(1 for j in ordered if j.state == JobState.CANCELLED.value),
    )

    queue = _queue(http)
    return BatchRead(
        id=batch.id,
        printer_id=batch.printer_id,
        created_by=batch.created_by,
        created_at=batch.created_at,
        jobs=[JobRead.model_validate(j) for j in ordered],
        summary=summary,
        run=None if queue is None else _run_read(queue.run_info(batch.id)),
    )


_RUN_ERRORS: dict[int | str, dict[str, Any]] = {
    403: {"description": "The key lacks the `print` scope or may not use this printer."},
    404: {"description": "No such batch, or no tape run of it that waits for an action."},
    409: {
        "description": (
            "The run is in another state (`run_not_awaiting_confirmation`, `run_not_stopped`)."
        )
    },
}


def _run_error(exc: RunStateError) -> HTTPException:
    status = 422 if exc.code == "label_out_of_range" else 409
    return HTTPException(status, detail={"error_code": exc.code, "error_message": str(exc)})


def _no_run() -> HTTPException:
    return HTTPException(
        404,
        detail={
            "error_code": "run_not_found",
            "error_message": "This batch has no tape run that waits for an action.",
        },
    )


async def _run_batch(
    session: SessionDep, batch_id: UUID, auth: AuthContext, http: Request
) -> PrintQueue:
    batch = await _visible_batch(session, batch_id, auth)
    check_printer_access(auth, batch.printer_id)
    queue = _queue(http)
    if queue is None:
        raise _no_run()
    return queue


@router.post(
    "/{batch_id}/continue",
    response_model=TapeRunRead,
    summary="Start the next sub-job of a tape batch",
    description=(
        "A tape batch of more than 50 labels prints in sub-jobs; each further sub-job starts "
        "only after this call, for example after the user checked or changed the tape (#277)."
    ),
    responses=_RUN_ERRORS,
)
async def continue_batch(
    batch_id: UUID, http: Request, session: SessionDep, auth: PrintAuthDep
) -> TapeRunRead:
    queue = await _run_batch(session, batch_id, auth, http)
    try:
        info = await queue.confirm_run(batch_id)
    except KeyError:
        raise _no_run() from None
    except RunStateError as exc:
        raise _run_error(exc) from None
    run = _run_read(info)
    assert run is not None
    return run


@router.post(
    "/{batch_id}/reprint",
    response_model=ReprintResponse,
    summary="Reprint a stopped tape batch from a label",
    description=(
        "After the tape ran out (or another error stopped a group) the group's outcome is "
        "unknown. Count what printed, fix the tape, and reprint from the first label that is "
        "missing: that label to the end of the group, and every label that was not started, "
        "are queued again as new jobs; the labels before it count as printed. A printer the "
        "tape end paused is resumed (#277). `from_label` outside the group answers 422 "
        "`label_out_of_range`."
    ),
    responses={**_RUN_ERRORS, 422: {"description": "`label_out_of_range`."}},
)
async def reprint_batch(
    batch_id: UUID,
    body: ReprintRequest,
    http: Request,
    session: SessionDep,
    auth: PrintAuthDep,
) -> ReprintResponse:
    queue = await _run_batch(session, batch_id, auth, http)
    try:
        result = await queue.reprint_from(batch_id, body.from_label)
    except KeyError:
        raise _no_run() from None
    except RunStateError as exc:
        raise _run_error(exc) from None
    return ReprintResponse(
        new_job_ids=[str(j) for j in result.new_job_ids],
        confirmed_job_ids=[str(j) for j in result.confirmed_job_ids],
        job_ids=result.job_ids,
        run=_run_read(queue.run_info(batch_id)),
    )
