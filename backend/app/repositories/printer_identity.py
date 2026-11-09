"""Repository for the stored hardware identity of a printer (#231).

Every write is a compare-and-swap on the identity the caller read, so two probes racing on one
printer cannot overwrite each other's decision. All writes commit.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, update
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
    """Set the stored identity while it still equals ``expect_*``; False when it changed.

    A new stored identity ends a mismatch: the device behind the address is the stored one.
    """
    return await _cas(
        session,
        printer_id,
        expect_kind,
        expect_value,
        hardware_id=value,
        hardware_id_kind=kind,
        hardware_id_seen_at=now,
        **_NO_MISMATCH,
    )


async def touch_seen(
    session: AsyncSession,
    printer_id: UUID,
    *,
    kind: str,
    value: str,
    now: datetime,
    clear_mismatch: bool = False,
) -> bool:
    """Move ``hardware_id_seen_at`` while the stored identity is still ``(kind, value)``.

    ``clear_mismatch`` also ends a mismatch, in the same write.
    """
    extra = _NO_MISMATCH if clear_mismatch else {}
    return await _cas(session, printer_id, kind, value, hardware_id_seen_at=now, **extra)


async def mark_mismatch(
    session: AsyncSession,
    printer_id: UUID,
    *,
    kind: str,
    value: str,
    observed_kind: str,
    observed_value: str,
    now: datetime,
) -> bool:
    """Record a differing device while the stored identity is still ``(kind, value)``.

    ``observed_*`` always follow the latest reading; ``mismatch_since`` is set once and kept for
    as long as the mismatch lasts. The stored identity is never touched.
    """
    return await _cas(
        session,
        printer_id,
        kind,
        value,
        observed_id=observed_value,
        observed_kind=observed_kind,
        mismatch_since=func.coalesce(PrinterIdentity.mismatch_since, now),
    )


async def adopt_observed(session: AsyncSession, printer_id: UUID, *, now: datetime) -> bool:
    """Make the observed device the stored one and end the mismatch; does NOT commit.

    One UPDATE that copies ``observed_*`` onto the stored columns inside the database, so no
    identity value passes through Python and a probe that races on the row cannot slip a
    different value in between. False when no mismatch is pending (nothing was written). The
    caller owns the transaction: it commits or rolls back this write with its other changes.
    """
    result = await session.execute(
        update(PrinterIdentity)
        .where(
            PrinterIdentity.printer_id == printer_id,  # type: ignore[arg-type]
            PrinterIdentity.mismatch_since.is_not(None),  # type: ignore[union-attr]
            PrinterIdentity.observed_id.is_not(None),  # type: ignore[union-attr]
            PrinterIdentity.observed_kind.is_not(None),  # type: ignore[union-attr]
        )
        .values(
            hardware_id=PrinterIdentity.observed_id,
            hardware_id_kind=PrinterIdentity.observed_kind,
            hardware_id_seen_at=now,
            **_NO_MISMATCH,
        )
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


_NO_MISMATCH: dict[str, object] = {
    "observed_id": None,
    "observed_kind": None,
    "mismatch_since": None,
}


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
