"""Queries for physical sheets and their non-free cells (spec 7.1).

Reads that a write decides on run inside the writer's transaction, after the write lock. They
use ``populate_existing`` so a long-lived session never decides on a row it loaded before
another session changed it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, case, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.job import Job, JobState
from app.models.sheet import Sheet, SheetCell, SheetIdCounter, SheetType, SheetTypeVersion

_FRESH = {"populate_existing": True}


async def get_type_by_key(session: AsyncSession, key: str) -> SheetType | None:
    result = await session.execute(
        select(SheetType).where(col(SheetType.key) == key).execution_options(**_FRESH)
    )
    return result.scalar_one_or_none()


async def get_by_code(session: AsyncSession, code: str) -> Sheet | None:
    result = await session.execute(
        select(Sheet).where(col(Sheet.code) == code).execution_options(**_FRESH)
    )
    return result.scalar_one_or_none()


async def cells_of(session: AsyncSession, sheet_id: UUID) -> list[SheetCell]:
    result = await session.execute(
        select(SheetCell)
        .where(col(SheetCell.sheet_id) == sheet_id)
        .order_by(col(SheetCell.cell_no))
        .execution_options(**_FRESH)
    )
    return list(result.scalars().all())


async def counter(session: AsyncSession, prefix: str) -> SheetIdCounter | None:
    return await session.get(SheetIdCounter, prefix, populate_existing=True)


def _count_state(state: str) -> ColumnElement[int]:
    return func.coalesce(func.sum(case((col(SheetCell.state) == state, 1), else_=0)), 0)


async def list_with_counts(
    session: AsyncSession, *, type_id: UUID | None, sheet_state: str | None
) -> Sequence[tuple[Sheet, SheetType, SheetTypeVersion, int, int, int]]:
    """Sheets with type, pinned version and the number of used/reserved/unconfirmed cells."""
    counts = (
        select(
            col(SheetCell.sheet_id).label("sid"),
            _count_state("used").label("used"),
            _count_state("reserved").label("reserved"),
            _count_state("unconfirmed").label("unconfirmed"),
        )
        .group_by(col(SheetCell.sheet_id))
        .subquery()
    )
    stmt = (
        select(
            Sheet,
            SheetType,
            SheetTypeVersion,
            func.coalesce(counts.c.used, 0),
            func.coalesce(counts.c.reserved, 0),
            func.coalesce(counts.c.unconfirmed, 0),
        )
        .join(SheetType, col(SheetType.id) == col(Sheet.type_id))
        .join(SheetTypeVersion, col(SheetTypeVersion.id) == col(Sheet.type_version_id))
        .outerjoin(counts, counts.c.sid == col(Sheet.id))
    )
    if type_id is not None:
        stmt = stmt.where(col(Sheet.type_id) == type_id)
    if sheet_state is not None:
        stmt = stmt.where(col(Sheet.state) == sheet_state)
    result = await session.execute(stmt)
    return [(row[0], row[1], row[2], int(row[3]), int(row[4]), int(row[5])) for row in result.all()]


async def cells_by_ref(
    session: AsyncSession, *, source: str, ref: str
) -> Sequence[tuple[str, SheetCell]]:
    """Cells of an integration item with their sheet code, newest first."""
    result = await session.execute(
        select(col(Sheet.code), SheetCell)
        .join(Sheet, col(Sheet.id) == col(SheetCell.sheet_id))
        .where(col(SheetCell.source) == source, col(SheetCell.ref) == ref)
        .order_by(col(SheetCell.updated_at).desc(), col(Sheet.code), col(SheetCell.cell_no))
    )
    return [(code, cell) for code, cell in result.all()]


async def has_hub_cell(session: AsyncSession, sheet_id: UUID) -> bool:
    """Whether the sheet holds an ID label cell of the hub in any state (OC-40)."""
    result = await session.execute(
        select(
            exists().where(col(SheetCell.sheet_id) == sheet_id, col(SheetCell.source) == "hub")
        ).execution_options(**_FRESH)
    )
    return bool(result.scalar_one())


async def has_unattached_reservation(session: AsyncSession, sheet_id: UUID) -> bool:
    """Whether a ``reserved`` cell of the sheet points at a job that has no ``jobs`` row yet.

    That is the window between the reservation commit and the page job being saved (C26).
    """
    result = await session.execute(
        select(
            exists().where(
                col(SheetCell.sheet_id) == sheet_id,
                col(SheetCell.state) == "reserved",
                ~exists().where(col(Job.id) == col(SheetCell.job_id)),
            )
        ).execution_options(**_FRESH)
    )
    return bool(result.scalar_one())


async def active_job_payloads(session: AsyncSession) -> list[dict[str, Any]]:
    """Payloads of the jobs that are still queued or printing."""
    result = await session.execute(
        select(col(Job.payload))
        .where(col(Job.state).in_((JobState.QUEUED.value, JobState.PRINTING.value)))
        .execution_options(**_FRESH)
    )
    return [p for p in result.scalars().all() if isinstance(p, dict)]


async def reserved_cells_of_job(session: AsyncSession, job_id: UUID) -> list[SheetCell]:
    result = await session.execute(
        select(SheetCell)
        .where(col(SheetCell.job_id) == job_id, col(SheetCell.state) == "reserved")
        .order_by(col(SheetCell.sheet_id), col(SheetCell.cell_no))
        .execution_options(**_FRESH)
    )
    return list(result.scalars().all())
