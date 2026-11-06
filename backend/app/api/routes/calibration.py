"""Calibration API for page printers (spec 15, 18).

Reads and the fit need ``read`` scope, writes need ``admin``; every route also checks the
key's printer restriction (``403 printer_not_allowed`` for another printer's calibration).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.sheet_common import actor, mapped
from app.auth.dependencies import AuthContext, check_printer_access
from app.auth.scope_deps import require_admin, require_read
from app.calibration import service
from app.calibration.fit import Reading, fit
from app.calibration.model import (
    CalibrationIn,
    CalibrationPut,
    CalibrationRead,
    deviation_to_values,
)
from app.db.session import get_session
from app.sheets import type_service as ts

router = APIRouter(prefix="/api/printers", tags=["calibration"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ReadDep = Annotated[AuthContext, Depends(require_read)]
AdminDep = Annotated[AuthContext, Depends(require_admin)]
PrinterPath = Annotated[UUID, Path(description="Printer id (a page printer).")]
TrayPath = Annotated[str, Path(min_length=1, max_length=100, description="Tray key.")]


class ReadingIn(BaseModel):
    col_gap: int = Field(ge=1, le=1000, description="Vertical gap S1, S2, ... counted from 1.")
    row_gap: int = Field(ge=1, le=1000, description="Horizontal gap Z1, Z2, ... counted from 1.")
    across_mm: float = Field(ge=-20, le=20, description="Ink offset to the right, mm.")
    down_mm: float = Field(ge=-20, le=20, description="Ink offset downwards, mm.")


class FitRequest(BaseModel):
    type: str = Field(min_length=1, max_length=200, description="Sheet type key.")
    version: int | None = Field(default=None, ge=1, description="Defaults to the current version.")
    readings: list[ReadingIn] = Field(min_length=3, max_length=200)


class FitResponse(BaseModel):
    values: CalibrationIn
    residuals_mm: list[float]
    flagged: list[int] = Field(description="Indices of readings further than 0.3 mm from the fit.")
    out_of_range: list[str] = Field(description="Names of values outside the allowed ranges.")


@router.get(
    "/{printer_id}/calibration",
    response_model=list[CalibrationRead],
    summary="Calibration of every enabled tray",
)
async def get_calibration(
    printer_id: PrinterPath, session: SessionDep, auth: ReadDep
) -> list[CalibrationRead]:
    check_printer_access(auth, printer_id)
    with mapped():
        return await service.get_all(session, printer_id)


@router.put(
    "/{printer_id}/calibration/{tray}",
    response_model=CalibrationRead,
    summary="Set the manual calibration of a tray",
)
async def put_calibration(
    printer_id: PrinterPath,
    tray: TrayPath,
    body: CalibrationPut,
    session: SessionDep,
    auth: AdminDep,
) -> CalibrationRead:
    check_printer_access(auth, printer_id)
    measured = (body.measured_on.type_key, body.measured_on.version) if body.measured_on else None
    with mapped():
        return await service.put(
            session,
            printer_id,
            tray,
            CalibrationIn(**body.model_dump(exclude={"measured_on"})),
            measured_on=measured,
            actor=actor(auth),
        )


@router.delete(
    "/{printer_id}/calibration/{tray}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reset a tray to no calibration",
)
async def delete_calibration(
    printer_id: PrinterPath, tray: TrayPath, session: SessionDep, auth: AdminDep
) -> Response:
    check_printer_access(auth, printer_id)
    with mapped():
        await service.delete(session, printer_id, tray, actor=actor(auth))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{printer_id}/calibration/{tray}/fit",
    response_model=FitResponse,
    summary="Fit calibration values from measured readings (nothing is saved)",
)
async def fit_calibration(
    printer_id: PrinterPath,
    tray: TrayPath,
    body: FitRequest,
    session: SessionDep,
    auth: ReadDep,
) -> FitResponse:
    check_printer_access(auth, printer_id)
    with mapped():
        await service.snapshot(session, printer_id, tray)  # printer kind and tray must be valid
        if body.version is None:
            version = await ts.current_version(session, (await ts.get_type(session, body.type)).id)
        else:
            version = await ts.get_version(session, body.type, body.version)
        geometry = ts.version_geometry(version)
        result = fit(
            geometry,
            geometry.page_size,
            [Reading(r.col_gap, r.row_gap, r.across_mm, r.down_mm) for r in body.readings],
        )
    return FitResponse(
        values=deviation_to_values(result.dev),
        residuals_mm=result.residuals_mm,
        flagged=result.flagged,
        out_of_range=result.out_of_range,
    )
