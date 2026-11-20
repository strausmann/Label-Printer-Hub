# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Repository for PrinterStatusCache aggregate — last known ESC i S block."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
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
            updated_at=datetime.now(UTC),
        )
        session.add(cache)
    else:
        existing.raw_block = raw_block
        existing.parsed = parsed
        existing.captured_at = captured_at
        existing.updated_at = datetime.now(UTC)
        session.add(existing)
    await session.commit()
    result = await session.get(PrinterStatusCache, printer_id)
    assert result is not None
    return result


# What a producer stores in ``last_error`` today: an exception class name, nothing else.
_ERROR_CLASS_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


async def drop_free_text_errors(session: AsyncSession) -> int:
    """Remove a ``last_error`` that is not a bare class name from every cache row.

    Hub 1.7.0 stored ``str(exc)`` there, for a tape printer ``cannot reach <host>:9100``,
    and the status route hands the field to every key. Since 1.7.x the producers store the
    class name only; this clears what an older hub left behind so no address survives the
    upgrade. The key is dropped instead of rewritten (the smaller change): the next probe of
    the printer writes the class name. Returns the number of rows changed; the caller commits.
    """
    changed = 0
    rows = (await session.execute(select(PrinterStatusCache))).scalars().all()
    for row in rows:
        parsed = row.parsed
        if not isinstance(parsed, dict):
            continue
        value = parsed.get("last_error")
        if value is None or (isinstance(value, str) and _ERROR_CLASS_NAME.fullmatch(value)):
            continue
        row.parsed = {k: v for k, v in parsed.items() if k != "last_error"}
        session.add(row)
        changed += 1
    return changed
