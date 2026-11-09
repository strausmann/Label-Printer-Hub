"""Sheet type API (spec 15): catalogue, own types, versions, export and import.

Reads need ``read`` scope and are not limited by a key's printer restriction (OC-37); every
write needs ``admin`` (OC-11). The routes stay thin: parse, call the service, map
``SheetApiError`` to the existing error shape.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.sheet_common import actor, mapped
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_admin, require_read
from app.db.session import get_session
from app.models.sheet import SheetType, SheetTypeVersion
from app.schemas.sheets import (
    GeometryMm,
    ImportResponse,
    SheetTypeCreate,
    SheetTypeDetail,
    SheetTypePatch,
    SheetTypeRead,
    VersionCreate,
    VersionRead,
)
from app.sheets import exchange
from app.sheets import type_service as ts
from app.sheets.errors import ImportTooLargeError, SheetTypeVersionNotFoundError
from app.sheets.geometry import normalise, validate_geometry
from app.sheets.naming import KEY_PATTERN

router = APIRouter(prefix="/api/v1/sheet-types", tags=["sheet-types"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ReadDep = Annotated[AuthContext, Depends(require_read)]
AdminDep = Annotated[AuthContext, Depends(require_admin)]
KeyPath = Annotated[str, Path(description="Type key, e.g. `avery-l4736`.")]
VersionPath = Annotated[int, Path(ge=1, le=1_000_000)]

_IMPORT_BODY = {
    "requestBody": {
        "required": True,
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ExportDoc"}}},
    }
}
_NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"description": "Sheet type not found."}}


def _geometry(v: SheetTypeVersion) -> GeometryMm:
    return exchange.geometry_to_doc(ts.version_geometry(v))


def _version_read(v: SheetTypeVersion, sheets: int) -> VersionRead:
    return VersionRead(
        version=v.version,
        geometry=_geometry(v),
        geometry_hash=v.geometry_hash,
        change_note=v.change_note,
        created_at=v.created_at,
        sheets=sheets,
    )


async def _type_read(
    session: AsyncSession,
    t: SheetType,
    versions: list[tuple[SheetTypeVersion, int]] | None = None,
) -> tuple[SheetTypeRead, list[VersionRead]]:
    if versions is None:
        versions = await ts.list_versions_with_sheet_counts(session, t.id)
    current, _ = versions[-1]  # oldest first; a type always has version 1
    hints = validate_geometry(normalise(ts.version_geometry(current)))
    read = SheetTypeRead(
        key=t.key,
        prefix=t.prefix,
        vendor=t.vendor,
        product_codes=list(t.product_codes),
        description=t.description,
        allow_qr=t.allow_qr,
        verified=t.verified,
        origin=t.origin,  # type: ignore[arg-type]
        source_name=t.source_name,
        source_url=t.source_url,
        notes=t.notes,
        archived_at=t.archived_at,
        created_at=t.created_at,
        updated_at=t.updated_at,
        current_version=current.version,
        geometry=_geometry(current),
        hints=hints,
        sheets_in_use=sum(count for _, count in versions),
    )
    return read, [_version_read(v, count) for v, count in versions]


@router.get("", response_model=list[SheetTypeRead], summary="List sheet types")
async def list_sheet_types(
    session: SessionDep,
    _auth: ReadDep,
    page: Annotated[Literal["A4", "Letter"] | None, Query()] = None,
    vendor: Annotated[str | None, Query(max_length=200)] = None,
    q: Annotated[str | None, Query(max_length=100, description="Key, codes, description.")] = None,
    w: Annotated[float | None, Query(ge=0, le=1000, description="Label width, ±0.5 mm.")] = None,
    h: Annotated[float | None, Query(ge=0, le=1000, description="Label height, ±0.5 mm.")] = None,
    include_archived: bool = False,
) -> list[SheetTypeRead]:
    with mapped():
        types = await ts.list_types(
            session,
            page=page,
            vendor=vendor,
            q=q,
            w=w,
            h=h,
            include_archived=include_archived,
        )
        by_type = await ts.list_versions_with_sheet_counts_many(session, [t.id for t in types])
        return [(await _type_read(session, t, by_type[t.id]))[0] for t in types]


@router.post(
    "/import",
    response_model=ImportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Import a sheet type document",
    openapi_extra=_IMPORT_BODY,
    responses={
        200: {"model": ImportResponse, "description": "The same geometry exists already."},
        413: {"description": "Document larger than 64 KB."},
    },
)
async def import_sheet_type(
    request: Request,
    response: Response,
    session: SessionDep,
    auth: AdminDep,
    mode: Annotated[Literal["strict", "new_version", "as_new_key"], Query()] = "strict",
    new_key: Annotated[str | None, Query(max_length=64, pattern=KEY_PATTERN.pattern)] = None,
    new_prefix: Annotated[str | None, Query(max_length=10, pattern=r"^[A-Z][A-Z0-9]{1,9}$")] = None,
) -> ImportResponse:
    with mapped():
        raw = await _read_bounded(request)
        doc = exchange.parse_import(raw)
        result = await exchange.import_type(
            session, doc, mode=mode, new_key=new_key, new_prefix=new_prefix, actor=actor(auth)
        )
    if result.outcome == "unchanged":
        response.status_code = status.HTTP_200_OK
    return ImportResponse(outcome=result.outcome, key=result.key, version=result.version)


async def _read_bounded(request: Request) -> bytes:
    """Read the body, never more than the limit plus one chunk.

    The app has no global body limit, so ``Request.body()`` would buffer anything. A declared
    length above the limit is refused before a byte is read; without one, reading stops as
    soon as more than the limit has arrived.
    """
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > exchange.MAX_IMPORT_BYTES:
        raise ImportTooLargeError()
    buffer = bytearray()
    async for chunk in request.stream():
        buffer.extend(chunk)
        if len(buffer) > exchange.MAX_IMPORT_BYTES:
            raise ImportTooLargeError()
    return bytes(buffer)


@router.post(
    "",
    response_model=SheetTypeRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a sheet type with version 1",
)
async def create_sheet_type(
    body: SheetTypeCreate, session: SessionDep, auth: AdminDep
) -> SheetTypeRead:
    with mapped():
        geometry = exchange.geometry_from_doc(body.geometry)
        fields = ts.TypeFields(
            key=body.key,
            prefix=body.prefix,
            vendor=body.vendor,
            product_codes=list(body.product_codes),
            description=body.description,
            allow_qr=body.allow_qr,
            verified=body.verified,
            source_name=body.source_name,
            source_url=body.source_url,
            notes=body.notes,
        )
        t, _ = await ts.create_type(session, fields, geometry, actor=actor(auth))
        return (await _type_read(session, t))[0]


@router.get(
    "/{key}",
    response_model=SheetTypeDetail,
    summary="One sheet type with its versions",
    responses=_NOT_FOUND,
)
async def get_sheet_type(key: KeyPath, session: SessionDep, _auth: ReadDep) -> SheetTypeDetail:
    with mapped():
        t = await ts.get_type(session, key)
        read, versions = await _type_read(session, t)
        return SheetTypeDetail(**read.model_dump(), versions=versions)


@router.get(
    "/{key}/versions/{n}",
    response_model=VersionRead,
    summary="One version of a sheet type",
    responses=_NOT_FOUND,
)
async def get_sheet_type_version(
    key: KeyPath, n: VersionPath, session: SessionDep, _auth: ReadDep
) -> VersionRead:
    with mapped():
        t = await ts.get_type(session, key)
        for v, count in await ts.list_versions_with_sheet_counts(session, t.id):
            if v.version == n:
                return _version_read(v, count)
        raise SheetTypeVersionNotFoundError()  # the type was resolved above


@router.patch(
    "/{key}",
    response_model=SheetTypeRead,
    summary="Edit the non-geometric fields of a sheet type",
    responses=_NOT_FOUND,
)
async def patch_sheet_type(
    key: KeyPath, body: SheetTypePatch, session: SessionDep, auth: AdminDep
) -> SheetTypeRead:
    with mapped():
        # Only what the client sent: an omitted field is untouched, `null` is a value.
        changes = body.model_dump(exclude_unset=True)
        t = await ts.patch_type(session, key, changes, actor=actor(auth))
        return (await _type_read(session, t))[0]


@router.post(
    "/{key}/versions",
    response_model=VersionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a version with new geometry",
    responses=_NOT_FOUND,
)
async def add_sheet_type_version(
    key: KeyPath, body: VersionCreate, session: SessionDep, auth: AdminDep
) -> VersionRead:
    with mapped():
        geometry = exchange.geometry_from_doc(body.geometry)
        v = await ts.add_version(
            session, key, geometry, actor=actor(auth), change_note=body.change_note
        )
        return _version_read(v, 0)


@router.post(
    "/{key}/archive",
    response_model=SheetTypeRead,
    summary="Archive a sheet type",
    responses=_NOT_FOUND,
)
async def archive_sheet_type(key: KeyPath, session: SessionDep, auth: AdminDep) -> SheetTypeRead:
    with mapped():
        t = await ts.archive_type(session, key, actor=actor(auth))
        return (await _type_read(session, t))[0]


@router.post(
    "/{key}/unarchive",
    response_model=SheetTypeRead,
    summary="Restore an archived sheet type",
    responses=_NOT_FOUND,
)
async def unarchive_sheet_type(key: KeyPath, session: SessionDep, auth: AdminDep) -> SheetTypeRead:
    with mapped():
        t = await ts.unarchive_type(session, key, actor=actor(auth))
        return (await _type_read(session, t))[0]


@router.delete(
    "/{key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a custom sheet type without sheets",
    responses={**_NOT_FOUND, 409: {"description": "Type is in use or not custom."}},
)
async def delete_sheet_type(key: KeyPath, session: SessionDep, auth: AdminDep) -> Response:
    with mapped():
        await ts.delete_type(session, key, actor=actor(auth))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{key}/export",
    response_model=exchange.ExportDoc,
    summary="Export one version of a sheet type as a JSON document",
    responses=_NOT_FOUND,
)
async def export_sheet_type(
    key: KeyPath,
    session: SessionDep,
    _auth: ReadDep,
    version: Annotated[int | None, Query(ge=1, le=1_000_000)] = None,
) -> JSONResponse:
    with mapped():
        doc = await exchange.export_type(session, key, version)
    filename = f"{doc.type.key}-v{doc.version.version}.json"
    return JSONResponse(
        content=doc.model_dump(mode="json"),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
