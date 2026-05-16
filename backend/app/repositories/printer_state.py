"""Repository for PrinterState aggregate — operator pause/resume."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.printer_state import PrinterState


async def get(session: AsyncSession, printer_id: UUID) -> PrinterState | None:
    """Return the PrinterState row for the given printer, or None if absent."""
    return await session.get(PrinterState, printer_id)


async def get_or_create(session: AsyncSession, printer_id: UUID) -> PrinterState:
    """Return the existing PrinterState row, or insert a default (paused=False) one."""
    existing = await session.get(PrinterState, printer_id)
    if existing is not None:
        return existing
    state = PrinterState(printer_id=printer_id, paused=False)
    session.add(state)
    await session.commit()
    await session.refresh(state)
    return state


async def set_paused(
    session: AsyncSession, printer_id: UUID, paused: bool
) -> PrinterState:
    """Upsert the paused flag for a printer. Returns the updated row."""
    existing = await session.get(PrinterState, printer_id)
    if existing is None:
        state = PrinterState(printer_id=printer_id, paused=paused)
        session.add(state)
    else:
        existing.paused = paused
        session.add(existing)
    await session.commit()
    result = await session.get(PrinterState, printer_id)
    assert result is not None  # noqa: S101 — just created/updated above
    return result
