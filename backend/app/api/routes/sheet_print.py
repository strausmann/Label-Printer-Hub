"""Print onto sheets (spec 12.6, 15): the read-only preview and the print.

``POST /api/print/{printer_key}/sheet/preview`` needs ``read`` scope and access to the printer.
It plans and draws; it writes nothing and takes no lock.

``POST /api/print/{printer_key}/sheet`` needs ``print`` scope and access to the printer. It
reserves the cells and queues one page job per planned page (202). Domain errors answer in the
sheet API's error envelope, and validation errors name field paths only (pre-flight C19).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.sheet_common import actor, mapped
from app.auth.dependencies import AuthContext, check_printer_access
from app.auth.scope_deps import require_print, require_read
from app.db import engine as db_engine
from app.db.session import get_session
from app.repositories import printers as printers_repo
from app.schemas.sheet_print import SheetPreview, SheetPrintRequest, SheetPrintResponse
from app.services.lookup_service import AppLookupService
from app.sheets import print_service
from app.sheets.cell_render import DEFAULT_CELL_RENDERER
from app.sheets.errors import PrinterNotFoundError, SheetPrinterDisabledError

router = APIRouter(prefix="/api", tags=["sheets"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ReadDep = Annotated[AuthContext, Depends(require_read)]
PrintDep = Annotated[AuthContext, Depends(require_print)]
PrinterKey = Annotated[str, Path(max_length=100, description="Printer slug or UUID.")]

# Stateless, like the lookup route's: one instance for the process.
_lookup_service = AppLookupService()


def get_lookup_service() -> AppLookupService:
    return _lookup_service


LookupDep = Annotated[AppLookupService, Depends(get_lookup_service)]

_PREVIEW_ERRORS: dict[int | str, dict[str, Any]] = {
    403: {"description": "These credentials may not use this printer (`printer_not_allowed`)."},
    404: {
        "description": (
            "Unknown printer (`printer_not_found`), sheet (`sheet_not_found`), sheet type, or "
            "an item the integration does not have (`app-lookup-not-found`)."
        )
    },
    409: {
        "description": (
            "Not a page printer (`media_kind_mismatch`), the printer is disabled "
            "(`printer_disabled`), the sheet is discarded or archived, or the cells do not "
            "fit (`insufficient_cells`, `cells_taken`)."
        )
    },
    422: {
        "description": (
            "Invalid request (`invalid_request`, field paths only), an unknown or disabled tray "
            "(`tray_unknown`), an item the cell cannot show (`content_type_data_mismatch`), a "
            "plan of more than 10 pages (`preview_too_large`), or an unknown integration "
            "(`integration_unknown_app`). Item errors carry `item_index`."
        )
    },
    502: {"description": "An integration lookup failed (`integration_lookup_failed`)."},
    503: {"description": "An integration is not configured (`integration_not_configured`)."},
}


@router.post(
    "/print/{printer_key}/sheet/preview",
    response_model=SheetPreview,
    summary="Preview a sheet print",
    description=(
        "Plans where the items would go and draws them, without reserving or printing anything. "
        "Per page: every cell with its state, a 150 dpi PNG of the new content only, whether "
        "the sheet ID and the feed-direction mark are printed, and where. Also the cells left "
        "free, the plan to send back as `expected_cells`, and where lookup items were printed "
        "before. The picture is never calibrated. Only page (IPP) printers print sheets. A "
        "plan of more than 10 pages is refused (`preview_too_large`)."
    ),
    responses=_PREVIEW_ERRORS,
)
async def preview_sheet_print(
    printer_key: PrinterKey,
    body: SheetPrintRequest,
    http: Request,
    session: SessionDep,
    auth: ReadDep,
    lookup: LookupDep,
) -> SheetPreview:
    printer = await printers_repo.resolve_by_slug_or_uuid(session, printer_key)
    if printer is None:
        raise PrinterNotFoundError().to_http()
    check_printer_access(auth, printer.id)
    if not printer.enabled:
        raise SheetPrinterDisabledError().to_http()
    language = http.app.state.settings_store.get("general.language")
    with mapped():
        return await print_service.preview(
            session,
            printer=printer,
            request=body,
            lookup=lookup,
            renderer=DEFAULT_CELL_RENDERER,
            language=None if language is None else str(language),
        )


_PRINT_ERRORS: dict[int | str, dict[str, Any]] = {
    **_PREVIEW_ERRORS,
    403: {
        "description": (
            "The key lacks the `print` scope, or may not use this printer (`printer_not_allowed`)."
        )
    },
    409: {
        "description": (
            "Not a page printer (`media_kind_mismatch`), the printer is disabled "
            "(`printer_disabled`) or unknown to the print queue (`printer-unavailable`), the "
            "sheet is discarded or archived, the cells do not fit (`insufficient_cells`, "
            "`cells_taken`), or the plan differs from `expected_cells` (`plan_changed`, with the "
            "new plan)."
        )
    },
    422: {
        "description": (
            "Invalid request (`invalid_request`, field paths only), an unknown or disabled tray "
            "(`tray_unknown`), an item the cell cannot show (`content_type_data_mismatch`), or an "
            "unknown integration (`integration_unknown_app`). Item errors carry `item_index`."
        )
    },
}


@router.post(
    "/print/{printer_key}/sheet",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SheetPrintResponse,
    summary="Print labels onto sheets",
    description=(
        "Reserves the cells for the items and queues one page job per planned page; the cells "
        "turn `used` when a page has printed. Send the preview's `expected_cells` to be refused "
        "(`plan_changed`) if the plan moved since. Nothing is reserved if an item fails: a "
        "lookup, or a cell that cannot show the item (the error names `item_index`). A sheet "
        "job has no copies. The response names the job of each page, where its sheet ID and "
        "feed-direction mark are printed, and one batch id for all of them."
    ),
    responses=_PRINT_ERRORS,
)
async def print_sheet(
    printer_key: PrinterKey,
    body: SheetPrintRequest,
    http: Request,
    session: SessionDep,
    auth: PrintDep,
    lookup: LookupDep,
) -> SheetPrintResponse:
    printer = await printers_repo.resolve_by_slug_or_uuid(session, printer_key)
    if printer is None:
        raise PrinterNotFoundError().to_http()
    check_printer_access(auth, printer.id)
    if not printer.enabled:
        raise SheetPrinterDisabledError().to_http()
    language = http.app.state.settings_store.get("general.language")
    with mapped():
        return await print_service.print_sheets(
            db_engine.async_session,
            printer=printer,
            request=body,
            lookup=lookup,
            queue=http.app.state.print_queue,
            actor=actor(auth),
            api_key_id=auth.api_key_id,
            source_ip=auth.ip,
            language=None if language is None else str(language),
            bus=getattr(http.app.state, "event_bus", None),
        )
