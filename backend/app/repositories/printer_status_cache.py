"""Repository for PrinterStatusCache aggregate — last known ESC i S block."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.printer_status_cache import PrinterStatusCache


async def get(session: AsyncSession, printer_id: UUID) -> PrinterStatusCache | None:
    """Return the cached status for the given printer, or None if absent."""
    return await session.get(PrinterStatusCache, printer_id)


async def upsert(
    session: AsyncSession,
    printer_id: UUID,
    *,
    raw_block: bytes,
    parsed: dict[str, Any],
    captured_at: datetime,
) -> PrinterStatusCache:
    """Insert or replace the status cache row for a printer.

    Always results in exactly one row per printer_id.
    """
    existing = await session.get(PrinterStatusCache, printer_id)
    if existing is None:
        cache = PrinterStatusCache(
            printer_id=printer_id,
            raw_block=raw_block,
            parsed=parsed,
            captured_at=captured_at,
        )
        session.add(cache)
    else:
        existing.raw_block = raw_block
        existing.parsed = parsed
        existing.captured_at = captured_at
        session.add(existing)
    await session.commit()
    result = await session.get(PrinterStatusCache, printer_id)
    assert result is not None
    return result
