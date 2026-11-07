"""Queries for physical sheets and their non-free cells (spec 7.1).

Reads that a write decides on run inside the writer's transaction, after the write lock. They
use ``populate_existing`` so a long-lived session never decides on a row it loaded before
another session changed it.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, case, exists, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.job import PAGE_SHEET_EXPR, Job, JobState, json_at
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


async def sheets_by_codes(session: AsyncSession, codes: Sequence[str]) -> dict[str, Sheet]:
    """The sheets with these codes, fresh; a code that does not exist is not in the answer."""
    result = await session.execute(
        select(Sheet).where(col(Sheet.code).in_(list(codes))).execution_options(**_FRESH)
    )
    return {sheet.code: sheet for sheet in result.scalars().all()}


async def types_by_ids(session: AsyncSession, ids: Sequence[UUID]) -> dict[UUID, SheetType]:
    result = await session.execute(
        select(SheetType).where(col(SheetType.id).in_(list(ids))).execution_options(**_FRESH)
    )
    return {t.id: t for t in result.scalars().all()}


async def versions_by_ids(
    session: AsyncSession, ids: Sequence[UUID]
) -> dict[UUID, SheetTypeVersion]:
    result = await session.execute(
        select(SheetTypeVersion)
        .where(col(SheetTypeVersion.id).in_(list(ids)))
        .execution_options(**_FRESH)
    )
    return {v.id: v for v in result.scalars().all()}


async def cells_of_many(
    session: AsyncSession, sheet_ids: Sequence[UUID]
) -> dict[UUID, list[SheetCell]]:
    """The non-free cells of each sheet, by cell number (one statement for all of them)."""
    out: dict[UUID, list[SheetCell]] = {sid: [] for sid in sheet_ids}
    result = await session.execute(
        select(SheetCell)
        .where(col(SheetCell.sheet_id).in_(list(sheet_ids)))
        .order_by(col(SheetCell.sheet_id), col(SheetCell.cell_no))
        .execution_options(**_FRESH)
    )
    for cell in result.scalars().all():
        out[cell.sheet_id].append(cell)
    return out


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


async def unattached_reservation_sheets(
    session: AsyncSession, sheet_ids: Sequence[UUID]
) -> set[UUID]:
    """Which of the sheets have a ``reserved`` cell whose job has no ``jobs`` row yet."""
    result = await session.execute(
        select(col(SheetCell.sheet_id))
        .where(
            col(SheetCell.sheet_id).in_(list(sheet_ids)),
            col(SheetCell.state) == "reserved",
            ~exists().where(col(Job.id) == col(SheetCell.job_id)),
        )
        .distinct()
        .execution_options(**_FRESH)
    )
    return set(result.scalars().all())


_CARRIED_KEYS = ("margin_id", "feed_mark")


def _carried(key: str) -> tuple[ColumnElement[Any], ColumnElement[Any]]:
    path = f"$.detail.{key}"
    return (
        literal_column(json_at(path)),
        literal_column(f"CASE WHEN json_valid(payload) THEN json_type(payload, '{path}') END"),
    )


async def _carrier_rows(session: AsyncSession, *where: ColumnElement[bool]) -> list[dict[str, Any]]:
    """What the jobs matching ``where`` carry, without their payloads.

    Only the sheet id and the two ``detail`` entries the in-flight rules look at are selected,
    each small (a margin ID or a feed mark); a payload holds every cell's label and can be
    megabytes. Rows come back shaped like the part of a payload ``_active_sheet_page_carries``
    reads, so the rule stays one function.
    """
    columns: list[ColumnElement[Any]] = [literal_column(PAGE_SHEET_EXPR)]
    for key in _CARRIED_KEYS:
        columns.extend(_carried(key))
    result = await session.execute(
        select(*columns)
        .select_from(Job)
        .where(literal_column(json_at("$.kind")) == "sheet_page", *where)
        .execution_options(**_FRESH)
    )
    out: list[dict[str, Any]] = []
    for sheet, margin, margin_type, mark, mark_type in result.all():
        detail: dict[str, Any] = {"sheet_id": sheet}
        for key, raw, kind in (("margin_id", margin, margin_type), ("feed_mark", mark, mark_type)):
            # json_extract answers an object or an array as JSON text, a scalar as a value.
            detail[key] = json.loads(raw) if kind in ("object", "array") and raw else raw
        out.append({"kind": "sheet_page", "detail": detail})
    return out


def _of_sheets(sheet_ids: Sequence[UUID]) -> ColumnElement[bool]:
    return literal_column(PAGE_SHEET_EXPR).in_([str(i) for i in sheet_ids])


async def active_job_payloads(
    session: AsyncSession, sheet_ids: Sequence[UUID]
) -> list[dict[str, Any]]:
    """What the queued or printing page jobs of these sheets carry.

    Scoped to the sheets by the index on the sheet expression, so the cost does not depend on
    how many unrelated jobs are queued (R11-1).
    """
    return await _carrier_rows(
        session,
        _of_sheets(sheet_ids),
        col(Job.state).in_((JobState.QUEUED.value, JobState.PRINTING.value)),
    )


async def unconfirmed_job_payloads(
    session: AsyncSession, sheet_ids: Sequence[UUID]
) -> list[dict[str, Any]]:
    """What the jobs that still own an ``unconfirmed`` cell of these sheets carry.

    Such a job may have printed its page, so what it carried (margin ID, feed mark) counts as
    maybe printed until a human resolves the cells (spec 10.2a, F3-1). Retention spares these
    jobs, so their rows exist; a cell whose row is gone contributes nothing.
    """
    return await _carrier_rows(
        session,
        _of_sheets(sheet_ids),
        col(Job.id).in_(
            select(col(SheetCell.job_id)).where(
                col(SheetCell.sheet_id).in_(list(sheet_ids)),
                col(SheetCell.state) == "unconfirmed",
                col(SheetCell.job_id).is_not(None),
            )
        ),
    )


async def unsettled_job_payloads(
    session: AsyncSession, sheet_ids: Sequence[UUID]
) -> list[dict[str, Any]]:
    """What the jobs that are over but still own a ``reserved`` cell of these sheets carry.

    A page job's end is committed first and its cells are settled by the outcome handler in a
    second transaction. Between the two the job is no longer queued or printing and its cells
    are not yet ``used`` or ``unconfirmed``, so neither of the other rules sees what it carried
    (R10-4). A job that ended cleanly without printing counts too until its cells are freed: at
    worst the margin ID moves to a later job.
    """
    return await _carrier_rows(
        session,
        _of_sheets(sheet_ids),
        col(Job.state).not_in((JobState.QUEUED.value, JobState.PRINTING.value)),
        col(Job.id).in_(
            select(col(SheetCell.job_id)).where(
                col(SheetCell.sheet_id).in_(list(sheet_ids)),
                col(SheetCell.state) == "reserved",
                col(SheetCell.job_id).is_not(None),
            )
        ),
    )


async def reserved_cells_of_job(session: AsyncSession, job_id: UUID) -> list[SheetCell]:
    result = await session.execute(
        select(SheetCell)
        .where(col(SheetCell.job_id) == job_id, col(SheetCell.state) == "reserved")
        .order_by(col(SheetCell.sheet_id), col(SheetCell.cell_no))
        .execution_options(**_FRESH)
    )
    return list(result.scalars().all())


async def unconfirmed_cells_of_job(session: AsyncSession, job_id: UUID) -> list[int]:
    """The numbers of the ``unconfirmed`` cells that still point at the job (OC-42)."""
    result = await session.execute(
        select(col(SheetCell.cell_no))
        .where(col(SheetCell.job_id) == job_id, col(SheetCell.state) == "unconfirmed")
        .order_by(col(SheetCell.cell_no))
        .execution_options(**_FRESH)
    )
    return list(result.scalars().all())


async def all_reserved_cells(session: AsyncSession) -> list[SheetCell]:
    """Every ``reserved`` cell of every sheet (the startup sweep)."""
    result = await session.execute(
        select(SheetCell)
        .where(col(SheetCell.state) == "reserved")
        .order_by(col(SheetCell.sheet_id), col(SheetCell.cell_no))
        .execution_options(**_FRESH)
    )
    return list(result.scalars().all())


_JOB_CHUNK = 500  # well below SQLite's bound-variable limit


async def jobs_by_id(session: AsyncSession, job_ids: Sequence[UUID]) -> dict[UUID, Job]:
    """The ``jobs`` rows that exist among ``job_ids`` (a missing id has no entry)."""
    found: dict[UUID, Job] = {}
    ids = list(job_ids)
    for start in range(0, len(ids), _JOB_CHUNK):
        result = await session.execute(
            select(Job)
            .where(col(Job.id).in_(ids[start : start + _JOB_CHUNK]))
            .execution_options(**_FRESH)
        )
        found.update({j.id: j for j in result.scalars().all()})
    return found


def _carried_sheet(job: Job | None, key: str) -> str | None:
    if job is None or not isinstance(job.payload, dict):
        return None
    if job.payload.get("kind") != "sheet_page":
        return None
    detail = job.payload.get("detail")
    if not isinstance(detail, dict) or not detail.get(key):
        return None
    return str(detail.get("sheet_id"))


def margin_id_sheet(job: Job | None) -> str | None:
    """The sheet id a ``sheet_page`` job's margin ID belongs to; ``None``: it carries none.

    A job row already deleted by retention (``job is None``) counts as not carrying one.
    """
    return _carried_sheet(job, "margin_id")


def feed_mark_sheet(job: Job | None) -> str | None:
    """The sheet id a ``sheet_page`` job's feed-direction mark belongs to; ``None``: none."""
    return _carried_sheet(job, "feed_mark")
