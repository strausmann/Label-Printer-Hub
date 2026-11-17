# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""How a page printer's tray takes paper (#350, R-350-5): the guided test and the answer.

Both routes need ``print`` scope and access to the printer. A ``print`` key may set the loading
only while it is unset (409 ``tray_loading_already_set`` after); an ``admin`` key may change it.
The test page is a printer check like the test print: it is not held while the device behind
the printer is flagged as changed (R-350-10).
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.sheet_common import actor, mapped
from app.auth.dependencies import AuthContext, check_printer_access
from app.auth.scope_deps import require_print
from app.db.session import get_session
from app.schemas.capabilities import TrayLoadingRead
from app.schemas.sheets import PageJobQueued
from app.services import tray_loading_service
from app.sheets.errors import PrinterUnavailableError

router = APIRouter(prefix="/api/v1/printers", tags=["printers"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
PrintDep = Annotated[AuthContext, Depends(require_print)]
PrinterPath = Annotated[UUID, Path(description="Printer id (a page printer).")]
TrayPath = Annotated[str, Path(min_length=1, max_length=100, description="Tray key.")]


class TrayLoadingPut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    print_side: Literal["up", "down"]
    leading_edge: Literal["top", "bottom"]


def _language(request: Request) -> str | None:
    language = request.app.state.settings_store.get("general.language")
    return None if language is None else str(language)


@router.put(
    "/{printer_id}/trays/{tray}/loading",
    response_model=TrayLoadingRead,
    summary="Set how a tray takes paper",
    description=(
        "`print_side`: the face that gets printed as the sheet lies in the tray; "
        "`leading_edge`: the edge of the printed image at the sheet edge put in first. A "
        "`print` key may set it only while it is unset; an `admin` key may change it."
    ),
    responses={
        403: {"description": "These credentials may not use this printer."},
        409: {"description": "Already set and the key is not admin (`tray_loading_already_set`)."},
        422: {"description": "Invalid request or an unknown tray (`tray_unknown`)."},
    },
)
async def put_tray_loading(
    printer_id: PrinterPath,
    tray: TrayPath,
    body: TrayLoadingPut,
    session: SessionDep,
    auth: PrintDep,
) -> TrayLoadingRead:
    check_printer_access(auth, printer_id)
    with mapped():
        loading = await tray_loading_service.put(
            session,
            printer_id,
            tray,
            tray_loading_service.TrayLoading(body.print_side, body.leading_edge),
            actor=actor(auth),
            admin=auth.scope == "admin",
        )
    return TrayLoadingRead(print_side=loading.print_side, leading_edge=loading.leading_edge)


@router.post(
    "/{printer_id}/trays/{tray}/loading/test-page",
    response_model=PageJobQueued,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Print the tray loading test page",
    description=(
        'A page with a big "TOP ↑" at the top edge of the printed image and "PRINTED SIDE" '
        "in the middle, in the hub's language. Mark a cross on the face-up side next to the "
        'edge that goes in first, print, then answer where the print and "TOP" landed.'
    ),
    responses={
        403: {"description": "These credentials may not use this printer."},
        404: {"description": "Unknown printer (`printer_not_found`)."},
        409: {
            "description": (
                "A tape printer (`media_kind_mismatch`) or unknown to the print queue "
                "(`printer-unavailable`)."
            )
        },
        422: {"description": "An unknown or disabled tray (`tray_unknown`)."},
    },
)
async def print_tray_loading_page(
    printer_id: PrinterPath,
    tray: TrayPath,
    request: Request,
    session: SessionDep,
    auth: PrintDep,
) -> PageJobQueued:
    check_printer_access(auth, printer_id)
    with mapped():
        payload = await tray_loading_service.build_test_page(
            session, printer_id, tray, _language(request)
        )
        await session.commit()
        queue = getattr(request.app.state, "print_queue", None)
        if queue is None:
            raise PrinterUnavailableError()
        try:
            job_id = await queue.submit_page_job(
                printer_id, payload, api_key_id=auth.api_key_id, source_ip=auth.ip
            )
        except KeyError:
            raise PrinterUnavailableError() from None
    return PageJobQueued(job_id=job_id)
