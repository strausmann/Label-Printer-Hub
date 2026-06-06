"""POST /api/print/{printer_key}/batch — best-effort batch print."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import AuthContext, check_printer_access
from app.auth.scope_deps import require_print
from app.db.session import get_session
from app.models.print_batch import PrintBatch
from app.printer_backends.exceptions import (
    ContentTypeDataMismatchError,
    NoTapeLoadedError,
    PrinterCoverOpenError,
    PrinterOfflineError,
    SnmpQueryError,
    TapeMismatchError,
    UnsupportedTapeError,
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
    PrinterOfflineError: "printer_offline",
    PrinterCoverOpenError: "printer_cover_open",
    # R2-2: align with print.py — snmp_query_failed (was snmp_error)
    SnmpQueryError: "snmp_query_failed",
    TapeMismatchError: "tape_mismatch",
}


@router.post(
    "/print/{printer_key}/batch",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=BatchResponse,
    tags=["print"],
    summary="Submit a batch of print jobs",
    description=(
        "Atomic batch print. Validates all items and enqueues the entire batch "
        "as a unit — no per-item errors are returned. Any validation failure "
        "or hardware precondition (printer_offline, cover_open, unsupported_tape, "
        "no_tape_loaded, content_type_data_mismatch) rejects the whole batch "
        "with the appropriate 4xx status code."
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

    try:
        job_ids = await dispatch_batch(
            service=service,
            items=body.items,
            half_cut=use_half_cut,
        )
    except (PrinterCoverOpenError, TapeMismatchError) as exc:
        # 409: hardware state the user can fix (cover open / wrong tape)
        raise HTTPException(
            409,
            detail={
                "error_code": _SYNC_ERROR_MAP[type(exc)],
                # str(exc) is safe here: these exceptions carry only hardware-state
                # descriptions (e.g. "Expected 12mm tape, loaded 24mm"), no stack
                # trace fragments or internal paths.
                "error_message": str(exc),
            },
        ) from exc
    except (PrinterOfflineError, SnmpQueryError) as exc:
        # R2-2: 503 — server-side / network issue, client should retry later.
        # Consistent with print.py which maps PrinterOfflineError → 503.
        raise HTTPException(
            503,
            detail={
                "error_code": _SYNC_ERROR_MAP[type(exc)],
                "error_message": str(exc),
            },
        ) from exc
    except (NoTapeLoadedError, UnsupportedTapeError) as exc:
        # 409: tape hardware state — client must change tape and retry.
        # NOTE: We do NOT expose str(exc) — CWE-209 guard: use a fixed message
        # + structured detail instead of raw exception text.
        if isinstance(exc, NoTapeLoadedError):
            error_code = "no_tape_loaded"
            error_msg = "No tape loaded — insert a Brother TZe or DK cartridge."
            error_detail: dict[str, object] = {}
        else:
            error_code = "unsupported_tape"
            error_msg = "The currently loaded tape width is not supported by the layout engine."
            error_detail = {"tape_mm": exc.tape_mm}
        detail: dict[str, object] = {"error_code": error_code, "error_message": error_msg}
        if error_detail:
            detail["error_detail"] = error_detail
        raise HTTPException(409, detail=detail) from exc
    except ContentTypeDataMismatchError as exc:
        # 422: client-side data error — missing fields for the chosen content type.
        raise HTTPException(
            422,
            detail={
                "error_code": "content_type_data_mismatch",
                "error_message": (
                    "The label data is missing fields required for the selected content type."
                ),
                "error_detail": {"missing_fields": list(exc.missing_fields)},
            },
        ) from exc

    # 7. Persist tracking row
    # auth.subject_id does NOT exist — use api_key_id or source
    created_by = str(auth.api_key_id) if auth.api_key_id else auth.source
    batch_row = PrintBatch(
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
    )
