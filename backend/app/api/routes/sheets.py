"""Sheet API (spec 15): physical sheets, cell marking and the reprint lookup.

Reads need ``read`` scope; every write needs ``print`` (OC-11). Sheets carry no printer
restriction (OC-37). The routes stay thin: parse, call the sheet service, map ``SheetApiError``
to the existing error shape. ``GET /sheets/next-code`` is declared before ``/{code}``.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Query, Request, status
from fastapi.exceptions import RequestValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.identity_hold import ensure_not_held
from app.api.routes.sheet_common import actor, mapped
from app.auth.dependencies import AuthContext, check_printer_access
from app.auth.scope_deps import require_print, require_read
from app.db import engine as db_engine
from app.db.session import get_session
from app.models.printer import Printer
from app.models.sheet import SheetType
from app.repositories import printers as printers_repo
from app.schemas.sheets import (
    CellHitRead,
    CellNumbers,
    CellRead,
    MarginBandsMm,
    MarginCheckRead,
    MarkRequest,
    NextCode,
    ResolveRequest,
    SheetCreate,
    SheetCreated,
    SheetRead,
    SheetSummary,
)
from app.services.event_bus import EventBus
from app.sheets import exchange, print_service
from app.sheets import sheet_service as ss
from app.sheets import type_service as ts
from app.sheets.errors import PrinterNotFoundError, SheetPrinterDisabledError
from app.sheets.geometry import hmm_to_mm
from app.sheets.reservation import NewSheetIn
from app.sheets.sheet_service import MarkedCell

router = APIRouter(tags=["sheets"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ReadDep = Annotated[AuthContext, Depends(require_read)]
PrintDep = Annotated[AuthContext, Depends(require_print)]
CodePath = Annotated[
    str,
    Path(
        max_length=24,
        pattern=r"^[A-Z][A-Z0-9]{1,9}-[0-9]{4,}$",
        description="Sheet code, e.g. `L4736-0002`.",
    ),
]
_NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"description": "Sheet not found."}}
_WRITE_ERRORS: dict[int | str, dict[str, Any]] = {
    **_NOT_FOUND,
    409: {"description": "Sheet is discarded, or the cells are in the wrong state."},
    422: {"description": "A cell number is outside the sheet."},
}


def _bus(request: Request) -> EventBus | None:
    bus: EventBus | None = getattr(request.app.state, "event_bus", None)
    return bus


def _type_label(t: SheetType) -> str:
    codes = list(t.product_codes)
    if t.vendor and codes:
        return f"{t.vendor} {codes[0]}"
    return codes[0] if codes else t.key


def _summary_fields(row: ss.SheetListRow | ss.SheetDetail) -> dict[str, object]:
    return {
        "code": row.sheet.code,
        "type_key": row.type.key,
        "type_label": _type_label(row.type),
        "version": row.version.version,
        "label_w": hmm_to_mm(row.version.label_w),
        "label_h": hmm_to_mm(row.version.label_h),
        "total": row.total,
        "used": row.used,
        "reserved": row.reserved,
        "unconfirmed": row.unconfirmed,
        "free": row.free,
        "state": row.sheet.state,
        "last_used_at": row.sheet.last_used_at,
    }


def _read(detail: ss.SheetDetail) -> SheetRead:
    return SheetRead(**_read_fields(detail))


def _read_fields(detail: ss.SheetDetail) -> dict[str, Any]:
    return dict(
        **_summary_fields(detail),
        id_placement=detail.sheet.id_placement,
        id_printed=detail.sheet.id_printed,
        feed_mark_printed=detail.sheet.feed_mark_printed,
        note=detail.sheet.note,
        geometry=exchange.geometry_to_doc(ts.version_geometry(detail.version)),
        cells=[
            CellRead(
                cell=c.cell_no,
                state=c.state,  # type: ignore[arg-type]
                source=c.source,
                purpose=c.purpose,
                ref=c.ref,
                marked_by_hand=c.marked_by_hand,
                job_id=c.job_id,
                updated_at=c.updated_at,
            )
            for c in detail.cells
        ],
        discarded_at=detail.sheet.discarded_at,
    )


@router.get("/api/v1/sheets", response_model=list[SheetSummary], summary="List sheets")
async def list_sheets(
    session: SessionDep,
    _auth: ReadDep,
    type_key: Annotated[
        str | None, Query(alias="type", max_length=64, description="Sheet type key.")
    ] = None,
    free_at_least: Annotated[int | None, Query(ge=0, le=400)] = None,
    state: Annotated[Literal["active", "full", "discarded", "all"], Query()] = "active",
    q: Annotated[str | None, Query(max_length=24, description="Part of the code.")] = None,
) -> list[SheetSummary]:
    with mapped():
        rows = await ss.list_sheets(
            session, type_key=type_key, free_at_least=free_at_least, state=state, q=q
        )
    return [SheetSummary(**_summary_fields(r)) for r in rows]  # type: ignore[arg-type]


@router.get(
    "/api/v1/sheets/next-code",
    response_model=NextCode,
    summary="The code a new sheet of a type would probably get",
    responses={404: {"description": "Sheet type not found."}},
)
async def next_code(
    session: SessionDep,
    _auth: ReadDep,
    type_key: Annotated[str, Query(alias="type", max_length=64, description="Sheet type key.")],
) -> NextCode:
    with mapped():
        return NextCode(code=await ss.peek_next_code(session, type_key), hint="probable")


async def _usable_printer(session: AsyncSession, auth: AuthContext, key: str) -> Printer:
    """The printer a request names: it exists, the caller may use it and it is switched on
    (pre-flight C18)."""
    printer = await printers_repo.resolve_by_slug_or_uuid(session, key)
    if printer is None:
        raise PrinterNotFoundError().to_http()
    check_printer_access(auth, printer.id)
    if not printer.enabled:
        raise SheetPrinterDisabledError().to_http()
    return printer


def _language(request: Request) -> str | None:
    language = request.app.state.settings_store.get("general.language")
    return None if language is None else str(language)


@router.get(
    "/api/v1/sheets/margin-check",
    response_model=MarginCheckRead,
    summary="Where the margin ID and the feed mark of a new sheet would go on a printer",
    description=(
        "What the first job of a new sheet of the type would do on this printer and tray: the "
        "band and corner of the margin ID, whether a QR is drawn next to it, and whether the "
        "feed-direction mark prints (in the hub's current language). `printable=false` means no "
        "margin band is deep enough: the sheet can still be created and the ID added by hand. "
        "Read-only."
    ),
    responses={
        403: {"description": "These credentials may not use this printer."},
        404: {"description": "Unknown printer (`printer_not_found`) or sheet type."},
        409: {"description": "Not a page printer (`media_kind_mismatch`) or it is disabled."},
        422: {"description": "Invalid request (`invalid_request`) or an unknown tray."},
    },
)
async def margin_check(
    request: Request,
    session: SessionDep,
    auth: ReadDep,
    type_key: Annotated[str, Query(alias="type", max_length=64, description="Sheet type key.")],
    printer: Annotated[str, Query(min_length=1, max_length=100, description="Slug or UUID.")],
    tray: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
) -> MarginCheckRead:
    with mapped():
        found = await _usable_printer(session, auth, printer)
        check = await print_service.margin_check(
            session, printer=found, type_key=type_key, tray=tray, language=_language(request)
        )
    return MarginCheckRead(
        bands_mm=MarginBandsMm(**check.bands_mm),
        band=check.band,
        corner=check.corner,
        usable_mm=check.usable_mm,
        qr=check.qr,
        printable=check.printable,
        reason=check.reason,
        feed_mark=check.feed_mark,
    )


@router.get(
    "/api/v1/sheets/{code}",
    response_model=SheetRead,
    summary="One sheet with all cells that are not free (discarded sheets too)",
    responses=_NOT_FOUND,
)
async def get_sheet(code: CodePath, session: SessionDep, _auth: ReadDep) -> SheetRead:
    with mapped():
        return _read(await ss.get_sheet(session, code))


@router.post(
    "/api/v1/sheets",
    response_model=SheetCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Create a sheet, with the cells already used marked by hand",
    description=(
        "`id_placement` `margin` (the default) and `manual` only store the sheet. `cell` also "
        "reserves the first free cell for the sheet ID label and queues an ID-only job on the "
        "named page printer; `job_id` names it. If the job cannot be queued, the sheet stays "
        "without a reservation and the ID goes onto the next job's first free cell; the error "
        "names the sheet in `error_detail.sheet_code`."
    ),
    responses={
        403: {"description": "These credentials may not use the printer."},
        404: {"description": "Sheet type or printer not found."},
        409: {
            "description": (
                "Sheet type is archived, no cell is free for the ID (`insufficient_cells`), the "
                "printer is disabled (`printer_disabled`) or unknown to the queue."
            )
        },
        422: {"description": "A cell number is outside the sheet, or `cell` without a printer."},
        502: {"description": "The ID-only job was queued only partly (`print_interrupted`)."},
    },
)
async def create_sheet(
    body: SheetCreate, request: Request, session: SessionDep, auth: PrintDep
) -> SheetCreated:
    if body.id_placement == "cell":
        return await _create_with_id_cell(body, request, session, auth)
    with mapped():
        sheet = await ss.create_sheet(
            session,
            type_key=body.type,
            version=body.version,
            id_placement=body.id_placement,
            used_cells=[MarkedCell(m.cell, m.purpose) for m in body.used_cells],
            note=body.note,
            actor=actor(auth),
            bus=_bus(request),
        )
        return SheetCreated(**_read_fields(await ss.get_sheet(session, sheet.code)), job_id=None)


async def _create_with_id_cell(
    body: SheetCreate, request: Request, session: AsyncSession, auth: AuthContext
) -> SheetCreated:
    """``cell``: create the sheet, reserve the ID cell and queue the ID-only job in one go."""
    if body.printer is None:  # field paths only, like every other validation error
        raise RequestValidationError(
            [
                {
                    "type": "missing",
                    "loc": ("body", "printer"),
                    "msg": "Field required",
                    "input": None,
                }
            ]
        )
    with mapped():
        printer = await _usable_printer(session, auth, body.printer)
        ensure_not_held(getattr(request.app.state, "print_queue", None), printer.id)  # #231
        # Give the connection back: the service opens its own sessions, and a request holding
        # one while it waits for another can use up the pool (the R10-1 class). The printer row
        # stays usable (expire_on_commit=False); the session starts again for the read below.
        await session.commit()
        code, job_id = await print_service.create_sheet_with_id_label(
            db_engine.async_session,
            printer=printer,
            tray=body.tray,
            new=NewSheetIn(
                type_key=body.type,
                version=body.version,
                id_placement="cell",
                used_cells=[MarkedCell(m.cell, m.purpose) for m in body.used_cells],
                note=body.note,
            ),
            queue=request.app.state.print_queue,
            actor=actor(auth),
            api_key_id=auth.api_key_id,
            source_ip=auth.ip,
            language=_language(request),
            bus=_bus(request),
        )
        return SheetCreated(**_read_fields(await ss.get_sheet(session, code)), job_id=job_id)


@router.post(
    "/api/v1/sheets/{code}/discard",
    response_model=SheetRead,
    summary="Discard a sheet; its code is never issued again",
    responses={**_NOT_FOUND, 409: {"description": "A running job holds cells of the sheet."}},
)
async def discard_sheet(
    code: CodePath, request: Request, session: SessionDep, auth: PrintDep
) -> SheetRead:
    with mapped():
        await ss.discard_sheet(session, code, actor=actor(auth), bus=_bus(request))
        return _read(await ss.get_sheet(session, code))


@router.post(
    "/api/v1/sheets/{code}/cells/mark",
    response_model=SheetRead,
    summary="Mark free cells as used by hand",
    responses=_WRITE_ERRORS,
)
async def mark_cells(
    code: CodePath, body: MarkRequest, request: Request, session: SessionDep, auth: PrintDep
) -> SheetRead:
    with mapped():
        detail = await ss.mark_cells(
            session,
            code,
            [MarkedCell(m.cell, m.purpose) for m in body.cells],
            actor=actor(auth),
            bus=_bus(request),
        )
    return _read(detail)


@router.post(
    "/api/v1/sheets/{code}/cells/unmark",
    response_model=SheetRead,
    summary="Free cells that were marked by hand",
    responses=_WRITE_ERRORS,
)
async def unmark_cells(
    code: CodePath, body: CellNumbers, request: Request, session: SessionDep, auth: PrintDep
) -> SheetRead:
    with mapped():
        detail = await ss.unmark_cells(
            session, code, body.cells, actor=actor(auth), bus=_bus(request)
        )
    return _read(detail)


@router.post(
    "/api/v1/sheets/{code}/cells/resolve",
    response_model=SheetRead,
    summary="Settle cells waiting for confirmation as printed or not printed",
    responses=_WRITE_ERRORS,
)
async def resolve_cells(
    code: CodePath, body: ResolveRequest, request: Request, session: SessionDep, auth: PrintDep
) -> SheetRead:
    with mapped():
        detail = await ss.resolve_cells(
            session, code, body.cells, body.outcome, actor=actor(auth), bus=_bus(request)
        )
    return _read(detail)


@router.get(
    "/api/v1/sheet-cells",
    response_model=list[CellHitRead],
    summary="Where an integration item was printed before, newest first",
)
async def find_cells(
    session: SessionDep,
    _auth: ReadDep,
    source: Annotated[str, Query(pattern=r"^[a-z][a-z0-9_-]{0,31}$")],
    ref: Annotated[str, Query(min_length=1, max_length=200)],
) -> list[CellHitRead]:
    with mapped():
        hits = await ss.find_cells(session, source=source, ref=ref)
    return [
        CellHitRead(
            code=h.code,
            cell=h.cell,
            state=h.state,  # type: ignore[arg-type]
            purpose=h.purpose,
            updated_at=h.updated_at,
        )
        for h in hits
    ]
