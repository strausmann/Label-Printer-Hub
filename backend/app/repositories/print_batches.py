"""CRUD für PrintBatch-Aggregat."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.print_batch import PrintBatch


async def create(session: AsyncSession, batch: PrintBatch) -> PrintBatch:
    session.add(batch)
    await session.commit()
    await session.refresh(batch)
    return batch


async def get(session: AsyncSession, batch_id: UUID) -> PrintBatch | None:
    return await session.get(PrintBatch, batch_id)


async def list_recent(session: AsyncSession, hours: int = 24) -> list[PrintBatch]:
    since = datetime.now(UTC) - timedelta(hours=hours)
    result = await session.execute(
        select(PrintBatch)
        .where(col(PrintBatch.created_at) >= since)
        .order_by(col(PrintBatch.created_at).desc())
    )
    return list(result.scalars())


async def prune_older_than(session: AsyncSession, hours: int = 24) -> int:
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    result = await session.execute(select(PrintBatch).where(col(PrintBatch.created_at) < cutoff))
    rows = list(result.scalars())
    for row in rows:
        await session.delete(row)
    await session.commit()
    return len(rows)
