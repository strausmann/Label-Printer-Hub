"""POST /api/v1/print, POST /api/v1/printer/resume and POST /api/v1/render/preview."""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.print_errors import SYNC_ERROR_TYPES, print_error_response
from app.auth.dependencies import AuthContext, check_printer_access
from app.auth.scope_deps import require_print, require_read
from app.db.session import get_session
from app.printer_backends.exceptions import (
    ContentTypeDataMismatchError,
    QrPayloadTooLongError,
    UnsupportedTapeError,
)
from app.repositories import printer_state as printer_state_repo
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.schemas.label_layout import LabelOrientation, QlLayoutPreset
from app.schemas.print_request import PrintRequest, RawLabelData
from app.schemas.print_response import PrintJobResponse
from app.services.layout_engine import LayoutEngine
from app.services.print_queue import PrinterAlreadyActiveError

_log = logging.getLogger(__name__)

router = APIRouter()
# `router` spells the full path in each decorator (/api/v1/print, /api/v1/printer/resume);
# `render_router` carries the prefix for POST /api/v1/render/preview.
render_router = APIRouter(prefix="/api/v1")


def _check_default_printer(http: Request, auth: AuthContext) -> None:
    """403 when the key may not use the default printer these routes act on."""
    printer_id = getattr(http.app.state, "printer_id", None)
    if printer_id is not None:
        check_printer_access(auth, UUID(str(printer_id)), default_printer=True)


class _PrinterResumeResponse(BaseModel):
    """200 response body for POST /api/v1/printer/resume."""

    printer_id: UUID | str
    state: str


@router.post(
    "/api/v1/print",
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
async def create_print_job(
    request: PrintRequest,
    http: Request,
    _auth: Annotated[AuthContext, Depends(require_print)],
) -> Any:
    _check_default_printer(http, _auth)
    service = http.app.state.print_service
    if service is None:
        # No tape printer is wired (fresh install, or only IPP page printers): nothing can
        # take a label job. Same body shape as the other errors of this route.
        return JSONResponse(
            status_code=503,
            content={
                "error_code": "no_tape_printer",
                "error_message": "No tape printer is configured for label printing.",
            },
        )
    try:
        job_id = await service.submit_print_job(
            request, api_key_id=_auth.api_key_id, source_ip=_auth.ip
        )
    except SYNC_ERROR_TYPES as exc:
        return print_error_response(exc)
    # Phase 2: submit_print_job gibt jetzt UUID zurück; Response-Schema erwartet str.
    return PrintJobResponse(job_id=str(job_id), status="queued")


@router.post(
    "/api/v1/printer/resume",
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
async def resume_printer(
    http: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _auth: Annotated[AuthContext, Depends(require_print)],
) -> _PrinterResumeResponse | JSONResponse:
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
    check_printer_access(_auth, UUID(str(printer_id)), default_printer=True)
    # Same effect as POST /api/v1/printers/{id}/resume: clear the persisted flag too.
    await printer_state_repo.set_paused(session, printer_id, False)
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
    return _PrinterResumeResponse(printer_id=printer_id, state="active")


class _PreviewRequest(BaseModel):
    """Request body for POST /render/preview.

    Phase 1k.1a (Task 25): render-only endpoint — no printer, no queue, no DB.
    """

    content_type: ContentType
    data: RawLabelData
    tape_mm: int = 12
    orientation: LabelOrientation | None = None
    """``across``/``along`` (#258); omitted: the tape default (62 mm across, else along).
    The preview never applies a printer's stored default: send it explicitly."""
    layout_preset: QlLayoutPreset | None = None
    """QL 62 mm across-width preset; omitted: ``compact``."""


@render_router.post(
    "/render/preview",
    tags=["print"],
    summary="Render a label preview as PNG",
    description=(
        "Render a label using the LayoutEngine and return the result as a "
        "PNG image (no printer interaction, no job created).  "
        "Useful for UI preview and debugging.  "
        "Renders through the same engine call as a print job, so ``orientation`` and "
        "``layout_preset`` give the exact image the job would print (an ``along`` image is "
        "the landscape band before the printer backend rotates it).  "
        "Returns 422 when ``data`` is missing fields required by ``content_type`` or the "
        "QR payload does not fit the fixed QR code (``qr_payload_too_long``).  "
        "Returns 409 when ``tape_mm`` is not a supported tape width or the orientation is "
        "not available for it."
    ),
    response_class=Response,
    responses={
        200: {"content": {"image/png": {}}, "description": "PNG label bitmap"},
        409: {"description": "Unsupported tape width or orientation"},
        422: {"description": "Data missing required fields, or QR payload too long"},
    },
)
async def render_preview(
    body: _PreviewRequest,
    _auth: Annotated[AuthContext, Depends(require_read)],
) -> Response:
    """Render a label preview without touching the printer or DB.

    Uses a fresh LayoutEngine instance so that this endpoint works even
    when no printer is configured (dev / CI mode).

    Returns 200 with Content-Type: image/png on success.
    Returns 409 (unsupported_tape) when tape_mm is not in TAPE_GEOMETRY.
    Returns 422 (content_type_data_mismatch) when data is missing fields for content_type.
    """
    engine = LayoutEngine()
    label_data = LabelData(
        primary_id=body.data.primary_id,
        title=body.data.title,
        qr_payload=body.data.qr_payload,
        source_app="preview",
        secondary=body.data.secondary,
        items=body.data.items,
    )

    def _render() -> bytes:
        # Same code path as a print job (#258): the job renders with the same engine call.
        image = engine.render(
            body.tape_mm,
            body.content_type,
            label_data,
            orientation=body.orientation,
            preset=body.layout_preset,
        )
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()

    # asyncio.to_thread: render() + image.save() are CPU-bound (QR generation,
    # font rendering, PNG encoding). Offloading to a thread pool prevents blocking
    # the event loop during heavy rendering.
    # Errors are raised from the thread and re-raised here for structured handling.
    # NOTE: We do NOT expose str(exc) directly to the client — CodeQL CWE-209:
    # raw exception strings may contain stack trace fragments or internal paths.
    try:
        png_bytes = await asyncio.to_thread(_render)
    except UnsupportedTapeError as exc:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error_code": "unsupported_tape",
                "error_message": (
                    "The currently loaded tape width is not supported by the layout engine."
                    if exc.orientation is None
                    else "The selected orientation is not available for this tape width."
                ),
                "error_detail": {"tape_mm": exc.tape_mm},
            },
        )
    except ContentTypeDataMismatchError as exc:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                # R2-4: align with the print endpoint (_SYNC_ERROR_MAP) which uses
                # "content_type_data_mismatch" — was inconsistently "data_mismatch"
                "error_code": "content_type_data_mismatch",
                "error_message": (
                    "The label data is missing fields required for the selected content type."
                ),
                "error_detail": {"missing_fields": list(exc.missing_fields)},
            },
        )
    except QrPayloadTooLongError as exc:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=_qr_too_long_body(exc),
        )

    return Response(content=png_bytes, media_type="image/png")


def _qr_too_long_body(exc: QrPayloadTooLongError) -> dict[str, object]:
    return {
        "error_code": "qr_payload_too_long",
        "error_message": "The QR payload does not fit the fixed QR code of this tape.",
        "error_detail": {"length": exc.length, "max_bytes": exc.max_bytes},
    }
