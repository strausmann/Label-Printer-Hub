"""POST /api/print/{printer_key}/batch — best-effort batch print."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_print
from app.db.session import get_session
from app.models.print_batch import PrintBatch
from app.printer_backends.exceptions import (
    PrinterCoverOpenError,
    PrinterOfflineError,
    SnmpQueryError,
)
from app.repositories import print_batches as batches_repo
from app.repositories import printers as printers_repo
from app.schemas.print_batch import BatchRequest, BatchResponse
from app.services.batch_dispatch import dispatch_batch

# SessionDep locally — Hub has no central app/api/deps.py module.
SessionDep = Annotated[AsyncSession, Depends(get_session)]

# prefix=/api → POST /api/print/{...}/batch. print.py has no prefix
# (POST /print), so this is a clean separation.
router = APIRouter(prefix="/api")

_SYNC_ERROR_MAP: dict[type[Exception], str] = {
    PrinterOfflineError:   "printer_offline",
    PrinterCoverOpenError: "printer_cover_open",
    SnmpQueryError:        "snmp_error",
}


@router.post(
    "/print/{printer_key}/batch",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=BatchResponse,
    tags=["print"],
    summary="Submit a batch of print jobs",
    description=(
        "Best-effort batch print. Validates each item individually and "
        "returns per-item errors. Hardware preconditions (printer_offline, "
        "cover_open) reject the entire batch with 409."
    ),
)
async def create_batch(
    printer_key: Annotated[str, Path(description="Printer slug or UUID")],
    body: BatchRequest,
    http: Request,
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_print)],
) -> BatchResponse:
    # 1. Resolve printer
    printer = await printers_repo.resolve_by_slug_or_uuid(session, printer_key)
    if printer is None:
        raise HTTPException(404, detail={"error_code": "printer_not_found"})

    # 2. Best-effort dispatch
    service = http.app.state.print_service
    try:
        job_ids, errors = await dispatch_batch(service, body.items)
    except (PrinterOfflineError, PrinterCoverOpenError, SnmpQueryError) as exc:
        raise HTTPException(409, detail={
            "error_code": _SYNC_ERROR_MAP[type(exc)],
            "error_message": str(exc),
        })

    # 3. Persist tracking row
    # auth.subject_id does NOT exist — use api_key_id or source
    created_by = str(auth.api_key_id) if auth.api_key_id else auth.source
    batch_row = PrintBatch(
        printer_id=printer.id,
        job_ids=job_ids,
        created_by=created_by,
    )
    await batches_repo.create(session, batch_row)

    return BatchResponse(
        batch_id=batch_row.id,
        printer_id=printer.id,
        queued_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        job_ids=job_ids,
        errors=errors,
    )
