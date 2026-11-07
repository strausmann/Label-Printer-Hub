"""Atomic reservation: rows, new sheets, plan_changed, events, margin in flight (Task 3)."""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from app.models.job import Job, JobState
from app.models.sheet import Sheet, SheetCell
from app.page_render.transform import Deviation
from app.services.event_bus import BusEvent
from app.sheets import sheet_service as ss
from app.sheets import type_service as ts
from app.sheets.errors import (
    CellsTakenError,
    PlanChangedError,
    SheetDiscardedError,
    SheetTypeArchivedError,
    SheetTypeMismatchError,
)
from app.sheets.geometry import Geometry
from app.sheets.planner import MarginContext
from app.sheets.reservation import (
    ExpectedPage,
    ItemMeta,
    NewSheetIn,
    PlacementRequest,
    margin_id_in_flight,
    release,
    reserve,
)
from app.sheets.sheet_service import MarkedCell
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
KEY = "avery-l4736rev"


def _fields(key: str = KEY, prefix: str = "L4736") -> ts.TypeFields:
    return ts.TypeFields(
        key=key,
        prefix=prefix,
        vendor="Avery",
        product_codes=["L4736REV-25"],
        description=None,
        allow_qr=None,
    )


MARGIN = MarginContext(deviation=Deviation(), scan_payload=lambda c: f"sheet:{c}", render_dpi=600)


def meta(n: int) -> list[ItemMeta]:
    return [ItemMeta("api", f"item {i}", f"ref-{i}") for i in range(n)]


def existing(code: str, **kw: Any) -> PlacementRequest:
    return PlacementRequest(sheet_code=code, new_sheet=None, **kw)


def new(placement: str = "manual", **kw: Any) -> PlacementRequest:
    return PlacementRequest(
        sheet_code=None,
        new_sheet=NewSheetIn(type_key=KEY, version=None, id_placement=placement),  # type: ignore[arg-type]
        **kw,
    )


async def do_reserve(session: AsyncSession, placements: list[PlacementRequest], n: int, **kw: Any):
    args: dict[str, Any] = {
        "placements": placements,
        "items": meta(n),
        "expected": None,
        "hw_margins_hmm": None,
        "margin": MARGIN,
        "required_type_key": None,
        "actor": "tester",
    }
    args.update(kw)
    return await reserve(session, **args)


class FakeBus:
    def __init__(self) -> None:
        self.events: list[BusEvent] = []
        self._n = 0

    def next_event_id(self, channel: str) -> int:
        self._n += 1
        return self._n

    def publish(self, channel: str, event: BusEvent) -> None:
        self.events.append(event)


