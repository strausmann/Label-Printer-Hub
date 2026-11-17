# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""POST /api/v1/print/{printer_key}/batch — best-effort batch print."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.print_errors import print_error_http
from app.auth.dependencies import (
    AuthContext,
    charge_lookup_fan_out,
    check_printer_access,
    refund_lookup_fan_out,
)
from app.auth.scope_deps import require_print
from app.db.session import get_session
from app.models.print_batch import PrintBatch
from app.printer_backends.exceptions import (
    ConflictingOrientationError,
    NoTapeLoadedError,
    PrinterCoverOpenError,
    PrinterOfflineError,
    SnmpQueryError,
    TapeMismatchError,
)
from app.repositories import print_batches as batches_repo
from app.repositories import printers as printers_repo
from app.schemas.print_batch import BatchRequest, BatchResponse
from app.services.batch_dispatch import dispatch_batch
from app.services.print_error_codes import KNOWN_PRINT_ERROR_TYPES
from app.services.print_queue import (
    MAX_LABELS_PER_TAPE_JOB,
    QUEUED_RUN_RETRY_AFTER_S,
    TooManyQueuedRunsError,
)
from app.sheets.errors import MediaKindMismatchError

# SessionDep locally — Hub has no central app/api/deps.py module.
SessionDep = Annotated[AsyncSession, Depends(get_session)]

# prefix=/api → POST /api/v1/print/{...}/batch. print.py has no prefix
# (POST /api/v1/print), so this is a clean separation.
router = APIRouter(prefix="/api/v1")

# What dispatch_batch raises before it looks anything up: the queue claim and the preflight.
_NO_LOOKUP_RAN = (
    TooManyQueuedRunsError,
    PrinterCoverOpenError,
    TapeMismatchError,
    PrinterOfflineError,
    SnmpQueryError,
    NoTapeLoadedError,
    ConflictingOrientationError,
)


