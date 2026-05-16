"""POST /print + GET /jobs/{job_id} + POST /jobs/{job_id}/resume."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.printer_backends.exceptions import (
    PrinterCoverOpenError,
    PrinterOfflineError,
    SnmpQueryError,
    TapeEmptyError,
    TapeMismatchError,
)
from app.printer_backends.snmp_helper import LiveStatus, query_live_status
from app.schemas.print_request import PrintRequest
from app.schemas.print_response import PrintJobResponse, PrintJobStatusResponse
from app.services.job_lifecycle import JobState
from app.services.lookup_service import LookupFailedError
from app.services.print_queue import PrinterAlreadyActiveError
from app.services.template_loader import TemplateNotFoundError

_log = logging.getLogger(__name__)

router = APIRouter()


class _PrinterResumeResponse(BaseModel):
    """200 response body for POST /printer/resume."""

    printer_id: str
    state: str


_SYNC_ERROR_MAP: dict[type[Exception], tuple[int, str]] = {
    TemplateNotFoundError: (404, "template_not_found"),
    LookupFailedError: (502, "integration_lookup_failed"),
    TapeMismatchError: (409, "tape_mismatch"),
    TapeEmptyError: (409, "tape_empty"),
    PrinterCoverOpenError: (409, "printer_cover_open"),
    PrinterOfflineError: (503, "printer_offline"),
}


@router.post(
    "/print",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=PrintJobResponse,
    tags=["print"],
    summary="Submit a print job",
    description=(
        "Submit a label-print job.  The job is queued and dispatched "
        "asynchronously by the queue worker.  Returns 202 with the new "
        "job's UUID and state ``queued``.  Returns 4xx/5xx on printer "
        "errors (tape mismatch, offline, cover open, etc.)."
    ),
)
async def create_print_job(request: PrintRequest, http: Request) -> Any:
    service = http.app.state.print_service
    try:
        job_id = await service.submit_print_job(request)
    except tuple(_SYNC_ERROR_MAP) as exc:
        http_status, code = _SYNC_ERROR_MAP[type(exc)]
        body: dict[str, object] = {"error_code": code, "error_message": str(exc)}
        if isinstance(exc, TapeMismatchError):
            body["error_detail"] = {
                "expected_mm": exc.expected_mm,
                "loaded_mm": exc.loaded_mm,
            }
        return JSONResponse(status_code=http_status, content=body)
    return PrintJobResponse(job_id=job_id, status="queued")


@router.get(
    "/jobs/{job_id}",
    response_model=PrintJobStatusResponse,
    tags=["print"],
    summary="Get print job status",
    description=(
        "Return the current status and metadata for a print job submitted "
        "via ``POST /print``.  When the job is actively printing, the "
        "response includes live SNMP status from the printer.  "
        "Returns 404 when the job is not found."
    ),
)
async def get_job_status(job_id: str, http: Request) -> PrintJobStatusResponse:
    queue = http.app.state.print_queue
    try:
        job = await queue.get(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}") from exc

    live: LiveStatus | None = None
    if job.state == JobState.PRINTING:
        host = getattr(http.app.state, "printer_host", None)
        community = getattr(http.app.state, "printer_snmp_community", "public")
        if host:
            try:
                # Short timeout — this is on the request path, must stay snappy.
                # If SNMP is slow/unavailable, omit the live block (non-fatal).
                live = await query_live_status(host, community=community, timeout_s=1.0)
            except SnmpQueryError:
                _log.warning("live SNMP query failed for job %s", job_id, exc_info=True)
                live = None

    return PrintJobStatusResponse(
        job_id=job.id,
        status=job.state,
        error_code=getattr(job, "error_code", None),
        error_message=getattr(job, "error_message", None),
        error_detail=getattr(job, "error_detail", None),
        created_at=job.submitted_at,
        started_at=getattr(job, "started_at", None),
        finished_at=getattr(job, "finished_at", None),
        live=live,
    )


@router.post(
    "/printer/resume",
    status_code=status.HTTP_200_OK,
    response_model=_PrinterResumeResponse,
    tags=["print"],
    summary="Resume the printer queue",
    description=(
        "Resume the printer queue after a recoverable error halted it "
        "(tape empty, cover open, tape mismatch, printer offline).  "
        "Returns 200 with the printer ID and state ``active``.  "
        "Returns 404 when no printer is configured.  "
        "Returns 409 when the printer is already active."
    ),
)
async def resume_printer(http: Request) -> Any:
    """Resume the printer queue after a recoverable error halted it.

    Recoverable errors (TapeEmpty, CoverOpen, TapeMismatch, PrinterOffline)
    pause the printer worker. After the user fixes the underlying issue
    (changes tape, closes cover, reconnects), they call this endpoint to
    unblock subsequent jobs in the queue.

    Returns 200 with ``{ "printer_id": ..., "state": "active" }``.
    Returns 404 if no printer is configured.
    Returns 409 if the printer is already active.
    """
    queue = http.app.state.print_queue
    printer_id = getattr(http.app.state, "printer_id", None)
    if printer_id is None:
        raise HTTPException(status_code=404, detail="no printer configured")
    try:
        await queue.resume_printer(printer_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"unknown printer_id: {printer_id}",
        ) from exc
    except PrinterAlreadyActiveError:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"error_code": "already_active", "error_message": "Printer is already active"},
        )
    return {"printer_id": printer_id, "state": "active"}


@router.post(
    "/jobs/{job_id}/resume",
    status_code=status.HTTP_200_OK,
    response_model=PrintJobStatusResponse,
    tags=["print"],
    summary="Resume a paused print job",
    description=(
        "Resume a print job that is in ``PAUSED`` state (waiting for a tape "
        "change after a tape-mismatch error with ``on_tape_mismatch=queue``).  "
        "Transitions the job from ``PAUSED`` to ``QUEUED`` so the worker picks "
        "it up again.  Returns 200 with the updated status.  "
        "Returns 404 when the job is not found.  "
        "Returns 409 when the job is not in ``PAUSED`` state."
    ),
)
async def resume_job(job_id: str, http: Request) -> Any:
    """Resume a job that is PAUSED waiting for a tape change.

    User-driven workflow: client posted /print with on_tape_mismatch=queue,
    got 202 + job_id with state=PAUSED. User changes physical tape,
    calls this endpoint. The job transitions PAUSED → QUEUED and the worker
    picks it up.

    Returns 200 with the updated status.
    Returns 404 if job not found.
    Returns 409 if job is not in PAUSED state (error_code=invalid_state).
    """
    queue = http.app.state.print_queue
    try:
        job = await queue.get(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}") from exc

    if job.state != JobState.PAUSED:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error_code": "invalid_state",
                "error_message": (f"job {job_id} is in state {job.state.value!r}, not PAUSED"),
            },
        )

    # resume_job() transitions PAUSED → QUEUED and re-enqueues the job.
    # It also clears error metadata on the job object.
    await queue.resume_job(job_id)
    job.error_code = None
    job.error_message = None
    job.error_detail = None

    return PrintJobStatusResponse(
        job_id=job.id,
        status=job.state,
        error_code=None,
        error_message=None,
        error_detail=None,
        created_at=job.submitted_at,
        started_at=getattr(job, "started_at", None),
        finished_at=getattr(job, "finished_at", None),
        live=None,
    )
