"""Test print for tape and page printers (#228).

``POST /api/v1/printers/{id}/test-print`` prints one test label (tape) or one test page (page
printer) so an operator can see that a printer, its tape or tray, and its margins work.

Refusals, in this order, all ``ProblemDetail`` bodies under ``detail``: scope (dependency),
unknown printer 404, restricted key 403, disabled 409, paused 409, tray 422, then for a page
printer unpolled 409 ``printer-status-unknown``, offline/stale 409 ``printer-offline`` and
``media-unknown`` 409; for a tape printer the submit-time preflight decides (offline,
no tape). A test print reserves no sheet cell and uses no calibration.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.printer_runtime import get_printer_runtime
from app.api.routes.pause_view import pause_view
from app.auth.dependencies import AuthContext, check_printer_access
from app.auth.scope_deps import require_print
from app.config import get_settings
from app.db.session import get_session
from app.models.printer import Printer
from app.page_render.test_page import build_test_page_payload
from app.printer_backends.exceptions import (
    NoTapeLoadedError,
    PrinterDisabledError,
    PrinterOfflineError,
    QrPayloadTooLongError,
    SnmpQueryError,
)
from app.repositories import printer_state as printer_state_repo
from app.schemas.problem import ProblemDetail
from app.services.print_queue import PrintQueue
from app.services.printer_runtime import PrinterRuntime
from app.services.test_print import (
    TestPrintRefusal,
    plan_page_test_print,
    printer_url,
    resolve_tray,
    tape_test_label,
)

router = APIRouter(prefix="/api/v1/printers", tags=["printers"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
PrintDep = Annotated[AuthContext, Depends(require_print)]
RuntimeDep = Annotated[PrinterRuntime | None, Depends(get_printer_runtime)]
PrinterPath = Annotated[UUID, Path(description="Printer id.")]


class TestPrintRequest(BaseModel):
    __test__ = False  # a request model, not a test class

    model_config = ConfigDict(extra="forbid")

    tray: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="Tray key (page printers only); the default tray when omitted.",
    )


class TestPrintAccepted(BaseModel):
    __test__ = False

    job_id: UUID


def _refuse(status_code: int, type_: str, title: str, detail: str | None = None) -> HTTPException:
    problem = ProblemDetail(type=type_, title=title, status=status_code, detail=detail)
    return HTTPException(status_code=status_code, detail=problem.model_dump(exclude_none=True))


def _from_refusal(r: TestPrintRefusal) -> HTTPException:
    return _refuse(r.status, r.code, r.title, r.detail)


def _version() -> str:
    from app.main import HUB_VERSION  # deferred: app.main imports the routers

    return HUB_VERSION


@router.post(
    "/{printer_id}/test-print",
    response_model=TestPrintAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Unknown printer (`printer-not-found`)."},
        status.HTTP_409_CONFLICT: {
            "description": (
                "`printer-disabled`, `printer-paused`, `printer-status-unknown` (page printer "
                "the hub does not poll), `printer-offline`, `no-tape-loaded` (tape printer), "
                "`media-unknown` (page printer) or `printer-unavailable`."
            )
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": (
                "`tray-invalid`: a tray on a tape printer, or an unknown/disabled tray. "
                "`qr-payload-too-long`: the printer link does not fit the fixed QR code of "
                "the loaded tape (QL 62 mm)."
            )
        },
    },
    summary="Print a test label (tape) or a test page (page printer)",
    description=(
        "Prints one test label on a tape printer (printer name, tape width, time, a QR to the "
        "printer's page in the hub) or one test page on a page printer (a frame on the printable "
        "area, name, tray, time, a QR). A tape printer is asked at submit time what tape is "
        "loaded, so the answer needs no polling; a page printer needs a fresh status."
    ),
)
async def test_print(
    request: Request,
    printer_id: PrinterPath,
    session: SessionDep,
    auth: PrintDep,
    runtime: RuntimeDep = None,
    body: Annotated[TestPrintRequest | None, Body()] = None,
) -> TestPrintAccepted:
    requested_tray = body.tray if body is not None else None
    printer = await session.get(Printer, printer_id)
    if printer is None:
        raise _refuse(404, "printer-not-found", "Printer not found", f"No printer {printer_id}")
    check_printer_access(auth, printer_id)
    if not printer.enabled:
        raise _refuse(409, "printer-disabled", "The printer is disabled")
    state = await printer_state_repo.get(session, printer_id)
    paused, _ = pause_view(request, printer_id, state.paused if state is not None else False)
    if paused:
        raise _refuse(409, "printer-paused", "The printer is paused", "Resume it first")

    settings = get_settings()
    url = printer_url(settings.public_url, printer_id)
    version = _version()
    now = datetime.now().astimezone()

    if printer.backend == "ipp":
        queue: PrintQueue | None = getattr(request.app.state, "print_queue", None)
        try:
            tray = await resolve_tray(session, printer_id, requested_tray)
            plan = await plan_page_test_print(
                session,
                printer_id,
                tray,
                polled=runtime is not None and runtime.is_polled(printer_id),
                probe_interval_s=settings.sse_probe_interval_s,
            )
        except TestPrintRefusal as refusal:
            raise _from_refusal(refusal) from None
        payload = build_test_page_payload(
            printer, plan.tray, plan.media, plan.margins_mm, now, version, url
        )
        if queue is None:
            raise _unavailable(printer_id)
        try:
            job_id = await queue.submit_page_job(
                printer_id, payload, api_key_id=auth.api_key_id, source_ip=auth.ip
            )
        except KeyError:
            raise _unavailable(printer_id) from None
        return TestPrintAccepted(job_id=job_id)

    if requested_tray is not None:
        raise _refuse(
            422, "tray-invalid", "A tape printer has no trays", "Omit `tray` for a tape printer"
        )
    service = runtime.print_service_for(printer_id) if runtime is not None else None
    if service is None:
        raise _unavailable(printer_id)
    try:
        job_id = await service.submit_test_label(
            lambda width_mm: tape_test_label(printer, width_mm, now, version, url)
        )
    except PrinterDisabledError:
        raise _refuse(409, "printer-disabled", "The printer is disabled") from None
    except (PrinterOfflineError, SnmpQueryError):
        raise _refuse(
            409, "printer-offline", "The printer is offline", "The printer did not answer"
        ) from None
    except NoTapeLoadedError:
        raise _refuse(409, "no-tape-loaded", "No tape is loaded", "Load a tape first") from None
    except QrPayloadTooLongError as exc:
        # #258: the QR of a QL 62 mm label has a fixed size; the printer URL must fit it.
        raise _refuse(
            422,
            "qr-payload-too-long",
            "The printer link does not fit the fixed QR code of this tape",
            f"{exc.length} bytes, at most {exc.max_bytes}",
        ) from None
    return TestPrintAccepted(job_id=job_id)


def _unavailable(printer_id: UUID) -> HTTPException:
    return _refuse(
        409,
        "printer-unavailable",
        "Printer is not available to the print queue",
        f"Printer {printer_id} is not known to the print queue",
    )
