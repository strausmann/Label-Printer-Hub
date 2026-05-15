"""POST /print + GET /jobs/{job_id}."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.printer_backends.exceptions import SnmpQueryError
from app.printer_backends.snmp_helper import LiveStatus, query_live_status
from app.schemas.print_request import PrintRequest
from app.schemas.print_response import PrintJobResponse, PrintJobStatusResponse
from app.services.job_lifecycle import JobState
from app.services.lookup_service import LookupFailedError
from app.services.template_loader import TemplateNotFoundError

_log = logging.getLogger(__name__)

router = APIRouter()

_SYNC_ERROR_MAP: dict[type[Exception], tuple[int, str]] = {
    TemplateNotFoundError: (404, "template_not_found"),
    LookupFailedError: (502, "integration_lookup_failed"),
}


@router.post(
    "/print",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=PrintJobResponse,
)
async def create_print_job(request: PrintRequest, http: Request) -> Any:
    service = http.app.state.print_service
    try:
        job_id = await service.submit_print_job(request)
    except tuple(_SYNC_ERROR_MAP) as exc:
        http_status, code = _SYNC_ERROR_MAP[type(exc)]
        return JSONResponse(
            status_code=http_status,
            content={"error_code": code, "error_message": str(exc)},
        )
    return PrintJobResponse(job_id=job_id, status="queued")


@router.get(
    "/jobs/{job_id}",
    response_model=PrintJobStatusResponse,
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
