"""Sheet API (spec 15): physical sheets, cell marking and the reprint lookup.

Reads need ``read`` scope; every write needs ``print`` (OC-11). Sheets carry no printer
restriction (OC-37). The routes stay thin: parse, call the sheet service, map ``SheetApiError``
to the existing error shape. ``GET /sheets/next-code`` is declared before ``/{code}``.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.sheet_common import actor, mapped
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_print, require_read
from app.db.session import get_session
from app.models.sheet import SheetType
from app.schemas.sheets import (
    CellHitRead,
    CellNumbers,
    CellRead,
    MarkRequest,
    NextCode,
    ResolveRequest,
    SheetCreate,
    SheetRead,
    SheetSummary,
)
from app.services.event_bus import EventBus
from app.sheets import exchange
from app.sheets import sheet_service as ss
from app.sheets import type_service as ts
from app.sheets.geometry import hmm_to_mm
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
    return SheetRead(
        **_summary_fields(detail),  # type: ignore[arg-type]
        id_placement=detail.sheet.id_placement,  # type: ignore[arg-type]
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


@router.get("/api/sheets", response_model=list[SheetSummary], summary="List sheets")
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
    "/api/sheets/next-code",
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


@router.get(
    "/api/sheets/{code}",
    response_model=SheetRead,
    summary="One sheet with all cells that are not free (discarded sheets too)",
    responses=_NOT_FOUND,
)
async def get_sheet(code: CodePath, session: SessionDep, _auth: ReadDep) -> SheetRead:
    with mapped():
        return _read(await ss.get_sheet(session, code))


@router.post(
    "/api/sheets",
    response_model=SheetRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a sheet, with the cells already used marked by hand",
    responses={
        404: {"description": "Sheet type not found."},
        409: {"description": "Sheet type is archived."},
        422: {"description": "A cell number is outside the sheet."},
    },
)
async def create_sheet(
    body: SheetCreate, request: Request, session: SessionDep, auth: PrintDep
) -> SheetRead:
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
        return _read(await ss.get_sheet(session, sheet.code))


@router.post(
    "/api/sheets/{code}/discard",
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
    "/api/sheets/{code}/cells/mark",
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
    "/api/sheets/{code}/cells/unmark",
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
    "/api/sheets/{code}/cells/resolve",
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
    "/api/sheet-cells",
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
