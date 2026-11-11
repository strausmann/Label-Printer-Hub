"""Print onto sheets (spec 12.6, 15): the read-only preview and the print.

``POST /api/v1/print/{printer_key}/sheet/preview`` needs ``read`` scope and access to the printer.
It plans and draws; it writes nothing and takes no lock.

``POST /api/v1/print/{printer_key}/sheet`` needs ``print`` scope and access to the printer. It
reserves the cells and queues one page job per planned page (202). Domain errors answer in the
sheet API's error envelope, and validation errors name field paths only (pre-flight C19).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.identity_hold import ensure_sheet_not_held
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

router = APIRouter(prefix="/api/v1", tags=["sheets"])

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
            "plan of more than one sheet (`preview_too_large`), or an unknown integration "
            "(`integration_unknown_app`). Item errors carry `item_index`."
        )
    },
    502: {"description": "An integration lookup failed (`integration_lookup_failed`)."},
    503: {"description": "An integration is not configured (`integration_not_configured`)."},
}
_PREVIEW_ONLY_ERRORS: dict[int | str, dict[str, Any]] = {
    **_PREVIEW_ERRORS,
    429: {
        "description": (
            "The key has a preview in progress already (`too-many-previews`): one per key at "
            "a time. The body has the rate limit's shape (`retry_after_seconds`)."
        )
    },
    504: {
        "description": (
            "A page took longer than `PRINTER_HUB_RENDER_TIMEOUT_S` to draw (`render-timeout`). "
            "The drawing goes on: the key's next preview answers 429 `too-many-previews` until "
            "it has ended."
        )
    },
}
_PREVIEW_RETRY_AFTER_S = 1


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
        "run plans one sheet: a second placement is refused (`preview_too_large`), and the items "
        "the sheet does not take are left out (`placed`, `remaining`)."
    ),
    responses=_PREVIEW_ONLY_ERRORS,
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
    # Give the connection back before the lookups and the drawing (R10-1): the printer row is
    # all this request still needs from the session, and a committed session keeps it usable.
    await session.commit()
    # 266-07: one preview per key at a time (a request without a key: per caller and address).
    owner = auth.api_key_id or (auth.source, auth.user, auth.ip)
    try:
        with print_service.preview_slot(owner), mapped():
            return await print_service.preview(
                db_engine.async_session,
                printer=printer,
                request=body,
                lookup=lookup,
                renderer=DEFAULT_CELL_RENDERER,
                language=None if language is None else str(language),
            )
    except print_service.TooManyPreviewsError:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error_code": "too-many-previews",
                "error_message": (
                    "A preview of this key is in progress. Retry after "
                    f"{_PREVIEW_RETRY_AFTER_S} seconds."
                ),
                "retry_after_seconds": _PREVIEW_RETRY_AFTER_S,
            },
            headers={"Retry-After": str(_PREVIEW_RETRY_AFTER_S)},
        ) from None


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
            "device behind the printer changed (`printer-identity-mismatch`), the "
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
    502: {
        "description": (
            "An integration lookup failed (`integration_lookup_failed`), or the print stopped "
            "after some pages were queued (`print_interrupted`, or the error of that page with "
            "`batch_id` and `job_ids` in `error_detail`: those pages keep printing)."
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
        "job has no copies. One run prints one sheet: the first items as many as it takes; the "
        "response says how many were placed and how many remain (`placed`, `remaining`). "
        "The response names the job of each page, where its sheet ID and "
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
    ensure_sheet_not_held(getattr(http.app.state, "print_queue", None), printer.id)  # #231
    language = http.app.state.settings_store.get("general.language")
    await session.commit()  # no connection held through the lookups (R10-1); see preview above
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
