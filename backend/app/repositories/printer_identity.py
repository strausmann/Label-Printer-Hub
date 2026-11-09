"""Repository for the stored hardware identity of a printer (#231).

Every write is a compare-and-swap on the identity the caller read, so two probes racing on one
printer cannot overwrite each other's decision. All writes commit.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.printer_identity import PrinterIdentity


async def get(session: AsyncSession, printer_id: UUID) -> PrinterIdentity | None:
    """Return the identity row of a printer, or None if none was ever stored."""
    return await session.get(PrinterIdentity, printer_id)


async def insert(
    session: AsyncSession, printer_id: UUID, *, kind: str, value: str, now: datetime
) -> bool:
    """Store the first identity; False when a row exists already (a concurrent writer won)."""
    session.add(
        PrinterIdentity(
            printer_id=printer_id,
            hardware_id=value,
            hardware_id_kind=kind,
            hardware_id_seen_at=now,
        )
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return False
    return True


async def replace(
    session: AsyncSession,
    printer_id: UUID,
    *,
    expect_kind: str | None,
    expect_value: str | None,
    kind: str,
    value: str,
    now: datetime,
) -> bool:
    """Set the stored identity while it still equals ``expect_*``; False when it changed."""
    return await _cas(
        session,
        printer_id,
        expect_kind,
        expect_value,
        hardware_id=value,
        hardware_id_kind=kind,
        hardware_id_seen_at=now,
    )


async def touch_seen(
    session: AsyncSession, printer_id: UUID, *, kind: str, value: str, now: datetime
) -> bool:
    """Move ``hardware_id_seen_at`` while the stored identity is still ``(kind, value)``."""
    return await _cas(session, printer_id, kind, value, hardware_id_seen_at=now)


async def _cas(
    session: AsyncSession,
    printer_id: UUID,
    expect_kind: str | None,
    expect_value: str | None,
    **values: object,
) -> bool:
    kind_is = (
        PrinterIdentity.hardware_id_kind.is_(None)  # type: ignore[union-attr]
        if expect_kind is None
        else PrinterIdentity.hardware_id_kind == expect_kind
    )
    value_is = (
        PrinterIdentity.hardware_id.is_(None)  # type: ignore[union-attr]
        if expect_value is None
        else PrinterIdentity.hardware_id == expect_value
    )
    result = await session.execute(
        update(PrinterIdentity)
        .where(PrinterIdentity.printer_id == printer_id, kind_is, value_is)  # type: ignore[arg-type]
        .values(**values)
    )
    await session.commit()
    return bool(result.rowcount)  # type: ignore[attr-defined]
