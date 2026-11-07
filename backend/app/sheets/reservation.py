"""Atomic cell reservation for sheet prints (spec 8, 10.1, 10.2).

``reserve`` plans and inserts the ``reserved`` rows in one write transaction: the sheet write
lock is its first statement, every view the plan decides on is read after it, and a plan that
differs from the one the client confirmed (``expected``) rolls the whole transaction back, so a
new sheet and its counter step vanish with it (acceptance 13). Events are published after the
commit (C17).

D15: cells are reserved at job creation, used on completion, unconfirmed when the outcome is
unknown. This module owns the first transition; the outcome handler owns the others.

``load_sheet_view`` and ``margin_id_in_flight`` are shared with the preview, which calls them
without the lock: there they are a best-effort read, here (inside ``write_transaction``) they
are the decision.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sheet import Sheet, SheetCell, SheetType, SheetTypeVersion
from app.printer_backends.ipp.attributes import Margins
from app.repositories import sheets as repo
from app.services.event_bus import EventBus
from app.sheets.errors import (
    CellsTakenError,
    InvalidPlacementsError,
    PlanChangedError,
    SheetNotFoundError,
    SheetTypeMismatchError,
)
from app.sheets.events import SheetTouched, publish_touched
from app.sheets.geometry import cell_count
from app.sheets.planner import MarginContext, PlacementIn, Plan, SheetView, plan
from app.sheets.sheet_service import create_sheet_locked
from app.sheets.text import log_value
from app.sheets.type_service import version_geometry, write_transaction

logger = logging.getLogger(__name__)

ID_CELL_PURPOSE = "Sheet ID"
HUB_SOURCE = "hub"
NEW_SHEET = "new"

__all__ = [
    "CellAssignment",
    "ExpectedPage",
    "ItemMeta",
    "NewSheetIn",
    "PlacementRequest",
    "ReservedPage",
    "load_sheet_view",
    "margin_id_in_flight",
    "release",
    "reserve",
]


@dataclass
class NewSheetIn:
    type_key: str
    version: int | None
    id_placement: Literal["cell", "margin", "manual"]


@dataclass
class PlacementRequest:
    """One placement: an existing sheet (``sheet_code``) or a new one (``new_sheet``)."""

    sheet_code: str | None
    new_sheet: NewSheetIn | None
    cells: Literal["first_free"] | list[int] = "first_free"
    skip: list[int] = field(default_factory=list)
    count: int | None = None


@dataclass
class ItemMeta:
    source: str
    purpose: str
    ref: str | None


@dataclass
class CellAssignment:
    cell: int
    item_index: int | None  # None for the ID cell
    source: str
    purpose: str
    ref: str | None


@dataclass
class ReservedPage:
    job_id: UUID
    sheet_id: UUID
    sheet_code: str
    type_version_id: UUID
    assignments: list[CellAssignment]
    id_cell: int | None
    margin_id: bool
    hw_margin_cells: list[int]


@dataclass
class ExpectedPage:
    """What a preview promised for one page; ``sheet`` is the code or ``"new"``."""

    sheet: str
    cells: list[int]
    id_cell: int | None


# ---------------------------------------------------------------------------- views


def _active_sheet_page_carries_margin_id(
    payloads: Sequence[dict[str, Any]], sheet_id: UUID
) -> bool:
    for payload in payloads:
        if payload.get("kind") != "sheet_page":
            continue
        detail = payload.get("detail")
        if not isinstance(detail, dict):
            continue
        if str(detail.get("sheet_id")) == str(sheet_id) and detail.get("margin_id"):
            return True
    return False


async def margin_id_in_flight(session: AsyncSession, sheet_id: UUID) -> bool:
    """Whether another job already carries (or is about to carry) the sheet's margin ID.

    True if a queued or printing ``sheet_page`` job of the sheet has ``detail.margin_id``, or
    if the sheet has ``reserved`` cells whose job has no ``jobs`` row yet: the page job is
    saved after the reservation commits, and in that window a second request must not draw the
    margin ID again (C26). The second rule is conservative: at worst the margin ID moves to a
    later job (OC-40).
    """
    if await repo.has_unattached_reservation(session, sheet_id):
        return True
    return _active_sheet_page_carries_margin_id(await repo.active_job_payloads(session), sheet_id)


async def _view_of(session: AsyncSession, sheet: Sheet) -> SheetView:
    sheet_type = await session.get(SheetType, sheet.type_id, populate_existing=True)
    version = await session.get(SheetTypeVersion, sheet.type_version_id, populate_existing=True)
    if sheet_type is None or version is None:  # foreign keys make this unreachable
        raise SheetNotFoundError()
    cells = await repo.cells_of(session, sheet.id)
    return SheetView(
        code=sheet.code,
        type_key=sheet_type.key,
        type_version_id=version.id,
        geometry=version_geometry(version),
        allow_qr=sheet_type.allow_qr,
        non_free={c.cell_no: c.state for c in cells},
        id_placement=sheet.id_placement,  # type: ignore[arg-type]
        id_printed=sheet.id_printed,
        has_hub_cell=any(c.source == HUB_SOURCE for c in cells),
        margin_id_in_flight=(
            sheet.id_placement == "margin" and await margin_id_in_flight(session, sheet.id)
        ),
        state=sheet.state,  # type: ignore[arg-type]
        sheet_id=sheet.id,
    )


async def load_sheet_view(session: AsyncSession, code: str) -> SheetView:
    """The planner's view of an existing sheet, read fresh from the database.

    The sheet's **pinned** version supplies the geometry (D14). Inside ``write_transaction``
    this is the view a reservation decides on; the preview calls it without the lock.
    """
    sheet = await repo.get_by_code(session, code)
    if sheet is None:
        raise SheetNotFoundError()
    return await _view_of(session, sheet)


async def _create_sheet_view(session: AsyncSession, new: NewSheetIn, actor: str) -> SheetView:
    """Create a sheet (counter step included) in the caller's transaction and view it."""
    sheet, sheet_type, version = await create_sheet_locked(
        session,
        type_key=new.type_key,
        version=new.version,
        id_placement=new.id_placement,
        marks={},
        note=None,
        actor=actor,
    )
    return SheetView(
        code=sheet.code,
        type_key=sheet_type.key,
        type_version_id=version.id,
        geometry=version_geometry(version),
        allow_qr=sheet_type.allow_qr,
        non_free={},
        id_placement=new.id_placement,
        id_printed=False,
        has_hub_cell=False,
        margin_id_in_flight=False,
        state="active",
        sheet_id=sheet.id,
    )


