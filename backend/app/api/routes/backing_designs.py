# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Backing design API (#350, R-350-4): the vendor print on the back of a liner.

Reads need ``read`` scope, writes ``admin``. A sheet type links a design by its key
(``PATCH /api/v1/sheet-types/{key}``); the free strips decide where the sheet code goes on the
back of the liner.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.sheet_common import mapped
from app.api.routes.sheet_types import design_read
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_admin, require_read
from app.db.session import get_session
from app.schemas.sheets import BackingDesignCreate, BackingDesignPatch, BackingDesignRead
from app.sheets import backing_design_service as bds

router = APIRouter(prefix="/api/v1/backing-designs", tags=["sheet-types"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ReadDep = Annotated[AuthContext, Depends(require_read)]
AdminDep = Annotated[AuthContext, Depends(require_admin)]
KeyPath = Annotated[
    str, Path(max_length=64, description="Design key, e.g. `avery-zweckform-ultragrip`.")
]
_NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"description": "Backing design not found."}}
_INVALID: dict[int | str, dict[str, Any]] = {
    422: {
        "description": (
            "Invalid request: a strip is smaller than 1 mm or reaches outside the page "
            "(`invalid_geometry`, `error_detail.field` names it, e.g. `strips.0`)."
        )
    }
}


@router.get("", response_model=list[BackingDesignRead], summary="List backing designs")
async def list_backing_designs(session: SessionDep, _auth: ReadDep) -> list[BackingDesignRead]:
    with mapped():
        return [design_read(d, used) for d, used in await bds.list_with_usage(session)]


@router.post(
    "",
    response_model=BackingDesignRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a backing design",
    responses={409: {"description": "The key exists (`backing_design_exists`)."}, **_INVALID},
)
async def create_backing_design(
    body: BackingDesignCreate, session: SessionDep, _auth: AdminDep
) -> BackingDesignRead:
    with mapped():
        design = await bds.create(
            session,
            key=body.key,
            name=body.name,
            page_size=body.page_size,
            strips=bds.strips_from_mm(body.strips),
        )
        return design_read(design, 0)


@router.patch(
    "/{key}",
    response_model=BackingDesignRead,
    summary="Change the name or the free strips of a backing design",
    responses={**_NOT_FOUND, **_INVALID},
)
async def patch_backing_design(
    key: KeyPath, body: BackingDesignPatch, session: SessionDep, _auth: AdminDep
) -> BackingDesignRead:
    changes: dict[str, Any] = {}
    sent = body.model_fields_set
    with mapped():
        if "name" in sent and body.name is not None:
            changes["name"] = body.name
        if "strips" in sent and body.strips is not None:
            changes["strips"] = bds.strips_from_mm(body.strips)
        design = await bds.patch(session, key, changes)
        return design_read(design, await bds.types_in_use(session, design.id))


@router.delete(
    "/{key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a backing design no sheet type uses",
    responses={
        **_NOT_FOUND,
        409: {"description": "A sheet type uses the design (`backing_design_in_use`)."},
    },
)
async def delete_backing_design(key: KeyPath, session: SessionDep, _auth: AdminDep) -> Response:
    with mapped():
        await bds.delete(session, key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
