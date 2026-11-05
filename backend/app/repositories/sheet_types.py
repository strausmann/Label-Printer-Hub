"""Queries for sheet types and their versions (spec 7.1)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.sheet import Sheet, SheetType, SheetTypeVersion


async def get_by_key(session: AsyncSession, key: str) -> SheetType | None:
    result = await session.execute(select(SheetType).where(col(SheetType.key) == key))
    return result.scalar_one_or_none()


async def get_by_prefix(session: AsyncSession, prefix: str) -> SheetType | None:
    result = await session.execute(select(SheetType).where(col(SheetType.prefix) == prefix))
    return result.scalar_one_or_none()


async def current_version(session: AsyncSession, type_id: UUID) -> SheetTypeVersion | None:
    result = await session.execute(
        select(SheetTypeVersion)
        .where(col(SheetTypeVersion.type_id) == type_id)
        .order_by(col(SheetTypeVersion.version).desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_version(session: AsyncSession, type_id: UUID, n: int) -> SheetTypeVersion | None:
    result = await session.execute(
        select(SheetTypeVersion).where(
            col(SheetTypeVersion.type_id) == type_id, col(SheetTypeVersion.version) == n
        )
    )
    return result.scalar_one_or_none()


async def versions_with_sheet_counts_many(
    session: AsyncSession, type_ids: list[UUID]
) -> dict[UUID, list[tuple[SheetTypeVersion, int]]]:
    """Versions of all given types, oldest first, with the sheets (any state) pinned to each.

    One query for any number of types.
    """
    grouped: dict[UUID, list[tuple[SheetTypeVersion, int]]] = {tid: [] for tid in type_ids}
    if not type_ids:
        return grouped
    counts = (
        select(col(Sheet.type_version_id).label("vid"), func.count().label("n"))
        .group_by(col(Sheet.type_version_id))
        .subquery()
    )
    result = await session.execute(
        select(SheetTypeVersion, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.vid == col(SheetTypeVersion.id))
        .where(col(SheetTypeVersion.type_id).in_(type_ids))
        .order_by(col(SheetTypeVersion.type_id), col(SheetTypeVersion.version))
    )
    for v, n in result.all():
        grouped[v.type_id].append((v, int(n)))
    return grouped


async def versions_with_sheet_counts(
    session: AsyncSession, type_id: UUID
) -> list[tuple[SheetTypeVersion, int]]:
    """Every version, oldest first, with the number of sheets (any state) pinned to it."""
    return (await versions_with_sheet_counts_many(session, [type_id]))[type_id]


async def count_sheets(session: AsyncSession, type_id: UUID) -> int:
    result = await session.execute(
        select(func.count()).select_from(Sheet).where(col(Sheet.type_id) == type_id)
    )
    return int(result.scalar_one())


async def list_with_current_version(
    session: AsyncSession, *, vendor: str | None, include_archived: bool
) -> list[tuple[SheetType, SheetTypeVersion]]:
    """Types paired with their newest version; free-text and size filters live in the service."""
    newest = (
        select(
            col(SheetTypeVersion.type_id).label("tid"),
            func.max(col(SheetTypeVersion.version)).label("v"),
        )
        .group_by(col(SheetTypeVersion.type_id))
        .subquery()
    )
    stmt = (
        select(SheetType, SheetTypeVersion)
        .join(newest, newest.c.tid == col(SheetType.id))
        .join(
            SheetTypeVersion,
            (col(SheetTypeVersion.type_id) == col(SheetType.id))
            & (col(SheetTypeVersion.version) == newest.c.v),
        )
        .order_by(col(SheetType.key))
    )
    if vendor is not None:
        stmt = stmt.where(func.lower(col(SheetType.vendor)) == vendor.lower())
    if not include_archived:
        stmt = stmt.where(col(SheetType.archived_at).is_(None))
    result = await session.execute(stmt)
    return [(t, v) for t, v in result.all()]