# ---------------------------------------------------------------------------- reserve


class _InsertConflictError(Exception):
    """The composite key refused an insert; carries what the attempt tried to take."""

    def __init__(self, cells: list[int], *, explicit: bool) -> None:
        super().__init__("cell insert conflict")
        self.cells = cells
        self.explicit = explicit


def _expected_of(pl: Plan, new_views: set[int]) -> list[ExpectedPage]:
    return [
        ExpectedPage(
            sheet=NEW_SHEET if id(p.sheet) in new_views else str(p.sheet.code),
            cells=list(p.item_cells),
            id_cell=p.id_cell,
        )
        for p in pl.pages
    ]


def _plan_detail(pages: Sequence[ExpectedPage]) -> list[dict[str, Any]]:
    return [{"sheet": p.sheet, "cells": p.cells, "id_cell": p.id_cell} for p in pages]


async def _resolve_views(
    session: AsyncSession,
    placements: Sequence[PlacementRequest],
    required_type_key: str | None,
    actor: str,
) -> tuple[list[PlacementIn], set[int]]:
    """Views for every placement. One sheet is one object (the planner's caller contract)."""
    by_code: dict[str, SheetView] = {}
    new_views: set[int] = set()
    out: list[PlacementIn] = []
    for p in placements:
        if (p.sheet_code is None) == (p.new_sheet is None):
            raise InvalidPlacementsError("sheet_or_new_sheet")
        if p.sheet_code is not None:
            view = by_code.get(p.sheet_code)
            if view is None:
                view = await load_sheet_view(session, p.sheet_code)
                by_code[p.sheet_code] = view
            if required_type_key is not None and view.type_key != required_type_key:
                raise SheetTypeMismatchError(required_type_key, view.type_key)
        else:
            assert p.new_sheet is not None
            if required_type_key is not None and p.new_sheet.type_key != required_type_key:
                raise SheetTypeMismatchError(required_type_key, p.new_sheet.type_key)
            view = await _create_sheet_view(session, p.new_sheet, actor)
            new_views.add(id(view))
        out.append(PlacementIn(sheet=view, cells=p.cells, skip=list(p.skip), count=p.count))
    return out, new_views