@pytest_asyncio.fixture
async def session(async_session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[Any]:
    async with async_session_factory() as s:
        await ts.create_type(s, _fields(), G48, actor="tester")
        yield s


async def make_sheet(
    session: AsyncSession, used: int = 0, placement: str = "manual", key: str = KEY
) -> str:
    sheet = await ss.create_sheet(
        session,
        type_key=key,
        version=None,
        id_placement=placement,  # type: ignore[arg-type]
        used_cells=[MarkedCell(n) for n in range(1, used + 1)],
        note=None,
        actor="tester",
    )
    return sheet.code


async def cells(session: AsyncSession) -> list[SheetCell]:
    return list(
        (await session.execute(select(SheetCell).order_by(SheetCell.cell_no))).scalars().all()
    )


async def test_reserve_writes_reserved_rows_with_job_id(session: AsyncSession) -> None:
    code = await make_sheet(session, used=17)
    pages = await do_reserve(session, [existing(code)], 9)

    (page,) = pages
    assert page.sheet_code == code
    assert [a.cell for a in page.assignments] == list(range(18, 27))
    assert [a.item_index for a in page.assignments] == list(range(9))
    rows = [c for c in await cells(session) if c.state == "reserved"]
    assert [c.cell_no for c in rows] == list(range(18, 27))
    assert {c.job_id for c in rows} == {page.job_id}
    assert [c.purpose for c in rows] == [f"item {i}" for i in range(9)]
    assert {c.source for c in rows} == {"api"}
    assert [c.ref for c in rows] == [f"ref-{i}" for i in range(9)]


async def test_new_sheet_created_in_same_transaction(session: AsyncSession) -> None:
    pages = await do_reserve(session, [new("cell")], 3)

    (page,) = pages
    assert page.sheet_code == "L4736-0001"
    assert page.id_cell == 1
    id_assignment = page.assignments[0]
    assert (id_assignment.cell, id_assignment.item_index) == (1, None)
    assert (id_assignment.source, id_assignment.purpose) == ("hub", "Sheet ID")
    assert [a.cell for a in page.assignments[1:]] == [2, 3, 4]
    sheet = (await session.execute(select(Sheet))).scalar_one()
    assert (sheet.code, sheet.id_placement) == ("L4736-0001", "cell")
    id_row = next(c for c in await cells(session) if c.cell_no == 1)
    assert (id_row.source, id_row.state, id_row.job_id) == ("hub", "reserved", page.job_id)


async def test_plan_changed_writes_nothing(session: AsyncSession) -> None:
    fresh = await do_reserve(session, [new()], 2, expected=None)
    code = fresh[0].sheet_code
    await release(session, fresh[0].job_id)
    before_rows = len(await cells(session))
    stale = [ExpectedPage(sheet=code, cells=[3, 4], id_cell=None)]

    with pytest.raises(PlanChangedError) as err:
        await do_reserve(session, [existing(code, count=2), new()], 4, expected=stale)

    plan = err.value.detail["plan"]  # type: ignore[index]
    assert plan[0]["sheet"] == code
    assert err.value.error_code == "plan_changed"
    assert len(await cells(session)) == before_rows
    assert (await session.execute(select(func.count()).select_from(Sheet))).scalar_one() == 1
    # the new sheet and its counter step were rolled back (acceptance 13)
    assert await ss.peek_next_code(session, KEY) == "L4736-0002"


async def test_expected_matching_plan_commits(session: AsyncSession) -> None:
    code = await make_sheet(session)
    # counter-check of the test above: the same call with the true plan is accepted
    good = [ExpectedPage(sheet=code, cells=[1, 2], id_cell=None)]
    pages = await do_reserve(session, [existing(code, count=2)], 2, expected=good)
    assert [a.cell for a in pages[0].assignments] == [1, 2]


async def test_explicit_taken(session: AsyncSession) -> None:
    code = await make_sheet(session)
    await do_reserve(session, [existing(code, cells=[5])], 1)

    with pytest.raises(CellsTakenError) as err:
        await do_reserve(session, [existing(code, cells=[5])], 1)

    assert err.value.detail == {"cells": [5]}


async def test_type_mismatch_and_archived(session: AsyncSession) -> None:
    other = _fields("other-type", "OTHER")
    await ts.create_type(session, other, G48, actor="tester")
    code = await make_sheet(session, key="other-type")

    with pytest.raises(SheetTypeMismatchError) as err:
        await do_reserve(session, [existing(code)], 1, required_type_key=KEY)
    assert err.value.detail == {"expected": KEY, "actual": "other-type"}
    with pytest.raises(SheetTypeMismatchError):
        await do_reserve(
            session,
            [PlacementRequest(None, NewSheetIn("other-type", None, "manual"))],
            1,
            required_type_key=KEY,
        )

    await ts.archive_type(session, KEY, actor="tester")
    with pytest.raises(SheetTypeArchivedError):
        await do_reserve(session, [new()], 1, required_type_key=KEY)
    assert (await session.execute(select(func.count()).select_from(SheetCell))).scalar_one() == 0


async def test_release_deletes_only_that_jobs_reserved_rows(session: AsyncSession) -> None:
    code = await make_sheet(session, used=2)
    first = (await do_reserve(session, [existing(code)], 3))[0]
    second = (await do_reserve(session, [existing(code)], 2))[0]
    done = next(c for c in await cells(session) if c.cell_no == 4)
    done.state = "used"  # the first job already turned one cell into used
    await session.commit()

    freed = await release(session, first.job_id)

    assert freed == [3, 5]
    left = {c.cell_no: (c.state, c.job_id) for c in await cells(session)}
    assert left[4] == ("used", first.job_id)
    assert left[6] == ("reserved", second.job_id)
    assert 3 not in left and 5 not in left
    assert await release(session, first.job_id) == []  # idempotent


async def test_reserve_carries_margin_placement(session: AsyncSession) -> None:
    code = await make_sheet(session, placement="margin")

    page = (await do_reserve(session, [existing(code)], 1))[0]

    assert page.margin_id is True
    assert page.margin_placement is not None
    assert page.margin_placement.band == "top"
    assert page.margin_placement.depth_hmm == 1550
    assert page.id_not_printed is False


async def test_margin_context_is_required_and_unprintable_reserves_without_id(
    session: AsyncSession,
) -> None:
    tight = replace(
        G48, label_w=19900, label_h=28600, cols=1, rows=1, pitch_x=19900, pitch_y=28600,
        margin_top=550, margin_left=550,
    )  # fmt: skip
    await ts.create_type(session, _fields("tight", "TIGHT"), tight, actor="tester")
    code = await make_sheet(session, placement="margin", key="tight")

    page = (await do_reserve(session, [existing(code)], 1))[0]

    assert inspect.signature(reserve).parameters["margin"].default is inspect.Parameter.empty
    assert [c.cell_no for c in await cells(session)] == [1]
    assert (page.margin_id, page.margin_placement, page.id_not_printed) == (False, None, True)


async def test_margin_id_drawn_once_across_requests(session: AsyncSession) -> None:
    code = await make_sheet(session, placement="margin")

    first = (await do_reserve(session, [existing(code)], 2))[0]
    second = (await do_reserve(session, [existing(code)], 2))[0]

    # C26: the first job's row is not saved yet, so its margin ID counts as in flight
    assert (first.margin_id, second.margin_id) == (True, False)


async def _job(session: AsyncSession, job_id: UUID, state: str, detail: dict[str, Any]) -> None:
    session.add(
        Job(
            id=job_id,
            printer_id=uuid4(),
            state=state,
            payload={"kind": "sheet_page", "detail": detail},
        )
    )
    await session.commit()


async def test_margin_id_in_flight_rules(session: AsyncSession) -> None:
    code = await make_sheet(session, placement="margin")
    sheet_id = (await session.execute(select(Sheet.id))).scalar_one()
    other_id = uuid4()
    assert await margin_id_in_flight(session, sheet_id) is False

    job_id = uuid4()
    # a queued margin job of another sheet does not count
    await _job(session, job_id, JobState.QUEUED.value, {"sheet_id": str(other_id), "margin_id": {}})
    assert await margin_id_in_flight(session, sheet_id) is False
    # a queued job of this sheet without margin ID does not count
    await _job(session, uuid4(), JobState.QUEUED.value, {"sheet_id": str(sheet_id)})
    assert await margin_id_in_flight(session, sheet_id) is False
    # a queued / printing margin job does
    margin_job = uuid4()
    await _job(
        session,
        margin_job,
        JobState.PRINTING.value,
        {"sheet_id": str(sheet_id), "margin_id": {"text": code}},
    )
    assert await margin_id_in_flight(session, sheet_id) is True
    # a finished one does not
    job = await session.get(Job, margin_job)
    assert job is not None
    job.state = JobState.DONE.value
    await session.commit()
    assert await margin_id_in_flight(session, sheet_id) is False
    # reserved cells whose job has no row do (C26); once the row exists they do not
    attached = uuid4()
    session.add(
        SheetCell(sheet_id=sheet_id, cell_no=1, state="reserved", job_id=attached, source="api")
    )
    await session.commit()
    assert await margin_id_in_flight(session, sheet_id) is True
    await _job(session, attached, JobState.QUEUED.value, {"sheet_id": str(sheet_id)})
    assert await margin_id_in_flight(session, sheet_id) is False


async def test_events_after_commit_one_per_sheet(
    session: AsyncSession, async_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    code = await make_sheet(session, used=8)
    bus = FakeBus()
    pages = await do_reserve(session, [existing(code, count=2), new("cell")], 5, bus=bus)

    assert [p.sheet_code for p in pages] == [code, "L4736-0002"]
    assert [e.event_type for e in bus.events] == ["sheet.updated", "sheet.updated"]
    first, second = (e.data for e in bus.events)
    assert (first["code"], first["changed"], first["free"], first["total"]) == (
        code,
        [9, 10],
        38,
        48,
    )
    assert (second["code"], second["changed"], second["free"]) == ("L4736-0002", [1, 2, 3, 4], 44)

    bus.events.clear()
    freed = pages[0].job_id
    await release(session, freed, bus=bus)
    assert [e.data["changed"] for e in bus.events] == [[9, 10]]
    assert bus.events[0].data["free"] == 40


async def test_events_are_published_after_the_commit(session: AsyncSession) -> None:
    code = await make_sheet(session)
    bus = FakeBus()
    state_at_publish: list[bool] = []
    original = bus.publish

    def publish(channel: str, event: BusEvent) -> None:
        # after the commit the session holds no open transaction and no pending rows
        state_at_publish.append(session.in_transaction() or bool(session.new))
        original(channel, event)

    bus.publish = publish  # type: ignore[method-assign]
    await do_reserve(session, [existing(code)], 3, bus=bus)

    assert state_at_publish == [False]


async def test_no_event_when_plan_changed(session: AsyncSession) -> None:
    code = await make_sheet(session)
    bus = FakeBus()
    with pytest.raises(PlanChangedError):
        await do_reserve(
            session, [existing(code)], 2, bus=bus, expected=[ExpectedPage(code, [7, 8], None)]
        )
    assert bus.events == []


def _fail_first_cell_flush(monkeypatch: pytest.MonkeyPatch, times: int) -> list[int]:
    real = AsyncSession.flush
    calls = [0]

    async def flush(self: AsyncSession, objects: Any = None) -> None:
        if any(isinstance(o, SheetCell) for o in self.new) and calls[0] < times:
            calls[0] += 1
            raise IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed"))
        await real(self, objects)

    monkeypatch.setattr(AsyncSession, "flush", flush)
    return calls


async def test_integrity_error_first_free_replans_once(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    code = await make_sheet(session)
    calls = _fail_first_cell_flush(monkeypatch, 1)

    pages = await do_reserve(session, [existing(code)], 2)

    assert calls == [1]  # one refused insert, then the re-plan went through
    assert [a.cell for a in pages[0].assignments] == [1, 2]
    assert len([c for c in await cells(session) if c.state == "reserved"]) == 2


async def test_integrity_error_twice_gives_cells_taken(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    code = await make_sheet(session)
    calls = _fail_first_cell_flush(monkeypatch, 5)

    with pytest.raises(CellsTakenError) as err:
        await do_reserve(session, [existing(code)], 2)

    assert calls == [2]  # re-planned exactly once
    assert err.value.detail == {"cells": [1, 2]}
    assert await cells(session) == []


async def test_integrity_error_explicit_is_cells_taken_without_replan(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    code = await make_sheet(session)
    calls = _fail_first_cell_flush(monkeypatch, 5)

    with pytest.raises(CellsTakenError) as err:
        await do_reserve(session, [existing(code, cells=[7, 8])], 2)

    assert calls == [1]
    assert err.value.detail == {"cells": [7, 8]}
    assert await cells(session) == []


async def test_id_only_job_with_no_items(session: AsyncSession) -> None:
    pages = await do_reserve(session, [new("cell")], 0)
    assert pages[0].id_cell == 1
    assert [a.cell for a in pages[0].assignments] == [1]


async def test_second_print_does_not_plan_another_id_cell(session: AsyncSession) -> None:
    """I1: an ID cell that is still reserved counts as the sheet's ID in flight (OC-40)."""
    first = (await do_reserve(session, [new("cell")], 2))[0]
    assert first.id_cell == 1

    second = (await do_reserve(session, [existing(first.sheet_code)], 2))[0]

    assert second.id_cell is None
    assert [a.cell for a in second.assignments] == [4, 5]
    assert not any(a.source == "hub" for a in second.assignments)


async def test_reserve_onto_discarded_sheet_is_refused(session: AsyncSession) -> None:
    """I2: the sheet state is read under the lock and the planner refuses a discarded sheet."""
    code = await make_sheet(session)
    await ss.discard_sheet(session, code, actor="tester")

    with pytest.raises(SheetDiscardedError):
        await do_reserve(session, [existing(code)], 2)

    assert await cells(session) == []


async def test_plan_changed_when_only_the_id_cell_differs(session: AsyncSession) -> None:
    """I3: ``expected`` that omits or moves the ID cell is a different plan."""
    for wrong_id in (None, 2):
        with pytest.raises(PlanChangedError) as err:
            await do_reserve(
                session,
                [new("cell", count=2)],
                2,
                expected=[ExpectedPage("new", [2, 3], wrong_id)],
            )
        assert err.value.detail["plan"] == [  # type: ignore[index]
            {"sheet": "new", "cells": [2, 3], "id_cell": 1}
        ]
    assert await cells(session) == []
    # counter-check: the true plan, ID cell included, is accepted
    pages = await do_reserve(
        session, [new("cell", count=2)], 2, expected=[ExpectedPage("new", [2, 3], 1)]
    )
    assert pages[0].id_cell == 1


async def test_integrity_error_with_mixed_placements_is_not_replanned(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Minor 1: one explicit placement makes the whole request explicit; no re-plan."""
    code = await make_sheet(session)
    calls = _fail_first_cell_flush(monkeypatch, 5)

    with pytest.raises(CellsTakenError):
        await do_reserve(session, [existing(code, cells=[7, 8]), new(count=1)], 3)

    assert calls == [1]


async def test_failing_event_bus_does_not_lose_the_reservation(session: AsyncSession) -> None:
    """Minor 6: the rows are committed, so the caller must still get its pages."""
    code = await make_sheet(session)

    class Broken(FakeBus):
        def publish(self, channel: str, event: BusEvent) -> None:
            raise RuntimeError("subscriber exploded")

    pages = await do_reserve(session, [existing(code)], 2, bus=Broken())

    assert [a.cell for a in pages[0].assignments] == [1, 2]
    assert len([c for c in await cells(session) if c.state == "reserved"]) == 2
