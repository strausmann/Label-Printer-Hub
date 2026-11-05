"""Sheet service: create, next code, mark, unmark, resolve, discard, list, lookups (Task 6)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from app.models.sheet import Sheet, SheetCell, SheetIdCounter
from app.services.event_bus import BusEvent
from app.sheets import sheet_service as ss
from app.sheets import type_service as ts
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
from app.sheets.geometry import Geometry
from app.sheets.sheet_service import MarkedCell
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# 4 x 12 = 48 labels (L4736REV-like).
G48 = Geometry(
    page_size="A4",
    page_w=21000,
    page_h=29700,
    label_w=4570,
    label_h=2120,
    cols=4,
    rows=12,
    pitch_x=4850,
    pitch_y=2120,
    margin_top=2150,
    margin_left=840,
    corner_radius=None,
    shape="rectangle",
)
# 5 x 12 = 60 labels, used as version 2.
G60 = replace(G48, label_w=3600, cols=5, pitch_x=4000, margin_left=500)


def _fields(key: str = "avery-l4736rev", prefix: str = "L4736") -> ts.TypeFields:
    return ts.TypeFields(
        key=key,
        prefix=prefix,
        vendor="Avery",
        product_codes=["L4736REV-25"],
        description="Removable labels",
        allow_qr=None,
    )


@pytest_asyncio.fixture
async def session(async_session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[Any]:
    async with async_session_factory() as s:
        yield s


@pytest_asyncio.fixture
async def l4736(session: AsyncSession) -> str:
    await ts.create_type(session, _fields(), G48, actor="tester")
    return "avery-l4736rev"


class FakeBus:
    """Records what the service publishes; same surface as EventBus."""

    def __init__(self) -> None:
        self.events: list[tuple[str, BusEvent]] = []
        self._n = 0

    def next_event_id(self, channel: str) -> int:
        self._n += 1
        return self._n

    def publish(self, channel: str, event: BusEvent) -> None:
        self.events.append((channel, event))


async def _create(session: AsyncSession, key: str = "avery-l4736rev", **kw: Any) -> Sheet:
    args: dict[str, Any] = {
        "type_key": key,
        "version": None,
        "id_placement": "manual",
        "used_cells": [],
        "note": None,
        "actor": "tester",
    }
    args.update(kw)
    return await ss.create_sheet(session, **args)


async def _add_cell(session: AsyncSession, code: str, cell: int, state: str, **kw: Any) -> None:
    sheet = (await session.execute(select(Sheet).where(Sheet.code == code))).scalar_one()
    session.add(SheetCell(sheet_id=sheet.id, cell_no=cell, state=state, **{"source": "hub", **kw}))
    await session.commit()


async def _cell_rows(session: AsyncSession) -> int:
    return int((await session.execute(select(func.count()).select_from(SheetCell))).scalar_one())


# --- create and codes ------------------------------------------------------------------


async def test_create_manual_sheet_codes(session: AsyncSession, l4736: str) -> None:
    assert await ss.peek_next_code(session, l4736) == "L4736-0001"
    first = await _create(session)
    assert first.code == "L4736-0001"
    assert first.id_placement == "manual"
    assert first.state == "active"
    assert await ss.peek_next_code(session, l4736) == "L4736-0002"
    assert (await _create(session)).code == "L4736-0002"

    counter = await session.get(SheetIdCounter, "L4736")
    assert counter is not None
    counter.next_value = 100
    await session.commit()
    assert await ss.peek_next_code(session, l4736) == "L4736-0100"
    assert (await _create(session)).code == "L4736-0100"
    assert await ss.peek_next_code(session, l4736) == "L4736-0101"


async def test_codes_have_four_digits_and_grow_past_9999(session: AsyncSession, l4736: str) -> None:
    """Operator decision 2026-11-05: always four digits; above 9999 the number just grows."""
    assert await ss.allocate_code(session, "L4736") == "L4736-0001"
    counter = await session.get(SheetIdCounter, "L4736")
    assert counter is not None
    counter.next_value = 9999
    await session.flush()
    assert await ss.allocate_code(session, "L4736") == "L4736-9999"
    assert await ss.allocate_code(session, "L4736") == "L4736-10000"
    assert ss.format_code("L4736", 7) == "L4736-0007"


async def test_peek_next_code_writes_nothing(session: AsyncSession, l4736: str) -> None:
    await ss.peek_next_code(session, l4736)
    await session.commit()
    assert await session.get(SheetIdCounter, "L4736") is None
    with pytest.raises(SheetTypeNotFoundError):
        await ss.peek_next_code(session, "no-such-type")


async def test_allocate_code_uses_the_callers_transaction(
    session: AsyncSession, l4736: str
) -> None:
    assert await ss.allocate_code(session, "L4736") == "L4736-0001"
    assert await ss.allocate_code(session, "L4736") == "L4736-0002"
    await session.rollback()  # nothing committed by allocate_code itself
    assert await session.get(SheetIdCounter, "L4736") is None


async def test_create_with_used_cells(session: AsyncSession, l4736: str) -> None:
    sheet = await _create(session, used_cells=[MarkedCell(n) for n in range(1, 18)])
    detail = await ss.get_sheet(session, sheet.code)
    assert (detail.total, detail.used, detail.free) == (48, 17, 31)
    assert (detail.reserved, detail.unconfirmed) == (0, 0)
    cell = detail.cells[0]
    assert (cell.cell_no, cell.state, cell.source) == (1, "used", "manual")
    assert cell.marked_by_hand is True
    assert cell.purpose == "marked by hand"
    assert cell.job_id is None
    assert cell.updated_by == "tester"


async def test_create_with_typed_purpose_and_note(session: AsyncSession, l4736: str) -> None:
    sheet = await _create(
        session,
        used_cells=[MarkedCell(3, "flour 1 kg"), MarkedCell(4, "   ")],
        note="  shelf 2\x07 ",
    )
    detail = await ss.get_sheet(session, sheet.code)
    assert [(c.cell_no, c.purpose) for c in detail.cells] == [
        (3, "flour 1 kg"),
        (4, "marked by hand"),
    ]
    assert detail.sheet.note == "shelf 2"


async def test_create_refuses_bad_cells_and_writes_nothing(
    session: AsyncSession, l4736: str
) -> None:
    with pytest.raises(CellOutOfRangeError) as info:
        await _create(session, used_cells=[MarkedCell(0), MarkedCell(49), MarkedCell(2)])
    assert info.value.detail == {"cells": [0, 49], "max": 48}
    with pytest.raises(InvalidFieldError):
        await _create(session, used_cells=[MarkedCell(1, "x" * 121)])
    with pytest.raises(InvalidFieldError):
        await _create(session, note="x" * 501)
    with pytest.raises(InvalidFieldError):
        await _create(session, id_placement="cell")  # Plan 3 widens this
    assert await _cell_rows(session) == 0
    assert (await session.execute(select(func.count()).select_from(Sheet))).scalar_one() == 0
    assert await ss.peek_next_code(session, l4736) == "L4736-0001"  # no code was burnt


async def test_create_on_archived_type_refused(session: AsyncSession, l4736: str) -> None:
    await ts.archive_type(session, l4736, actor="tester")
    with pytest.raises(SheetTypeArchivedError):
        await _create(session)
    with pytest.raises(SheetTypeNotFoundError):
        await _create(session, key="no-such-type")
    assert await session.get(SheetIdCounter, "L4736") is None


async def test_create_old_version(session: AsyncSession, l4736: str) -> None:
    await ts.add_version(session, l4736, G60, actor="tester", change_note="5 columns")
    old = await _create(session, version=1)
    new = await _create(session)
    assert (await ss.get_sheet(session, old.code)).version.version == 1
    assert (await ss.get_sheet(session, old.code)).total == 48
    assert (await ss.get_sheet(session, new.code)).version.version == 2
    assert (await ss.get_sheet(session, new.code)).total == 60
    with pytest.raises(SheetTypeNotFoundError):
        await _create(session, version=3)


# --- get -------------------------------------------------------------------------------


async def test_get_unknown_sheet(session: AsyncSession, l4736: str) -> None:
    with pytest.raises(SheetNotFoundError):
        await ss.get_sheet(session, "L4736-0099")


# --- mark ------------------------------------------------------------------------------


async def test_mark_uses_pinned_version_cell_count(session: AsyncSession, l4736: str) -> None:
    sheet = await _create(session)
    code = sheet.code
    await ts.add_version(session, l4736, G60, actor="tester", change_note="5 columns")
    with pytest.raises(CellOutOfRangeError) as info:
        await ss.mark_cells(session, code, [MarkedCell(49)], actor="tester")
    assert info.value.detail == {"cells": [49], "max": 48}
    detail = await ss.mark_cells(session, code, [MarkedCell(48)], actor="tester")
    assert (detail.total, detail.free) == (48, 47)


async def test_mark_taken_and_out_of_range(session: AsyncSession, l4736: str) -> None:
    sheet = await _create(session)
    code = sheet.code
    detail = await ss.mark_cells(
        session, code, [MarkedCell(5, "first"), MarkedCell(5, "second")], actor="tester"
    )
    assert [c.cell_no for c in detail.cells] == [5]
    assert detail.cells[0].purpose == "first"
    assert detail.free == 47

    with pytest.raises(CellsTakenError) as info:
        await ss.mark_cells(session, code, [MarkedCell(6), MarkedCell(5)], actor="tester")
    assert info.value.detail == {"cells": [5]}
    assert await _cell_rows(session) == 1  # cell 6 was not written

    with pytest.raises(CellOutOfRangeError) as range_info:
        await ss.mark_cells(
            session, code, [MarkedCell(60), MarkedCell(7), MarkedCell(-1)], actor="tester"
        )
    assert range_info.value.detail == {"cells": [-1, 60], "max": 48}
    assert await _cell_rows(session) == 1


async def test_mark_refuses_reserved_and_unconfirmed(session: AsyncSession, l4736: str) -> None:
    sheet = await _create(session)
    code = sheet.code
    await _add_cell(session, code, 1, "reserved", job_id=uuid4())
    await _add_cell(session, code, 2, "unconfirmed", job_id=uuid4())
    with pytest.raises(CellsTakenError) as info:
        await ss.mark_cells(
            session, code, [MarkedCell(3), MarkedCell(2), MarkedCell(1)], actor="tester"
        )
    assert info.value.detail == {"cells": [1, 2]}


async def test_mark_on_discarded_or_unknown_sheet(session: AsyncSession, l4736: str) -> None:
    sheet = await _create(session)
    code = sheet.code
    await ss.discard_sheet(session, code, actor="tester")
    with pytest.raises(SheetDiscardedError):
        await ss.mark_cells(session, code, [MarkedCell(1)], actor="tester")
    with pytest.raises(SheetNotFoundError):
        await ss.mark_cells(session, "L4736-0077", [MarkedCell(1)], actor="tester")


# --- unmark ----------------------------------------------------------------------------


async def test_unmark_only_hand_marked(session: AsyncSession, l4736: str) -> None:
    sheet = await _create(session, used_cells=[MarkedCell(1), MarkedCell(2)])
    code = sheet.code
    await _add_cell(session, code, 3, "used", job_id=uuid4(), source="grocy")
    with pytest.raises(CellsNotMarkedByHandError) as info:
        await ss.unmark_cells(session, code, [1, 3, 9], actor="tester")
    assert info.value.status == 409
    assert info.value.error_code == "cells_not_marked_by_hand"
    assert info.value.detail == {"cells": [3, 9]}
    assert await _cell_rows(session) == 3

    detail = await ss.unmark_cells(session, code, [1, 1], actor="tester")
    assert [c.cell_no for c in detail.cells] == [2, 3]
    assert detail.free == 46


async def test_unmark_on_discarded_sheet(session: AsyncSession, l4736: str) -> None:
    sheet = await _create(session, used_cells=[MarkedCell(1)])
    code = sheet.code
    await ss.discard_sheet(session, code, actor="tester")
    with pytest.raises(SheetDiscardedError):
        await ss.unmark_cells(session, code, [1], actor="tester")


# --- resolve ---------------------------------------------------------------------------


async def test_resolve_unconfirmed(session: AsyncSession, l4736: str) -> None:
    sheet = await _create(session, used_cells=[MarkedCell(10)])
    code = sheet.code
    job = uuid4()
    await _add_cell(session, code, 1, "unconfirmed", job_id=job, source="hub",
                    purpose="Sheet ID")  # fmt: skip
    await _add_cell(session, code, 2, "unconfirmed", job_id=job, source="grocy",
                    purpose="flour 1 kg", ref="42")  # fmt: skip
    await _add_cell(session, code, 3, "unconfirmed", job_id=job, source="grocy")

    with pytest.raises(CellsNotUnconfirmedError) as info:
        await ss.resolve_cells(session, code, [2, 10, 11], "printed", actor="tester")
    assert info.value.status == 409
    assert info.value.error_code == "cells_not_unconfirmed"
    assert info.value.detail == {"cells": [10, 11]}

    detail = await ss.resolve_cells(session, code, [2], "printed", actor="person")
    cell2 = next(c for c in detail.cells if c.cell_no == 2)
    assert (cell2.state, cell2.source, cell2.purpose, cell2.ref, cell2.job_id) == (
        "used", "grocy", "flour 1 kg", "42", job
    )  # fmt: skip
    assert cell2.updated_by == "person"
    assert detail.sheet.id_printed is False  # no ID label among the resolved cells

    detail = await ss.resolve_cells(session, code, [3], "not_printed", actor="person")
    assert 3 not in [c.cell_no for c in detail.cells]
    assert detail.unconfirmed == 1

    detail = await ss.resolve_cells(session, code, [1], "printed", actor="person")
    assert detail.sheet.id_printed is True  # spec 7.1: the ID cell is used
    assert (detail.used, detail.unconfirmed, detail.free) == (3, 0, 45)


async def test_resolve_not_printed_id_cell_keeps_id_unprinted(
    session: AsyncSession, l4736: str
) -> None:
    sheet = await _create(session)
    await _add_cell(session, sheet.code, 1, "unconfirmed", job_id=uuid4(), source="hub")
    detail = await ss.resolve_cells(session, sheet.code, [1], "not_printed", actor="x")
    assert detail.sheet.id_printed is False
    assert detail.free == 48


# --- discard ---------------------------------------------------------------------------


async def test_discard_busy_and_ok(session: AsyncSession, l4736: str) -> None:
    sheet = await _create(session)
    code = sheet.code
    await _add_cell(session, code, 4, "reserved", job_id=uuid4())
    with pytest.raises(SheetBusyError):
        await ss.discard_sheet(session, code, actor="tester")
    assert (await ss.get_sheet(session, code)).sheet.state == "active"

    await session.execute(text("DELETE FROM sheet_cells"))
    await session.commit()
    discarded = await ss.discard_sheet(session, code, actor="tester")
    assert discarded.state == "discarded"
    assert discarded.discarded_by == "tester"
    assert discarded.discarded_at is not None

    detail = await ss.get_sheet(session, code)
    assert detail.sheet.state == "discarded"
    assert [r.sheet.code for r in await ss.list_sheets(session)] == []
    assert [r.sheet.code for r in await ss.list_sheets(session, state="discarded")] == [code]
    assert [r.sheet.code for r in await ss.list_sheets(session, state="all")] == [code]
    with pytest.raises(SheetNotFoundError):
        await ss.discard_sheet(session, "L4736-0055", actor="tester")


async def test_discard_twice_keeps_the_first_record(session: AsyncSession, l4736: str) -> None:
    sheet = await _create(session)
    code = sheet.code
    first = await ss.discard_sheet(session, code, actor="alice")
    at = first.discarded_at
    again = await ss.discard_sheet(session, code, actor="bob")
    assert again.discarded_by == "alice"
    assert at is not None and again.discarded_at is not None
    assert again.discarded_at.replace(tzinfo=None) == at.replace(tzinfo=None)


async def test_discarded_code_never_reissued_after_archive_cycle(
    session: AsyncSession, l4736: str
) -> None:
    first = await _create(session)
    assert first.code == "L4736-0001"
    await ss.discard_sheet(session, first.code, actor="tester")
    await ts.archive_type(session, l4736, actor="tester")
    await ts.unarchive_type(session, l4736, actor="tester")
    assert (await _create(session)).code == "L4736-0002"


# --- list ------------------------------------------------------------------------------


async def _sheet_with_free(session: AsyncSession, free: int) -> str:
    sheet = await _create(session, used_cells=[MarkedCell(n) for n in range(1, 49 - free)])
    return sheet.code


async def test_list_order_fits_first(session: AsyncSession, l4736: str) -> None:
    c3 = await _sheet_with_free(session, 3)
    c31 = await _sheet_with_free(session, 31)
    c9 = await _sheet_with_free(session, 9)
    rows = await ss.list_sheets(session, free_at_least=9)
    assert [r.sheet.code for r in rows] == [c31, c9, c3]
    assert [r.free for r in rows] == [31, 9, 3]
    assert (rows[0].total, rows[0].used, rows[0].type.key, rows[0].version.version) == (
        48, 17, l4736, 1
    )  # fmt: skip
    # only the 31 fits a request for 10; the rest follow by free cells, most first
    rows = await ss.list_sheets(session, free_at_least=10)
    assert [r.sheet.code for r in rows] == [c31, c9, c3]


async def test_list_ties_order_by_code(session: AsyncSession, l4736: str) -> None:
    a = await _sheet_with_free(session, 5)
    b = await _sheet_with_free(session, 5)
    assert [r.sheet.code for r in await ss.list_sheets(session)] == [a, b]


async def test_list_filters(session: AsyncSession, l4736: str) -> None:
    await ts.create_type(session, _fields("other-type", "OTHER"), G60, actor="tester")
    full = await _sheet_with_free(session, 0)
    part = await _sheet_with_free(session, 4)
    other = (await _create(session, key="other-type")).code
    gone = (await _create(session, key="other-type")).code
    await ss.discard_sheet(session, gone, actor="tester")

    codes = lambda rows: sorted(r.sheet.code for r in rows)  # noqa: E731
    assert codes(await ss.list_sheets(session)) == sorted([full, part, other])
    assert codes(await ss.list_sheets(session, state="full")) == [full]
    assert codes(await ss.list_sheets(session, state="all")) == sorted([full, part, other, gone])
    assert codes(await ss.list_sheets(session, type_key="other-type")) == [other]
    assert codes(await ss.list_sheets(session, type_key="other-type", state="all")) == sorted(
        [other, gone]
    )
    assert codes(await ss.list_sheets(session, q="other-0")) == [other]
    assert codes(await ss.list_sheets(session, q="l4736")) == sorted([full, part])
    with pytest.raises(SheetTypeNotFoundError):
        await ss.list_sheets(session, type_key="no-such-type")


async def test_list_counts_per_state(session: AsyncSession, l4736: str) -> None:
    sheet = await _create(session, used_cells=[MarkedCell(1)])
    await _add_cell(session, sheet.code, 2, "reserved", job_id=uuid4())
    await _add_cell(session, sheet.code, 3, "unconfirmed", job_id=uuid4())
    (row,) = await ss.list_sheets(session)
    assert (row.used, row.reserved, row.unconfirmed, row.free, row.total) == (1, 1, 1, 45, 48)


# --- find cells ------------------------------------------------------------------------


async def test_find_cells_by_ref(session: AsyncSession, l4736: str) -> None:
    a = await _create(session)
    b = await _create(session)
    now = datetime.now(UTC)
    await _add_cell(session, a.code, 5, "used", source="grocy", ref="42", purpose="flour",
                    updated_at=now - timedelta(days=2))  # fmt: skip
    await _add_cell(session, b.code, 7, "used", source="grocy", ref="42", purpose="flour",
                    updated_at=now)  # fmt: skip
    await _add_cell(session, b.code, 8, "used", source="grocy", ref="43")
    await _add_cell(session, b.code, 9, "used", source="snipeit", ref="42")

    hits = await ss.find_cells(session, source="grocy", ref="42")
    assert [(h.code, h.cell, h.state, h.purpose) for h in hits] == [
        (b.code, 7, "used", "flour"),
        (a.code, 5, "used", "flour"),
    ]
    assert hits[0].updated_at > hits[1].updated_at
    assert await ss.find_cells(session, source="grocy", ref="nope") == []


# --- sanitising ------------------------------------------------------------------------


async def test_purposes_sanitised(session: AsyncSession, l4736: str) -> None:
    sheet = await _create(session)
    code = sheet.code
    detail = await ss.mark_cells(
        session,
        code,
        [MarkedCell(1, "flo\x07ur‮"), MarkedCell(2, "a‍b")],
        actor="tester",
    )
    assert [c.purpose for c in detail.cells] == ["flour", "a‍b"]
    with pytest.raises(InvalidFieldError) as info:
        await ss.mark_cells(session, code, [MarkedCell(3, "x" * 121)], actor="tester")
    assert info.value.status == 422
    assert info.value.detail == {"field": "purpose", "reason": "too long"}
    assert await _cell_rows(session) == 2


# --- events ----------------------------------------------------------------------------


async def test_events_published_after_commit(session: AsyncSession, l4736: str) -> None:
    bus = FakeBus()
    sheet = await _create(session, used_cells=[MarkedCell(2), MarkedCell(1)], bus=bus)
    await ss.mark_cells(session, sheet.code, [MarkedCell(7), MarkedCell(5)], actor="t", bus=bus)
    await ss.unmark_cells(session, sheet.code, [5], actor="t", bus=bus)
    await _add_cell(session, sheet.code, 9, "unconfirmed", job_id=uuid4())
    await ss.resolve_cells(session, sheet.code, [9], "printed", actor="t", bus=bus)
    await ss.discard_sheet(session, sheet.code, actor="t", bus=bus)

    assert {ch for ch, _ in bus.events} == {"sheets"}
    assert [e.event_type for _, e in bus.events] == ["sheet.updated"] * 5
    assert [e.data for _, e in bus.events] == [
        {"code": "L4736-0001", "free": 46, "total": 48, "changed": [1, 2], "state": "active"},
        {"code": "L4736-0001", "free": 44, "total": 48, "changed": [5, 7], "state": "active"},
        {"code": "L4736-0001", "free": 45, "total": 48, "changed": [5], "state": "active"},
        {"code": "L4736-0001", "free": 44, "total": 48, "changed": [9], "state": "active"},
        {"code": "L4736-0001", "free": 44, "total": 48, "changed": [], "state": "discarded"},
    ]
    assert all(e.channel == "sheets" for _, e in bus.events)


async def test_failed_writes_publish_nothing(session: AsyncSession, l4736: str) -> None:
    bus = FakeBus()
    sheet = await _create(session, used_cells=[MarkedCell(1)])
    code = sheet.code
    with pytest.raises(CellsTakenError):
        await ss.mark_cells(session, code, [MarkedCell(1)], actor="t", bus=bus)
    with pytest.raises(CellsNotMarkedByHandError):
        await ss.unmark_cells(session, code, [2], actor="t", bus=bus)
    with pytest.raises(CellsNotUnconfirmedError):
        await ss.resolve_cells(session, code, [1], "printed", actor="t", bus=bus)
    await ts.archive_type(session, l4736, actor="t")
    with pytest.raises(SheetTypeArchivedError):
        await _create(session, bus=bus)
    assert bus.events == []


async def test_commit_failure_publishes_nothing(
    session: AsyncSession, l4736: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    bus = FakeBus()
    sheet = await _create(session)
    code = sheet.code

    async def boom() -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(session, "commit", boom)
    with pytest.raises(RuntimeError):
        await ss.mark_cells(session, code, [MarkedCell(1)], actor="t", bus=bus)
    assert bus.events == []
    monkeypatch.undo()
    assert await _cell_rows(session) == 0  # rolled back


# --- the write lock --------------------------------------------------------------------


async def test_every_sheet_write_takes_the_write_lock(session: AsyncSession, l4736: str) -> None:
    async def seq() -> int:
        return int(
            (await session.execute(text("SELECT seq FROM sheet_write_lock WHERE id = 1"))).scalar()
            or 0
        )

    before = await seq()
    sheet = await _create(session)
    await ss.mark_cells(session, sheet.code, [MarkedCell(1)], actor="t")
    await ss.unmark_cells(session, sheet.code, [1], actor="t")
    await _add_cell(session, sheet.code, 2, "unconfirmed", job_id=uuid4())
    await ss.resolve_cells(session, sheet.code, [2], "not_printed", actor="t")
    await ss.discard_sheet(session, sheet.code, actor="t")
    assert await seq() == before + 5
    # reads do not take it
    await ss.get_sheet(session, sheet.code)
    await ss.list_sheets(session)
    await ss.peek_next_code(session, l4736)
    await ss.find_cells(session, source="x", ref="y")
    await session.commit()
    assert await seq() == before + 5


# --- empty cell lists ------------------------------------------------------------------


async def test_empty_cell_lists_do_nothing(session: AsyncSession, l4736: str) -> None:
    """Spec 8: nothing to mark, free or settle means no lock, no commit and no event."""

    async def seq() -> int:
        return int(
            (await session.execute(text("SELECT seq FROM sheet_write_lock WHERE id = 1"))).scalar()
            or 0
        )

    bus: Any = FakeBus()
    sheet = await _create(session, used_cells=[MarkedCell(3, "kept")])
    await session.commit()
    before = await seq()
    for result in (
        await ss.mark_cells(session, sheet.code, [], actor="t", bus=bus),
        await ss.unmark_cells(session, sheet.code, [], actor="t", bus=bus),
        await ss.resolve_cells(session, sheet.code, [], "printed", actor="t", bus=bus),
    ):
        assert result.sheet.code == sheet.code and result.used == 1
    await session.commit()
    assert await seq() == before
    assert bus.events == []
    # an empty request still refuses an unknown or discarded sheet
    with pytest.raises(SheetNotFoundError):
        await ss.mark_cells(session, "L4736-0999", [], actor="t")
    await ss.discard_sheet(session, sheet.code, actor="t")
    with pytest.raises(SheetDiscardedError):
        await ss.unmark_cells(session, sheet.code, [], actor="t")


async def test_last_used_at_follows_cells_that_became_used(
    session: AsyncSession, l4736: str
) -> None:
    empty = await _create(session)
    assert empty.last_used_at is None
    with_marks = await _create(session, used_cells=[MarkedCell(1)])
    assert with_marks.last_used_at is not None
    code = empty.code
    detail = await ss.mark_cells(session, code, [MarkedCell(2)], actor="t")
    assert detail.sheet.last_used_at is not None
    third = (await _create(session)).code
    await _add_cell(session, third, 4, "unconfirmed", job_id=uuid4())
    await ss.resolve_cells(session, third, [4], "not_printed", actor="t")
    assert (await ss.get_sheet(session, third)).sheet.last_used_at is None  # nothing was used
    await _add_cell(session, third, 5, "unconfirmed", job_id=uuid4())
    resolved = await ss.resolve_cells(session, third, [5], "printed", actor="t")
    assert resolved.sheet.last_used_at is not None


async def test_sheet_note_keeps_line_breaks_but_a_purpose_does_not(
    session: AsyncSession, l4736: str
) -> None:
    sheet = await _create(
        session,
        used_cells=[MarkedCell(3, "flour\n1 kg")],
        note="shelf 2\r\nleft side",
    )
    detail = await ss.get_sheet(session, sheet.code)
    assert detail.sheet.note == "shelf 2\nleft side"
    assert [c.purpose for c in detail.cells] == ["flour 1 kg"]