async def _attempt(
    session: AsyncSession,
    *,
    placements: Sequence[PlacementRequest],
    items: Sequence[ItemMeta],
    expected: Sequence[ExpectedPage] | None,
    hw_margins_hmm: Margins | None,
    margin: MarginContext,
    required_type_key: str | None,
    actor: str,
) -> tuple[list[ReservedPage], list[SheetTouched]]:
    explicit = any(isinstance(p.cells, list) for p in placements)
    async with write_transaction(session):
        views, new_views = await _resolve_views(session, placements, required_type_key, actor)
        pl = plan(views, len(items), hw_margins_hmm=hw_margins_hmm, margin=margin)
        fresh = _expected_of(pl, new_views)
        if expected is not None and list(expected) != fresh:
            raise PlanChangedError(_plan_detail(fresh))  # write_transaction rolls it all back

        now = datetime.now(UTC)
        rows: list[SheetCell] = []
        pages: list[ReservedPage] = []
        touched: dict[UUID, SheetTouched] = {}
        next_item = 0
        for page in pl.pages:
            sheet_id = page.sheet.sheet_id
            assert sheet_id is not None and page.sheet.code is not None
            job_id = uuid4()
            assignments: list[CellAssignment] = []
            if page.id_cell is not None:
                assignments.append(
                    CellAssignment(page.id_cell, None, HUB_SOURCE, ID_CELL_PURPOSE, None)
                )
            for cell in page.item_cells:
                meta = items[next_item]
                assignments.append(
                    CellAssignment(cell, next_item, meta.source, meta.purpose, meta.ref)
                )
                next_item += 1
            rows.extend(
                SheetCell(
                    sheet_id=sheet_id,
                    cell_no=a.cell,
                    state="reserved",  # D15
                    job_id=job_id,
                    source=a.source,
                    purpose=a.purpose,
                    ref=a.ref,
                    marked_by_hand=False,
                    updated_at=now,
                    updated_by=actor,
                )
                for a in assignments
            )
            pages.append(
                ReservedPage(
                    job_id=job_id,
                    sheet_id=sheet_id,
                    sheet_code=page.sheet.code,
                    type_version_id=page.sheet.type_version_id,
                    assignments=assignments,
                    id_cell=page.id_cell,
                    margin_id=page.margin_id,
                    hw_margin_cells=list(page.hw_margin_cells),
                )
            )
            t = touched.setdefault(
                sheet_id,
                SheetTouched(
                    code=page.sheet.code,
                    total=cell_count(page.sheet.geometry),
                    free=cell_count(page.sheet.geometry) - len(page.sheet.non_free),
                    changed=[],
                ),
            )
            t.changed.extend(a.cell for a in assignments)
        try:
            session.add_all(rows)
            await session.flush()  # the composite key is the last guard (spec 8)
        except IntegrityError:
            raise _InsertConflictError(sorted(r.cell_no for r in rows), explicit=explicit) from None
        for t in touched.values():
            t.free -= len(t.changed)
        await session.commit()
    return pages, list(touched.values())


async def reserve(
    session: AsyncSession,
    *,
    placements: Sequence[PlacementRequest],
    items: Sequence[ItemMeta],
    expected: Sequence[ExpectedPage] | None,
    hw_margins_hmm: Margins | None,
    margin: MarginContext,
    required_type_key: str | None,
    actor: str,
    bus: EventBus | None = None,
) -> list[ReservedPage]:
    """Plan and reserve in one write transaction; publish ``sheet.updated`` after the commit.

    ``margin`` is required on purpose: without a printer's margin context the planner skips
    the margin-too-small check, which a real print must never do (ruling T2-1). A preview
    without a printer calls ``plan`` directly.

    An ``IntegrityError`` on insert cannot happen between two lock holders; it is kept as a
    defence. Explicit cells answer ``cells_taken``; ``first_free`` re-plans once in a fresh
    transaction and then gives up with ``cells_taken``.
    """
    kwargs: dict[str, Any] = {
        "placements": placements,
        "items": items,
        "expected": expected,
        "hw_margins_hmm": hw_margins_hmm,
        "margin": margin,
        "required_type_key": required_type_key,
        "actor": actor,
    }
    try:
        pages, touched = await _attempt(session, **kwargs)
    except _InsertConflictError as conflict:
        if conflict.explicit:
            raise CellsTakenError(conflict.cells) from None
        try:
            pages, touched = await _attempt(session, **kwargs)
        except _InsertConflictError as again:
            raise CellsTakenError(again.cells) from None
    publish_touched(bus, touched)
    logger.info("reserved %d cells on %d pages", sum(len(p.assignments) for p in pages), len(pages))
    return pages


async def release(session: AsyncSession, job_id: UUID, *, bus: EventBus | None = None) -> list[int]:
    """Delete a job's ``reserved`` rows (queue submission failed after the commit).

    Cells the job already turned into used or unconfirmed are not touched.
    """
    touched: list[SheetTouched] = []
    freed: list[int] = []
    async with write_transaction(session):
        rows = await repo.reserved_cells_of_job(session, job_id)
        by_sheet: dict[UUID, list[int]] = {}
        for row in rows:
            by_sheet.setdefault(row.sheet_id, []).append(row.cell_no)
            freed.append(row.cell_no)
            await session.delete(row)  # D15: reserved -> free
        await session.flush()
        for sheet_id, cells in by_sheet.items():
            sheet = await session.get(Sheet, sheet_id, populate_existing=True)
            version = (
                None
                if sheet is None
                else await session.get(SheetTypeVersion, sheet.type_version_id)
            )
            if sheet is None or version is None:  # foreign keys make this unreachable
                continue
            total = cell_count(version_geometry(version))
            remaining = len(await repo.cells_of(session, sheet_id))
            touched.append(
                SheetTouched(
                    code=sheet.code,
                    total=total,
                    free=total - remaining,
                    changed=cells,
                    state=sheet.state,
                )
            )
        await session.commit()
    publish_touched(bus, touched)
    if freed:
        logger.info("released %d reserved cells of job %s", len(freed), log_value(str(job_id)))
    return sorted(freed)