@router.post(
    "/print/{printer_key}/batch",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=BatchResponse,
    tags=["print"],
    summary="Submit a batch of print jobs",
    description=(
        "Validates all items and enqueues the batch as one tape run — no per-item errors are "
        "returned. The labels (copies included) print in sub-jobs of at most 50; each further "
        "sub-job waits for `POST /api/v1/batches/{batch_id}/continue`. Inside a sub-job the "
        "labels go out in groups of 10 with a status check after each; when a group fails, the "
        "run stops (see `GET /api/v1/batches/{batch_id}`). A tape end stops it when the printer "
        "reports it: a PT sets the SNMP `noPaper` bit; whether a QL-820NWB reports the end of a "
        "DK roll is not verified, so on a QL the check reliably catches only an unreachable "
        "printer and an open cover. Any validation failure "
        "or hardware precondition (printer_offline, cover_open, unsupported_tape, "
        "no_tape_loaded, content_type_data_mismatch) rejects the whole batch "
        "with the appropriate 4xx status code. A page printer (IPP) answers "
        "409 media_kind_mismatch. A printer holds at most "
        "`LABELYARD_MAX_QUEUED_RUNS_PER_PRINTER` (default 5) runs and a key at most "
        "`LABELYARD_MAX_QUEUED_RUNS_PER_KEY` (default 20); a run counts until it is over. "
        "A run that waits for `/continue` or a reprint counts against its key only. Over a "
        "cap the batch answers 429 too-many-queued-runs. Items that carry a `lookup` also "
        "count against the key's rate limit: the request's own token pays for the first lookup, "
        "each further one takes another token (never more than a full bucket), and a batch the "
        "remaining budget cannot cover answers 429 `rate_limit_exceeded` before any lookup; a "
        "batch refused before the first lookup gives the tokens back."
    ),
)
async def create_batch(
    printer_key: Annotated[str, Path(description="Printer slug or UUID")],
    body: BatchRequest,
    http: Request,
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_print)],
) -> BatchResponse:
    # 1. Resolve printer (404 if unknown slug/uuid)
    printer = await printers_repo.resolve_by_slug_or_uuid(session, printer_key)
    if printer is None:
        raise HTTPException(404, detail={"error_code": "printer_not_found"})

    # 2. Konsistenz-Check: body.printer_slug muss zur URL passen (wenn gesetzt)
    if body.printer_slug is not None and body.printer_slug != printer.slug:
        raise HTTPException(
            400,
            detail={
                "error_code": "printer_slug_mismatch",
                "error_message": (
                    f"body.printer_slug={body.printer_slug!r} matches neither URL "
                    f"slug={printer.slug!r}."
                ),
            },
        )

    # 3. ACL: api-key may be restricted to a subset of printer_ids
    check_printer_access(auth, printer.id)

    # 3b. Tape jobs only: a page printer (IPP) prints sheets, not tape labels.
    if printer.backend == "ipp":
        raise MediaKindMismatchError().to_http()

    # 4. R3-Drift #10: backend_router direkt aus app.state — KEIN get_app_state.
    backend_router = getattr(http.app.state, "backend_router", None)
    if backend_router is None:
        raise HTTPException(503, detail={"error_code": "router_not_initialized"})

    backend = backend_router.get(printer.slug)
    if backend is None:
        raise HTTPException(
            503,
            detail={
                "error_code": "printer_unreachable",
                "error_message": f"No backend registered for slug={printer.slug!r}.",
            },
        )

    # 5. R4-A-C2-Fix (Volle Multi-Printer): pro-Drucker PrintService via service_for().
    try:
        service = backend_router.service_for(printer.slug)
    except KeyError as err:
        raise HTTPException(
            503,
            detail={
                "error_code": "service_not_initialized",
                "error_message": f"No PrintService registered for slug={printer.slug!r}.",
            },
        ) from err

    # 6. Dispatch (half_cut: override takes precedence over backend capability)
    backend_supports_half_cut: bool = getattr(backend, "half_cut_supported", False)
    if body.half_cut_override is not None:
        use_half_cut = body.half_cut_override and backend_supports_half_cut
    else:
        use_half_cut = backend_supports_half_cut

    # Every item with a lookup is one integration call; the request's token pays for the first.
    # 429 here, before the printer is asked and before any lookup.
    charged = charge_lookup_fan_out(auth, sum(1 for item in body.items if item.lookup is not None))

    # #277: the queue's tape run carries the batch id, so continue/reprint find it.
    run_id = uuid4()
    label_ids: list[UUID] = []
    try:
        try:
            job_ids = await dispatch_batch(
                service=service,
                items=body.items,
                half_cut=use_half_cut,
                run_id=run_id,
                label_ids=label_ids,
                queue=getattr(http.app.state, "print_queue", None),
                printer_id=printer.id,
                api_key_id=auth.api_key_id,
                source_ip=auth.ip,
            )
        except _NO_LOOKUP_RAN:
            # Refused before the first lookup (queue claim, preflight): the client retries.
            refund_lookup_fan_out(auth, charged)
            raise
    except TooManyQueuedRunsError as exc:
        # 263-76: the rate-limit answer's shape; nothing was looked up, drawn or stored.
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error_code": "too-many-queued-runs",
                "error_message": (
                    f"{exc} Retry after {QUEUED_RUN_RETRY_AFTER_S} seconds, or continue or "
                    "discard a waiting run."
                ),
                "retry_after_seconds": QUEUED_RUN_RETRY_AFTER_S,
            },
            headers={"Retry-After": str(QUEUED_RUN_RETRY_AFTER_S)},
        ) from exc
    except ConflictingOrientationError as exc:
        # 422: a batch prints with one orientation (#258)
        raise HTTPException(
            422,
            detail={
                "error_code": "conflicting_orientation",
                "error_message": "The batch items ask for different orientations.",
                "error_detail": {"orientations": list(exc.orientations)},
            },
        ) from exc
    except KNOWN_PRINT_ERROR_TYPES as exc:
        # The shared table (#378): status, code, fixed text and detail under ``detail``.
        raise print_error_http(exc, http) from exc

    # 7. Persist tracking row
    # auth.subject_id does NOT exist — use api_key_id or source
    created_by = str(auth.api_key_id) if auth.api_key_id else auth.source
    batch_row = PrintBatch(
        id=run_id,
        printer_id=printer.id,
        job_ids=[str(jid) for jid in job_ids],
        created_by=created_by,
    )
    await batches_repo.create(session, batch_row)

    return BatchResponse(
        batch_id=batch_row.id,
        printer_id=printer.id,
        queued_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        job_ids=[str(jid) for jid in job_ids],
        label_job_ids=[str(jid) for jid in label_ids],
        sub_job_size=MAX_LABELS_PER_TAPE_JOB,
    )
