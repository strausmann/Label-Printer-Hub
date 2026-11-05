"""Physical sheets: create, next code, mark, unmark, resolve, discard, list, lookups (spec 8, 10).

Every write runs in ``type_service.write_transaction``: the sheet write lock is its first
statement, and every read the write decides on (free cells, sheet state, the counter) happens
after it. Two writers on the same sheet are therefore serialised and the second one decides on
what the first committed (Review Focus 3, 4). Events are published after the commit.

A free cell has no row. Cell numbers run from 1 to the cell count of the sheet's **pinned**
version (D14), never of the type's current one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sheet import Sheet, SheetCell, SheetIdCounter, SheetType, SheetTypeVersion
from app.repositories import sheet_types as types_repo
from app.repositories import sheets as repo
from app.services.event_bus import EventBus
from app.sheets.errors import (
    CellOutOfRangeError,
    CellsNotMarkedByHandError,
    CellsNotUnconfirmedError,
    CellsTakenError,
    InvalidFieldError,
    SheetBusyError,
    SheetDiscardedError,
    SheetNotFoundError,
    SheetTypeArchivedError,
    SheetTypeNotFoundError,
)
from app.sheets.events import publish_sheet_updated
from app.sheets.text import sanitise_text
from app.sheets.type_service import write_transaction

logger = logging.getLogger(__name__)

PURPOSE_MAX = 120
NOTE_MAX = 500
DEFAULT_HAND_PURPOSE = "marked by hand"
_ID_PLACEMENTS = ("margin", "manual")  # Plan 3 adds "cell"
_STATE_FILTERS = ("active", "full", "discarded", "all")


@dataclass
class MarkedCell:
    cell: int
    purpose: str | None = None


@dataclass
class SheetDetail:
    sheet: Sheet
    type: SheetType
    version: SheetTypeVersion
    cells: list[SheetCell]
    total: int
    used: int
    reserved: int
    unconfirmed: int

    @property
    def free(self) -> int:
        return self.total - self.used - self.reserved - self.unconfirmed

    @property
    def state(self) -> str:
        return self.sheet.state


@dataclass
class SheetListRow:
    sheet: Sheet
    type: SheetType
    version: SheetTypeVersion
    total: int
    used: int
    reserved: int
    unconfirmed: int

    @property
    def free(self) -> int:
        return self.total - self.used - self.reserved - self.unconfirmed


@dataclass
class CellHit:
    code: str
    cell: int
    state: str
    purpose: str | None
    updated_at: datetime


def _now() -> datetime:
    return datetime.now(UTC)


def _clean(field: str, value: str, max_len: int, *, multiline: bool = False) -> str:
    try:
        return sanitise_text(value, max_len=max_len, multiline=multiline)
    except ValueError:
        raise InvalidFieldError(field, "too long") from None


def _clean_marks(cells: list[MarkedCell]) -> dict[int, str]:
    """Cell number → purpose; duplicates collapse onto the first, empty means the default."""
    out: dict[int, str] = {}
    for mark in cells:
        purpose = "" if mark.purpose is None else _clean("purpose", mark.purpose, PURPOSE_MAX)
        out.setdefault(mark.cell, purpose or DEFAULT_HAND_PURPOSE)
    return out


def format_code(prefix: str, value: int) -> str:
    """``L4736-0002``; four digits, a counter above 9999 grows to five (spec 7.1)."""
    return f"{prefix}-{value:04d}"


def _total(version: SheetTypeVersion) -> int:
    return version.cols * version.rows


def _check_range(numbers: list[int], total: int) -> None:
    bad = sorted({n for n in numbers if n < 1 or n > total})
    if bad:
        raise CellOutOfRangeError(bad, total)


async def allocate_code(session: AsyncSession, prefix: str) -> str:
    """Read-increment the prefix counter in the caller's transaction (no lock, no commit).

    The caller holds ``acquire_sheet_write_lock``. Counters never decrease and never reset.
    """
    row = await repo.counter(session, prefix)
    if row is None:
        value = 1
        session.add(SheetIdCounter(prefix=prefix, next_value=2))
    else:
        value = row.next_value
        row.next_value = value + 1
    await session.flush()
    return format_code(prefix, value)


async def peek_next_code(session: AsyncSession, type_key: str) -> str:
    """The code the next sheet would probably get; a hint, not a reservation (spec 10.1)."""
    t = await types_repo.get_by_key(session, type_key)
    if t is None:
        raise SheetTypeNotFoundError()
    row = await repo.counter(session, t.prefix)
    return format_code(t.prefix, 1 if row is None else row.next_value)


async def _detail(session: AsyncSession, sheet: Sheet) -> SheetDetail:
    t = await session.get(SheetType, sheet.type_id)
    v = await session.get(SheetTypeVersion, sheet.type_version_id)
    if t is None or v is None:  # foreign keys make this unreachable
        raise SheetNotFoundError()
    cells = await repo.cells_of(session, sheet.id)
    counts = {"used": 0, "reserved": 0, "unconfirmed": 0}
    for c in cells:
        counts[c.state] += 1
    return SheetDetail(
        sheet=sheet,
        type=t,
        version=v,
        cells=cells,
        total=_total(v),
        used=counts["used"],
        reserved=counts["reserved"],
        unconfirmed=counts["unconfirmed"],
    )


async def _sheet(session: AsyncSession, code: str) -> Sheet:
    sheet = await repo.get_by_code(session, code)
    if sheet is None:
        raise SheetNotFoundError()
    return sheet


async def _writable(session: AsyncSession, code: str) -> SheetDetail:
    sheet = await _sheet(session, code)
    if sheet.state == "discarded":
        raise SheetDiscardedError()
    return await _detail(session, sheet)


def _publish(bus: EventBus | None, detail: SheetDetail, changed: list[int]) -> None:
    publish_sheet_updated(
        bus,
        code=detail.sheet.code,
        free=detail.free,
        total=detail.total,
        changed=changed,
        state=detail.sheet.state,
    )


async def get_sheet(session: AsyncSession, code: str) -> SheetDetail:
    """The sheet with all non-free cells; a discarded sheet is returned, not refused."""
    return await _detail(session, await _sheet(session, code))


async def create_sheet(
    session: AsyncSession,
    *,
    type_key: str,
    version: int | None,
    id_placement: Literal["margin", "manual"],
    used_cells: list[MarkedCell],
    note: str | None,
    actor: str,
    bus: EventBus | None = None,
) -> Sheet:
    """Create a sheet pinned to a version, with the cells already used marked by hand."""
    if id_placement not in _ID_PLACEMENTS:
        raise InvalidFieldError("id_placement", "not supported")
    marks = _clean_marks(used_cells)
    clean_note = None if note is None else _clean("note", note, NOTE_MAX, multiline=True) or None
    async with write_transaction(session):
        t = await repo.get_type_by_key(session, type_key)
        if t is None:
            raise SheetTypeNotFoundError()
        if t.archived_at is not None:
            raise SheetTypeArchivedError()
        v = (
            await types_repo.current_version(session, t.id)
            if version is None
            else await types_repo.get_version(session, t.id, version)
        )
        if v is None:
            raise SheetTypeNotFoundError()
        _check_range(list(marks), _total(v))
        sheet = Sheet(
            code=await allocate_code(session, t.prefix),
            type_id=t.id,
            type_version_id=v.id,
            id_placement=id_placement,
            note=clean_note,
            created_by=actor,
            last_used_at=_now() if marks else None,
        )
        session.add(sheet)
        await session.flush()
        _add_hand_marks(session, sheet.id, marks, actor)
        await session.flush()
        detail = await _detail(session, sheet)
        await session.commit()
    logger.info("sheet %s created by %s (%d cells used)", sheet.code, actor, len(marks))
    _publish(bus, detail, sorted(marks))
    return sheet


def _add_hand_marks(
    session: AsyncSession, sheet_id: UUID, marks: dict[int, str], actor: str
) -> None:
    now = _now()
    for n, purpose in sorted(marks.items()):
        session.add(
            SheetCell(
                sheet_id=sheet_id,
                cell_no=n,
                state="used",
                source="manual",
                purpose=purpose,
                marked_by_hand=True,
                updated_at=now,
                updated_by=actor,
            )
        )


async def mark_cells(
    session: AsyncSession,
    code: str,
    cells: list[MarkedCell],
    *,
    actor: str,
    bus: EventBus | None = None,
) -> SheetDetail:
    """Mark free cells as used by hand; any non-free cell refuses the whole request."""
    marks = _clean_marks(cells)
    if not marks:  # nothing to mark: no lock, no commit, no event
        return await _writable(session, code)
    async with write_transaction(session):
        before = await _writable(session, code)
        _check_range(list(marks), before.total)
        taken = sorted(c.cell_no for c in before.cells if c.cell_no in marks)
        if taken:
            raise CellsTakenError(taken)
        _add_hand_marks(session, before.sheet.id, marks, actor)
        before.sheet.last_used_at = _now()
        await session.flush()
        detail = await _detail(session, before.sheet)
        await session.commit()
    _publish(bus, detail, sorted(marks))
    return detail


async def unmark_cells(
    session: AsyncSession,
    code: str,
    cells: list[int],
    *,
    actor: str,
    bus: EventBus | None = None,
) -> SheetDetail:
    """Free cells that were marked by hand; a cell a job used carries a label and stays."""
    wanted = sorted(set(cells))
    if not wanted:  # nothing to free: no lock, no commit, no event
        return await _writable(session, code)
    async with write_transaction(session):
        before = await _writable(session, code)
        _check_range(wanted, before.total)
        rows = {c.cell_no: c for c in before.cells}
        bad = [
            n
            for n in wanted
            if n not in rows or rows[n].state != "used" or not rows[n].marked_by_hand
        ]
        if bad:
            raise CellsNotMarkedByHandError(bad)
        for n in wanted:
            await session.delete(rows[n])
        await session.flush()
        detail = await _detail(session, before.sheet)
        await session.commit()
    logger.info("sheet %s: %d cells un-marked by %s", code, len(wanted), actor)
    _publish(bus, detail, wanted)
    return detail


async def resolve_cells(
    session: AsyncSession,
    code: str,
    cells: list[int],
    outcome: Literal["printed", "not_printed"],
    *,
    actor: str,
    bus: EventBus | None = None,
) -> SheetDetail:
    """Settle unconfirmed cells (OC-9): ``printed`` keeps them as used, ``not_printed`` frees."""
    if outcome not in ("printed", "not_printed"):
        raise InvalidFieldError("outcome", "must be printed or not_printed")
    wanted = sorted(set(cells))
    if not wanted:  # nothing to settle: no lock, no commit, no event
        return await _writable(session, code)
    async with write_transaction(session):
        before = await _writable(session, code)
        _check_range(wanted, before.total)
        rows = {c.cell_no: c for c in before.cells}
        bad = [n for n in wanted if n not in rows or rows[n].state != "unconfirmed"]
        if bad:
            raise CellsNotUnconfirmedError(bad)
        now = _now()
        for n in wanted:
            row = rows[n]
            if outcome == "not_printed":
                await session.delete(row)
                continue
            before.sheet.last_used_at = now
            row.state = "used"  # source, purpose, ref and job id stay
            row.updated_at = now
            row.updated_by = actor
            if row.source == "hub":  # the ID label is on the sheet now (spec 7.1)
                before.sheet.id_printed = True
        await session.flush()
        detail = await _detail(session, before.sheet)
        await session.commit()
    logger.info("sheet %s: %d cells resolved as %s by %s", code, len(wanted), outcome, actor)
    _publish(bus, detail, wanted)
    return detail


async def discard_sheet(
    session: AsyncSession, code: str, *, actor: str, bus: EventBus | None = None
) -> Sheet:
    """Retire a sheet; its code is never issued again. Refused while a job holds cells."""
    async with write_transaction(session):
        sheet = await _sheet(session, code)
        if sheet.state == "discarded":  # idempotent: the first discard stays on record
            await session.commit()
            return sheet
        detail = await _detail(session, sheet)
        if detail.reserved:
            raise SheetBusyError()
        sheet.state = "discarded"
        sheet.discarded_at = _now()
        sheet.discarded_by = actor
        await session.flush()
        await session.commit()
    logger.info("sheet %s discarded by %s", code, actor)
    _publish(bus, detail, [])
    return sheet


async def list_sheets(
    session: AsyncSession,
    *,
    type_key: str | None = None,
    free_at_least: int | None = None,
    state: Literal["active", "full", "discarded", "all"] = "active",
    q: str | None = None,
) -> list[SheetListRow]:
    """Sheets ordered OC-34: those with ``free >= free_at_least`` first, then most free, code."""
    if state not in _STATE_FILTERS:
        raise InvalidFieldError("state", "unknown filter")
    type_id: UUID | None = None
    if type_key is not None:
        t = await types_repo.get_by_key(session, type_key)
        if t is None:
            raise SheetTypeNotFoundError()
        type_id = t.id
    sheet_state = {"active": "active", "full": "active", "discarded": "discarded"}.get(state)
    raw = await repo.list_with_counts(session, type_id=type_id, sheet_state=sheet_state)
    rows = [
        SheetListRow(sheet=s, type=t, version=v, total=_total(v), used=u, reserved=r, unconfirmed=c)
        for s, t, v, u, r, c in raw
    ]
    if state == "full":
        rows = [r for r in rows if r.free == 0]
    if q:
        needle = q.lower()
        rows = [r for r in rows if needle in r.sheet.code.lower()]
    want = free_at_least or 0

    def order(row: SheetListRow) -> tuple[int, int, str]:
        return (0 if row.free >= want else 1, -row.free, row.sheet.code)

    return sorted(rows, key=order)


async def find_cells(session: AsyncSession, *, source: str, ref: str) -> list[CellHit]:
    """Where an integration item was printed before (spec 10.3), newest first."""
    return [
        CellHit(
            code=code, cell=c.cell_no, state=c.state, purpose=c.purpose, updated_at=c.updated_at
        )
        for code, c in await repo.cells_by_ref(session, source=source, ref=ref)
    ]
