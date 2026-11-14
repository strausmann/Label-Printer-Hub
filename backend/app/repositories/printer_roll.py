# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Repository for the stored roll record of a printer (#229)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.printer_roll import PrinterRoll


async def get(session: AsyncSession, printer_id: UUID) -> PrinterRoll | None:
    """Return the roll record of a printer, or None if none was ever observed."""
    return await session.get(PrinterRoll, printer_id)


async def set_colour(
    session: AsyncSession,
    printer_id: UUID,
    *,
    colour: str | None,
    width_mm: int,
    media_raw: str | None = None,
    now: datetime,
) -> bool:
    """Record the operator's colour for the roll of width ``width_mm``; commits.

    One conditional UPDATE: it matches only while the stored roll still has that width
    (and media text, when given), so a
    roll change detected between the caller's read and this write is not overwritten. Returns
    False when nothing matched.
    """
    conditions = [PrinterRoll.printer_id == printer_id, PrinterRoll.width_mm == width_mm]
    if media_raw is not None:
        conditions.append(PrinterRoll.media_raw == media_raw)
    result = await session.execute(
        update(PrinterRoll)
        .where(*conditions)  # type: ignore[arg-type]
        .values(
            colour=colour,
            set_at=now if colour is not None else None,
            prompt_pending=False,
        )
    )
    await session.commit()
    return bool(result.rowcount)  # type: ignore[attr-defined]
