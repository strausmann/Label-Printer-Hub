"""Calibration API for page printers (spec 15, 18).

Reads and the fit need ``read`` scope, writes need ``admin``; every route also checks the
key's printer restriction (``403 printer_not_allowed`` for another printer's calibration).
"""

from __future__ import annotations

import asyncio
import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.sheet_common import actor, mapped
from app.auth.dependencies import AuthContext, check_printer_access
from app.auth.scope_deps import require_admin, require_print, require_read
from app.calibration import page, service
from app.calibration.fit import Reading, fit
from app.calibration.model import (
    CalibrationIn,
    CalibrationPut,
    CalibrationRead,
    deviation_to_values,
)
from app.db.session import get_session
from app.schemas.problem import ProblemDetail
from app.sheets import type_service as ts

router = APIRouter(prefix="/api/printers", tags=["calibration"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ReadDep = Annotated[AuthContext, Depends(require_read)]
AdminDep = Annotated[AuthContext, Depends(require_admin)]
PrintDep = Annotated[AuthContext, Depends(require_print)]
PrinterPath = Annotated[UUID, Path(description="Printer id (a page printer).")]
TrayPath = Annotated[str, Path(min_length=1, max_length=100, description="Tray key.")]


class ReadingIn(BaseModel):
    col_gap: int = Field(ge=1, le=1000, description="Vertical gap S1, S2, ... counted from 1.")
    row_gap: int = Field(ge=1, le=1000, description="Horizontal gap Z1, Z2, ... counted from 1.")
    across_mm: float = Field(
        ge=-20, le=20, allow_inf_nan=False, description="Ink offset to the right, mm."
    )
    down_mm: float = Field(
        ge=-20, le=20, allow_inf_nan=False, description="Ink offset downwards, mm."
    )


class FitRequest(BaseModel):
    type: str = Field(min_length=1, max_length=200, description="Sheet type key.")
    version: int | None = Field(default=None, ge=1, description="Defaults to the current version.")
    readings: list[ReadingIn] = Field(min_length=3, max_length=200)


class FitResponse(BaseModel):
    values: CalibrationIn
    residuals_mm: list[float]
    flagged: list[int] = Field(
        description="0-based indices into `readings` of those further than 0.3 mm from the fit."
    )
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


class PageRequest(BaseModel):
    type: str = Field(min_length=1, max_length=200, description="Sheet type key.")
    version: int | None = Field(default=None, ge=1, description="Defaults to the current version.")
    corrected: bool = Field(
        default=False,
        description="Print with the tray's stored correction, to check it (not to measure).",
    )


class PageJobAccepted(BaseModel):
    job_id: UUID


@router.post(
    "/{printer_id}/calibration/{tray}/page",
    response_model=PageJobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        status.HTTP_409_CONFLICT: {
            "description": (
                "The printer is a tape printer (`media_kind_mismatch`) or is not known to the "
                "print queue (`printer-unavailable`)."
            )
        }
    },
    summary="Print the calibration page (no sheet is created)",
)
async def print_calibration_page(
    request: Request,
    printer_id: PrinterPath,
    tray: TrayPath,
    body: PageRequest,
    session: SessionDep,
    auth: PrintDep,
) -> PageJobAccepted:
    check_printer_access(auth, printer_id)
    with mapped():
        payload = await page.build_payload(
            session, printer_id, tray, type_key=body.type, version=body.version,
            corrected=body.corrected,
        )  # fmt: skip
        queue = getattr(request.app.state, "print_queue", None)
        if queue is None:
            raise _printer_unavailable(printer_id)
        try:
            job_id = await queue.submit_page_job(
                printer_id, payload, api_key_id=auth.api_key_id, source_ip=auth.ip
            )
        except KeyError:
            raise _printer_unavailable(printer_id) from None
    return PageJobAccepted(job_id=job_id)


@router.get(
    "/{printer_id}/calibration/{tray}/page/pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}, "description": "The calibration page."}},
    summary="Download the calibration page as a PDF",
)
async def download_calibration_page(
    printer_id: PrinterPath,
    tray: TrayPath,
    session: SessionDep,
    auth: ReadDep,
    type_key: Annotated[
        str, Query(alias="type", min_length=1, max_length=200, description="Sheet type key.")
    ],
    version: Annotated[
        int | None, Query(ge=1, description="Defaults to the current version.")
    ] = None,
    corrected: bool = False,
) -> Response:
    check_printer_access(auth, printer_id)
    with mapped():
        payload = await page.build_payload(
            session, printer_id, tray, type_key=type_key, version=version, corrected=corrected
        )
    pdf = await asyncio.to_thread(page.render_calibration_page, payload)  # what the job renders
    name = re.sub(r"[^A-Za-z0-9._-]", "_", f"calibration-{payload.detail['type_key']}")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{name}-v{payload.detail["version"]}.pdf"'
        },
    )


def _printer_unavailable(printer_id: UUID) -> HTTPException:
    problem = ProblemDetail(
        type="printer-unavailable",
        title="Printer is not available to the print queue",
        status=status.HTTP_409_CONFLICT,
        detail=f"Printer {printer_id} is not known to the print queue",
    )
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail=problem.model_dump(exclude_none=True)
    )
