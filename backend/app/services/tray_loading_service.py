# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""How a page printer's tray takes paper (#350, R-350-5).

``print_side`` is the face that gets printed, as the sheet lies in the tray; ``leading_edge``
is the edge of the printed image that lands at the sheet edge put in first. The back of a
sheet is printed turned by 180 degrees when the bottom edge leads.

Writing: an admin may always set it (an upsert). A ``print`` key only while it is unset: the
write is ``INSERT … ON CONFLICT DO NOTHING`` and no inserted row is the refusal, so two first
answers at the same time cannot both win. The insert comes first and holds SQLite's write lock;
the tray is checked after it, so a printer save that removes the tray cannot leave an orphan.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import CursorResult, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.printer_tray import PrinterTray
from app.models.printer_tray_loading import PrinterTrayLoading
from app.services.page_jobs import PagePayload
from app.sheets.errors import (
    MediaKindMismatchError,
    PrinterNotFoundError,
    TrayLoadingAlreadySetError,
    TrayUnknownError,
)

__all__ = ["TrayLoading", "build_test_page", "get", "get_all", "put"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrayLoading:
    print_side: Literal["up", "down"]
    leading_edge: Literal["top", "bottom"]


def _of(row: PrinterTrayLoading) -> TrayLoading:
    return TrayLoading(
        print_side="down" if row.print_side == "down" else "up",
        leading_edge="bottom" if row.leading_edge == "bottom" else "top",
    )


async def get(session: AsyncSession, printer_id: UUID, tray_key: str) -> TrayLoading | None:
    row = await session.get(PrinterTrayLoading, (printer_id, tray_key))
    return None if row is None else _of(row)


async def get_all(session: AsyncSession, printer_id: UUID) -> dict[str, TrayLoading]:
    rows = (
        await session.execute(
            select(PrinterTrayLoading).where(col(PrinterTrayLoading.printer_id) == printer_id)
        )
    ).scalars()
    return {r.tray_key: _of(r) for r in rows}


async def put(
    session: AsyncSession,
    printer_id: UUID,
    tray_key: str,
    loading: TrayLoading,
    *,
    actor: str,
    admin: bool,
) -> TrayLoading:
    """Store the loading of a tray; ``admin`` may overwrite, ``print`` only set it once."""
    if session.in_transaction():  # the authentication read leaves a read transaction open
        await session.commit()
    values = {
        "printer_id": printer_id,
        "tray_key": tray_key,
        "print_side": loading.print_side,
        "leading_edge": loading.leading_edge,
        "updated_at": datetime.now(UTC),
        "updated_by": actor,
    }
    stmt = insert(PrinterTrayLoading).values(**values)
    if admin:
        stmt = stmt.on_conflict_do_update(
            index_elements=["printer_id", "tray_key"],
            set_={k: values[k] for k in ("print_side", "leading_edge", "updated_at", "updated_by")},
        )
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=["printer_id", "tray_key"])
    try:
        try:
            result = await session.execute(stmt)
        except IntegrityError:
            # The only foreign key is the printer: an unknown printer is a 404 (review M3). The
            # failed statement wrote nothing; the rollback below ends the transaction.
            raise PrinterNotFoundError() from None
        inserted = isinstance(result, CursorResult) and result.rowcount == 1
        tray = (
            await session.execute(
                select(col(PrinterTray.tray_key)).where(
                    col(PrinterTray.printer_id) == printer_id,
                    col(PrinterTray.tray_key) == tray_key,
                )
            )
        ).first()
        if tray is None:
            raise TrayUnknownError([])  # never echo the caller's key
        if not inserted:
            raise TrayLoadingAlreadySetError()
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    logger.info("tray loading set for printer %s", printer_id)
    return loading


async def build_test_page(
    session: AsyncSession, printer_id: UUID, tray: str, language: str | None
) -> PagePayload:
    """The loading test page of a page printer's enabled tray (R-350-5); writes nothing."""
    from app.calibration import service as calibration_service
    from app.models.printer import Printer
    from app.sheets.back_side import loading_page_payload

    printer = await session.get(Printer, printer_id)
    if printer is None:
        raise PrinterNotFoundError()
    if printer.backend != "ipp":
        raise MediaKindMismatchError()
    tray_key = await calibration_service.resolve_tray(session, printer_id, tray)
    return loading_page_payload(tray_key, "A4", language)
