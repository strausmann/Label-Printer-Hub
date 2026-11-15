# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Outcome handler and orphan sweep: D15 transitions after a page job ends (Task 5)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from app.models.job import Job
from app.models.sheet import Sheet, SheetCell
from app.sheets import sheet_service as ss
from app.sheets import type_service as ts
from app.sheets.outcome import SheetCellsOutcome, sweep_orphan_reservations
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.unit.sheets.test_reservation import G48 as GEOMETRY
from tests.unit.sheets.test_reservation import (
    FakeBus,
    _fields,
    do_reserve,
    existing,
    make_sheet,
    new,
)

Factory = async_sessionmaker[AsyncSession]


@pytest_asyncio.fixture
async def session(async_session_factory: Factory) -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as s:
        await ts.create_type(s, _fields(), GEOMETRY, actor="tester")
        yield s


async def read_cells(factory: Factory) -> list[SheetCell]:
    async with factory() as s:
        return list(
            (await s.execute(select(SheetCell).order_by(SheetCell.cell_no))).scalars().all()
        )


async def read_sheet(factory: Factory) -> Sheet:
    async with factory() as s:
        return (await s.execute(select(Sheet))).scalar_one()


def states(rows: list[SheetCell]) -> dict[int, str]:
    return {r.cell_no: r.state for r in rows}


async def add_job(
    session: AsyncSession,
    job_id: UUID,
    state: str = "printing",
    *,
    margin_id: bool = False,
    sheet_id: UUID | None = None,
    feed_mark: bool = False,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    finished_at: datetime | None = None,
) -> None:
    detail: dict[str, Any] = {"margin_id": margin_id}
    if feed_mark:
        detail["feed_mark"] = {"text": "▲ Top \u2013 this edge first"}
    if sheet_id is not None:
        detail["sheet_id"] = str(sheet_id)
    session.add(
        Job(
            id=job_id,
            printer_id=uuid4(),
            state=state,
            payload={"kind": "sheet_page", "detail": detail},
            result=result,
            error=error,
            finished_at=finished_at,
        )
    )
    await session.commit()


# ---------------------------------------------------------------------------- handler


async def test_completed_marks_used(session: AsyncSession, async_session_factory: Factory) -> None:
    code = await make_sheet(session, used=17)
    (page,) = await do_reserve(session, [existing(code)], 9)
    bus = FakeBus()
    handler = SheetCellsOutcome(async_session_factory, bus)  # type: ignore[arg-type]

    await handler.on_completed(page.job_id)

    rows = await read_cells(async_session_factory)
    assert len(rows) == 26  # acceptance 1: the sheet shows 26 used
    assert {r.state for r in rows} == {"used"}
    assert (await read_sheet(async_session_factory)).last_used_at is not None
    (event,) = bus.events
    assert event.event_type == "sheet.updated"
    assert event.data["code"] == code
    assert event.data["changed"] == list(range(18, 27))
    assert event.data["free"] == 22
    assert event.data["total"] == 48


async def test_clean_failure_frees(session: AsyncSession, async_session_factory: Factory) -> None:
    code = await make_sheet(session, used=17)
    (page,) = await do_reserve(session, [existing(code)], 9)
    bus = FakeBus()
    handler = SheetCellsOutcome(async_session_factory, bus)  # type: ignore[arg-type]

    await handler.on_ended(page.job_id, state="failed", started=False, error_code="ipp_aborted")

    assert len(await read_cells(async_session_factory)) == 17  # acceptance 2: rows deleted
    (event,) = bus.events
    assert event.data["changed"] == list(range(18, 27))
    assert event.data["free"] == 31


async def test_cancelled_before_start_frees(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    code = await make_sheet(session)
    (page,) = await do_reserve(session, [existing(code)], 3)
    handler = SheetCellsOutcome(async_session_factory, None)

    await handler.on_ended(page.job_id, state="cancelled", started=False, error_code="cancelled")

    assert await read_cells(async_session_factory) == []


async def test_started_failure_unconfirmed(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    code = await make_sheet(session, used=17)
    (page,) = await do_reserve(session, [existing(code)], 9)
    bus = FakeBus()
    handler = SheetCellsOutcome(async_session_factory, bus)  # type: ignore[arg-type]
    last_used = (await read_sheet(async_session_factory)).last_used_at  # the 17 hand marks

    await handler.on_ended(page.job_id, state="failed", started=True, error_code="interrupted")

    got = states(await read_cells(async_session_factory))
    assert [got[n] for n in range(18, 27)] == ["unconfirmed"] * 9
    assert (await read_sheet(async_session_factory)).last_used_at == last_used  # not "used"
    (event,) = bus.events
    assert event.data["changed"] == list(range(18, 27))


async def test_interrupted_code_is_unconfirmed_even_when_started_is_false(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    """The backstop-interrupted job (C4): the code says the page may have printed."""
    code = await make_sheet(session)
    (page,) = await do_reserve(session, [existing(code)], 2)
    handler = SheetCellsOutcome(async_session_factory, None)

    await handler.on_ended(page.job_id, state="failed", started=False, error_code="interrupted")

    assert set(states(await read_cells(async_session_factory)).values()) == {"unconfirmed"}


async def test_on_unknown_is_unconfirmed(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    code = await make_sheet(session)
    (page,) = await do_reserve(session, [existing(code)], 4)
    handler = SheetCellsOutcome(async_session_factory, None)

    await handler.on_unknown(page.job_id)

    assert set(states(await read_cells(async_session_factory)).values()) == {"unconfirmed"}


async def test_on_started_changes_nothing(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    code = await make_sheet(session)
    (page,) = await do_reserve(session, [existing(code)], 4)
    bus = FakeBus()
    handler = SheetCellsOutcome(async_session_factory, bus)  # type: ignore[arg-type]

    await handler.on_started(page.job_id)

    assert set(states(await read_cells(async_session_factory)).values()) == {"reserved"}
    assert bus.events == []


@pytest.mark.parametrize("call", ["completed", "failed_clean", "failed_started", "unknown"])
async def test_idempotent(session: AsyncSession, async_session_factory: Factory, call: str) -> None:
    code = await make_sheet(session)
    (page,) = await do_reserve(session, [existing(code)], 5)
    bus = FakeBus()
    handler = SheetCellsOutcome(async_session_factory, bus)  # type: ignore[arg-type]

    async def fire() -> None:
        if call == "completed":
            await handler.on_completed(page.job_id)
        elif call == "unknown":
            await handler.on_unknown(page.job_id)
        else:
            await handler.on_ended(
                page.job_id,
                state="failed",
                started=call == "failed_started",
                error_code="ipp_aborted",
            )

    await fire()
    after_first = [
        (r.cell_no, r.state, r.updated_at) for r in await read_cells(async_session_factory)
    ]
    await fire()
    # A late second call, even a contradicting one, changes nothing.
    await handler.on_completed(page.job_id)
    await handler.on_unknown(page.job_id)

    after_second = [
        (r.cell_no, r.state, r.updated_at) for r in await read_cells(async_session_factory)
    ]
    assert after_second == after_first
    assert len(bus.events) == 1  # one sheet.updated, not three


async def test_other_jobs_cells_are_untouched(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    code = await make_sheet(session)
    (a,) = await do_reserve(session, [existing(code, count=2)], 2)
    (b,) = await do_reserve(session, [existing(code, count=3)], 3)
    handler = SheetCellsOutcome(async_session_factory, None)

    await handler.on_completed(a.job_id)

    got = states(await read_cells(async_session_factory))
    assert [got[n] for n in (1, 2)] == ["used", "used"]
    assert [got[n] for n in (3, 4, 5)] == ["reserved"] * 3
    assert {r.job_id for r in await read_cells(async_session_factory) if r.cell_no > 2} == {
        b.job_id
    }


async def test_failing_bus_does_not_hide_the_commit(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    class BrokenBus(FakeBus):
        def publish(self, channel: str, event: Any) -> None:
            raise RuntimeError("subscriber failed")

    code = await make_sheet(session)
    (page,) = await do_reserve(session, [existing(code)], 2)
    handler = SheetCellsOutcome(async_session_factory, BrokenBus())  # type: ignore[arg-type]

    await handler.on_completed(page.job_id)

    assert set(states(await read_cells(async_session_factory)).values()) == {"used"}


# ---------------------------------------------------------------------------- id_printed


async def test_completed_hub_id_cell_sets_id_printed(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    (page,) = await do_reserve(session, [new("cell")], 2)
    handler = SheetCellsOutcome(async_session_factory, None)

    await handler.on_completed(page.job_id)

    assert (await read_sheet(async_session_factory)).id_printed is True


async def test_completed_margin_job_sets_id_printed(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    (page,) = await do_reserve(session, [new("margin")], 2)
    await add_job(session, page.job_id, margin_id=True, sheet_id=page.sheet_id)
    handler = SheetCellsOutcome(async_session_factory, None)

    await handler.on_completed(page.job_id)

    assert (await read_sheet(async_session_factory)).id_printed is True


async def test_completed_job_without_margin_id_leaves_id_printed_false(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    """Counter-check of the margin case: the same sheet and job, no margin ID in the payload."""
    (page,) = await do_reserve(session, [new("margin")], 2)
    await add_job(session, page.job_id, margin_id=False, sheet_id=page.sheet_id)
    handler = SheetCellsOutcome(async_session_factory, None)

    await handler.on_completed(page.job_id)

    assert (await read_sheet(async_session_factory)).id_printed is False


async def test_id_printed_set_on_completion_only(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    """Acceptance 7, outcome side: a margin job that fails cleanly frees its cells and leaves
    ``id_printed`` false (OC-40: the next job carries the margin ID again)."""
    (page,) = await do_reserve(session, [new("margin")], 2)
    await add_job(session, page.job_id, margin_id=True, sheet_id=page.sheet_id)
    handler = SheetCellsOutcome(async_session_factory, None)

    await handler.on_ended(page.job_id, state="failed", started=False, error_code="ipp_aborted")

    assert await read_cells(async_session_factory) == []
    assert (await read_sheet(async_session_factory)).id_printed is False


async def test_clean_failure_of_an_id_cell_job_leaves_id_printed_false(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    (page,) = await do_reserve(session, [new("cell")], 2)
    handler = SheetCellsOutcome(async_session_factory, None)

    await handler.on_ended(page.job_id, state="cancelled", started=False, error_code="cancelled")

    assert (await read_sheet(async_session_factory)).id_printed is False


async def test_unconfirmed_does_not_set_id_printed(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    (page,) = await do_reserve(session, [new("cell")], 2)
    handler = SheetCellsOutcome(async_session_factory, None)

    await handler.on_unknown(page.job_id)

    assert (await read_sheet(async_session_factory)).id_printed is False


async def test_id_printed_and_used_cells_land_in_one_commit(
    session: AsyncSession, async_session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Carry-forward from Task 3: one transaction. Counter-check: with two commits (cells,
    then the flag) a crash between them leaves used cells with ``id_printed`` false."""
    (page,) = await do_reserve(session, [new("cell")], 2)
    handler = SheetCellsOutcome(async_session_factory, None)
    commits: list[str] = []
    real_commit = AsyncSession.commit

    async def counting(self: AsyncSession) -> None:
        commits.append("commit")
        await real_commit(self)

    monkeypatch.setattr(AsyncSession, "commit", counting)

    await handler.on_completed(page.job_id)

    assert commits == ["commit"]
    assert (await read_sheet(async_session_factory)).id_printed is True
    assert set(states(await read_cells(async_session_factory)).values()) == {"used"}


async def test_failed_commit_leaves_cells_and_flag_untouched(
    session: AsyncSession, async_session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    (page,) = await do_reserve(session, [new("cell")], 2)
    handler = SheetCellsOutcome(async_session_factory, None)

    async def broken(self: AsyncSession) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(AsyncSession, "commit", broken)
    with pytest.raises(RuntimeError):
        await handler.on_completed(page.job_id)
    monkeypatch.undo()

    assert set(states(await read_cells(async_session_factory)).values()) == {"reserved"}
    assert (await read_sheet(async_session_factory)).id_printed is False


async def test_resolve_printed_sets_id_printed_for_margin_job(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    """A margin first job interrupted after start: unconfirmed, ``id_printed`` false; resolved
    as printed the flag is set; resolved as not printed it stays false."""
    code = await make_sheet(session, placement="margin")
    (page,) = await do_reserve(session, [existing(code, count=2)], 2)
    await add_job(session, page.job_id, margin_id=True, sheet_id=page.sheet_id)
    handler = SheetCellsOutcome(async_session_factory, None)
    await handler.on_ended(page.job_id, state="failed", started=True, error_code="interrupted")
    assert (await read_sheet(async_session_factory)).id_printed is False

    async with async_session_factory() as s:
        await ss.resolve_cells(s, code, [1], "not_printed", actor="tester")
    assert (await read_sheet(async_session_factory)).id_printed is False

    async with async_session_factory() as s:
        await ss.resolve_cells(s, code, [2], "printed", actor="tester")
    assert (await read_sheet(async_session_factory)).id_printed is True


async def test_resolve_printed_without_margin_job_leaves_id_printed_false(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    code = await make_sheet(session, placement="margin")
    (page,) = await do_reserve(session, [existing(code, count=2)], 2)
    await add_job(session, page.job_id, margin_id=False, sheet_id=page.sheet_id)
    handler = SheetCellsOutcome(async_session_factory, None)
    await handler.on_unknown(page.job_id)

    async with async_session_factory() as s:
        await ss.resolve_cells(s, code, [1, 2], "printed", actor="tester")

    assert (await read_sheet(async_session_factory)).id_printed is False


async def test_resolve_printed_after_job_row_was_purged_counts_as_no_margin(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    code = await make_sheet(session, placement="margin")
    (page,) = await do_reserve(session, [existing(code, count=2)], 2)
    handler = SheetCellsOutcome(async_session_factory, None)
    await handler.on_unknown(page.job_id)  # no jobs row ever existed

    async with async_session_factory() as s:
        await ss.resolve_cells(s, code, [1, 2], "printed", actor="tester")

    assert (await read_sheet(async_session_factory)).id_printed is False


# ---------------------------------------------------------------------------- sweep


async def seed_reserved(
    session: AsyncSession, factory: Factory, code: str, cell: int, job_id: UUID | None
) -> None:
    session.add(
        SheetCell(
            sheet_id=(await read_sheet(factory)).id,
            cell_no=cell,
            state="reserved",
            job_id=job_id,
            source="api",
            purpose="p",
            ref=None,
            marked_by_hand=False,
            updated_at=datetime.now(UTC) - timedelta(hours=1),
            updated_by="tester",
        )
    )
    await session.commit()


async def sweep_world(session: AsyncSession, factory: Factory) -> dict[str, int]:
    """One cell per situation; returns ``{situation: cell}``."""
    code = await make_sheet(session)
    cases: dict[str, tuple[str | None, dict[str, Any]]] = {
        "missing": (None, {}),
        "done": ("done", {}),
        "cancelled": ("cancelled", {}),
        "failed_clean": ("failed", {"result": {"started": False}, "error": "ipp_aborted: x"}),
        "failed_started": ("failed", {"result": {"started": True}, "error": "ipp_aborted: x"}),
        # The backstop persists "interrupted" without a result: ``started`` can still be false.
        "backstop_interrupted": (
            "failed",
            {"result": {"phase": "uploading", "started": False}, "error": "interrupted: may have"},
        ),
        "failed_restart": ("failed_restart", {"error": "page_outcome_unknown"}),
        "queued": ("queued", {}),
        "printing": ("printing", {"result": {"phase": "uploading", "started": False}}),
    }
    world: dict[str, int] = {}
    for n, (name, (state, kw)) in enumerate(cases.items(), start=1):
        job_id = uuid4()
        if state is not None:
            await add_job(session, job_id, state, **kw)
        await seed_reserved(session, factory, code, n, job_id)
        world[name] = n
    return world


async def test_sweep_orphan_reservations(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    world = await sweep_world(session, async_session_factory)
    bus = FakeBus()

    report = await sweep_orphan_reservations(async_session_factory, bus=bus)  # type: ignore[arg-type]

    got = states(await read_cells(async_session_factory))
    expected = {
        "missing": "unconfirmed",  # T5-1: the job row may have been purged after it printed
        "done": "used",
        "cancelled": None,
        "failed_clean": None,
        "failed_started": "unconfirmed",
        "backstop_interrupted": "unconfirmed",
        "failed_restart": "unconfirmed",
        "queued": "reserved",
        "printing": "reserved",
    }
    assert {name: got.get(cell) for name, cell in world.items()} == expected
    assert (report.used, report.unconfirmed, report.freed) == (1, 4, 2)
    assert report.untouched == 2
    (event,) = bus.events
    changed = sorted(c for name, c in world.items() if name not in ("queued", "printing"))
    assert event.data["changed"] == changed  # every touched cell is announced, no other


@pytest.mark.parametrize("situation", ["failed_started", "backstop_interrupted", "failed_restart"])
async def test_sweep_possibly_printed_is_never_freed(
    session: AsyncSession, async_session_factory: Factory, situation: str
) -> None:
    """C4, one condition at a time: each alone keeps the cell (a second label on top of a
    printed one is the anti-goal)."""
    world = await sweep_world(session, async_session_factory)

    await sweep_orphan_reservations(async_session_factory)

    got = states(await read_cells(async_session_factory))
    assert got[world[situation]] == "unconfirmed"


async def test_sweep_is_idempotent(session: AsyncSession, async_session_factory: Factory) -> None:
    await sweep_world(session, async_session_factory)
    await sweep_orphan_reservations(async_session_factory)
    before = states(await read_cells(async_session_factory))
    bus = FakeBus()

    report = await sweep_orphan_reservations(async_session_factory, bus=bus)  # type: ignore[arg-type]

    assert states(await read_cells(async_session_factory)) == before
    assert (report.used, report.unconfirmed, report.freed) == (0, 0, 0)
    assert bus.events == []


async def test_sweep_spares_a_fresh_reservation_without_a_jobs_row(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    """The reservation commits before the page job is saved (C26): in that window the rows
    have no ``jobs`` row yet and are not orphans."""
    code = await make_sheet(session)
    (fresh,) = await do_reserve(session, [existing(code, count=2)], 2)  # updated_at is now
    await seed_reserved(session, async_session_factory, code, 10, uuid4())  # an hour old

    report = await sweep_orphan_reservations(async_session_factory)

    got = states(await read_cells(async_session_factory))
    # the old job-less row is unconfirmed (never free), the fresh one stays reserved
    assert got == {1: "reserved", 2: "reserved", 10: "unconfirmed"}
    assert report.spared == 2
    assert {r.job_id for r in await read_cells(async_session_factory) if r.cell_no < 10} == {
        fresh.job_id
    }


async def test_sweep_grace_period_is_what_spares_it(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    """Counter-check: with a zero grace period the same fresh reservation is settled."""
    code = await make_sheet(session)
    await do_reserve(session, [existing(code, count=2)], 2)

    await sweep_orphan_reservations(async_session_factory, grace=timedelta(0))

    assert set(states(await read_cells(async_session_factory)).values()) == {"unconfirmed"}


async def test_sweep_job_saved_after_the_read_is_not_deleted(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    """A fresh reservation whose job row appears later keeps its cells and the job decides."""
    code = await make_sheet(session)
    (page,) = await do_reserve(session, [existing(code, count=2)], 2)
    await sweep_orphan_reservations(async_session_factory)
    await add_job(session, page.job_id, "queued")

    await sweep_orphan_reservations(async_session_factory)

    assert set(states(await read_cells(async_session_factory)).values()) == {"reserved"}


async def test_sweep_done_job_sets_id_printed(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    (page,) = await do_reserve(session, [new("cell")], 2)
    await add_job(session, page.job_id, "done", sheet_id=page.sheet_id)
    async with async_session_factory() as s:
        await s.execute(update(SheetCell).values(updated_at=datetime.now(UTC) - timedelta(hours=1)))
        await s.commit()

    await sweep_orphan_reservations(async_session_factory)

    assert (await read_sheet(async_session_factory)).id_printed is True
    assert (await read_sheet(async_session_factory)).last_used_at is not None


async def age_cells(factory: Factory, days: int = 40) -> None:
    async with factory() as s:
        await s.execute(
            update(SheetCell).values(updated_at=datetime.now(UTC) - timedelta(days=days))
        )
        await s.commit()


async def test_purged_job_row_never_frees_a_printed_page(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    """T5-1: retention deletes the row of a done job whose handler call was lost; the sweep
    must then say "unconfirmed", not free cells that carry a printed label."""
    code = await make_sheet(session)
    (page,) = await do_reserve(session, [existing(code)], 3)
    await age_cells(async_session_factory)
    assert page.job_id  # the jobs row never exists here: it was purged before the sweep

    await sweep_orphan_reservations(async_session_factory)

    assert set(states(await read_cells(async_session_factory)).values()) == {"unconfirmed"}


async def test_retention_keeps_a_job_with_reserved_cells(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    from app.repositories import jobs as jobs_repo

    code = await make_sheet(session)
    (page,) = await do_reserve(session, [existing(code)], 3)
    old = datetime.now(UTC) - timedelta(days=40)
    await add_job(session, page.job_id, "done", finished_at=old)
    plain = uuid4()
    await add_job(session, plain, "done", finished_at=old)  # no cells: nothing protects it

    async with async_session_factory() as s:
        deleted = await jobs_repo.evict_terminal_older_than(s, timedelta(days=30))

    assert deleted == 1
    async with async_session_factory() as s:
        ids = set((await s.execute(select(Job.id))).scalars().all())
    assert ids == {page.job_id}


async def test_retention_evicts_once_the_cells_are_settled(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    """Counter-check: the protection ends with the reservation."""
    from app.repositories import jobs as jobs_repo

    code = await make_sheet(session)
    (page,) = await do_reserve(session, [existing(code)], 3)
    await add_job(session, page.job_id, "done", finished_at=datetime.now(UTC) - timedelta(days=40))
    await SheetCellsOutcome(async_session_factory, None).on_completed(page.job_id)

    async with async_session_factory() as s:
        assert await jobs_repo.evict_terminal_older_than(s, timedelta(days=30)) == 1


@pytest.mark.parametrize("first", ["clean_failure", "unknown"])
async def test_late_completed_changes_nothing_for_a_margin_job(
    session: AsyncSession, async_session_factory: Factory, first: str
) -> None:
    """T5-2: id_printed is set only by the call that moves cells reserved -> used."""
    (page,) = await do_reserve(session, [new("margin")], 2)
    await add_job(session, page.job_id, margin_id=True, sheet_id=page.sheet_id)
    handler = SheetCellsOutcome(async_session_factory, None)
    if first == "clean_failure":
        await handler.on_ended(page.job_id, state="failed", started=False, error_code="ipp_aborted")
    else:
        await handler.on_unknown(page.job_id)
    before = states(await read_cells(async_session_factory))

    await handler.on_completed(page.job_id)

    assert states(await read_cells(async_session_factory)) == before
    assert (await read_sheet(async_session_factory)).id_printed is False


async def test_sweep_stamps_last_used_with_the_jobs_finish_time(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    code = await make_sheet(session)
    (page,) = await do_reserve(session, [existing(code)], 2)
    finished = datetime.now(UTC) - timedelta(days=2)
    await add_job(session, page.job_id, "done", finished_at=finished)
    await age_cells(async_session_factory, days=2)

    await sweep_orphan_reservations(async_session_factory)

    stamp = (await read_sheet(async_session_factory)).last_used_at
    assert stamp is not None
    assert abs(stamp.replace(tzinfo=UTC) - finished) < timedelta(seconds=5)


# ---------------------------------------------------------------------------- feed mark (5c)


async def test_completed_job_sets_feed_mark_printed(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    (page,) = await do_reserve(session, [new("manual")], 2)
    await add_job(session, page.job_id, sheet_id=page.sheet_id, feed_mark=True)
    handler = SheetCellsOutcome(async_session_factory, None)

    await handler.on_completed(page.job_id)

    sheet = await read_sheet(async_session_factory)
    assert sheet.feed_mark_printed is True
    assert sheet.id_printed is False  # its own flag: a manual sheet never sets the ID's
    assert set(states(await read_cells(async_session_factory)).values()) == {"used"}


async def test_completed_job_without_mark_leaves_it_false(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    (page,) = await do_reserve(session, [new("manual")], 2)
    await add_job(session, page.job_id, sheet_id=page.sheet_id, feed_mark=False)
    await SheetCellsOutcome(async_session_factory, None).on_completed(page.job_id)
    assert (await read_sheet(async_session_factory)).feed_mark_printed is False


async def test_clean_failure_leaves_the_mark_false(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    (page,) = await do_reserve(session, [new("manual")], 2)
    await add_job(session, page.job_id, sheet_id=page.sheet_id, feed_mark=True)
    handler = SheetCellsOutcome(async_session_factory, None)

    await handler.on_ended(page.job_id, state="failed", started=False, error_code="ipp_aborted")

    assert (await read_sheet(async_session_factory)).feed_mark_printed is False


async def test_resolve_printed_sets_the_mark_not_printed_does_not(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    code = await make_sheet(session)
    (page,) = await do_reserve(session, [existing(code, count=2)], 2)
    await add_job(session, page.job_id, sheet_id=page.sheet_id, feed_mark=True)
    handler = SheetCellsOutcome(async_session_factory, None)
    await handler.on_ended(page.job_id, state="failed", started=True, error_code="interrupted")
    assert (await read_sheet(async_session_factory)).feed_mark_printed is False

    async with async_session_factory() as s:
        await ss.resolve_cells(s, code, [1], "not_printed", actor="tester")
    assert (await read_sheet(async_session_factory)).feed_mark_printed is False

    async with async_session_factory() as s:
        await ss.resolve_cells(s, code, [2], "printed", actor="tester")
    assert (await read_sheet(async_session_factory)).feed_mark_printed is True


async def test_resolve_printed_without_mark_job_leaves_it_false(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    code = await make_sheet(session)
    (page,) = await do_reserve(session, [existing(code, count=2)], 2)
    await add_job(session, page.job_id, sheet_id=page.sheet_id, feed_mark=False)
    await SheetCellsOutcome(async_session_factory, None).on_unknown(page.job_id)

    async with async_session_factory() as s:
        await ss.resolve_cells(s, code, [1, 2], "printed", actor="tester")

    assert (await read_sheet(async_session_factory)).feed_mark_printed is False


@pytest.mark.parametrize("first", ["clean_failure", "unknown"])
async def test_late_completed_leaves_the_mark_false(
    session: AsyncSession, async_session_factory: Factory, first: str
) -> None:
    """T5-2 for the new flag: a late call finds no reserved row and changes nothing."""
    (page,) = await do_reserve(session, [new("manual")], 2)
    await add_job(session, page.job_id, sheet_id=page.sheet_id, feed_mark=True)
    handler = SheetCellsOutcome(async_session_factory, None)
    if first == "clean_failure":
        await handler.on_ended(page.job_id, state="failed", started=False, error_code="ipp_aborted")
    else:
        await handler.on_unknown(page.job_id)

    await handler.on_completed(page.job_id)

    assert (await read_sheet(async_session_factory)).feed_mark_printed is False


async def test_sweep_done_job_sets_the_mark(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    (page,) = await do_reserve(session, [new("manual")], 2)
    await add_job(session, page.job_id, "done", sheet_id=page.sheet_id, feed_mark=True)
    async with async_session_factory() as s:
        await s.execute(update(SheetCell).values(updated_at=datetime.now(UTC) - timedelta(hours=1)))
        await s.commit()

    await sweep_orphan_reservations(async_session_factory)

    assert (await read_sheet(async_session_factory)).feed_mark_printed is True


async def test_sweep_unconfirmed_and_freed_leave_the_mark_false(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    (page,) = await do_reserve(session, [new("manual")], 2)
    await add_job(
        session, page.job_id, "failed", sheet_id=page.sheet_id, feed_mark=True,
        result={"started": True},
    )  # fmt: skip
    async with async_session_factory() as s:
        await s.execute(update(SheetCell).values(updated_at=datetime.now(UTC) - timedelta(hours=1)))
        await s.commit()

    await sweep_orphan_reservations(async_session_factory)

    assert (await read_sheet(async_session_factory)).feed_mark_printed is False


async def test_resolving_the_id_cell_sets_both_flags(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    """The ID-only job of a ``cell`` sheet carries the mark: its hub cell sets both flags, the
    mark check is separate from the ID check and not an ``elif``."""
    (page,) = await do_reserve(session, [new("cell")], 0)
    await add_job(session, page.job_id, sheet_id=page.sheet_id, feed_mark=True)
    handler = SheetCellsOutcome(async_session_factory, None)
    await handler.on_unknown(page.job_id)
    sheet = await read_sheet(async_session_factory)
    assert (sheet.id_printed, sheet.feed_mark_printed) == (False, False)
    code = sheet.code

    async with async_session_factory() as s:
        await ss.resolve_cells(s, code, [1], "printed", actor="tester")

    after = await read_sheet(async_session_factory)
    assert (after.id_printed, after.feed_mark_printed) == (True, True)


async def test_completed_cell_sheet_job_sets_both_flags(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    (page,) = await do_reserve(session, [new("cell")], 0)
    await add_job(session, page.job_id, sheet_id=page.sheet_id, feed_mark=True)

    await SheetCellsOutcome(async_session_factory, None).on_completed(page.job_id)

    after = await read_sheet(async_session_factory)
    assert (after.id_printed, after.feed_mark_printed) == (True, True)


# ------------------------------------------------- unconfirmed carriers (F3-1, review I1)


async def _interrupted_margin_job(
    session: AsyncSession, factory: Factory, placement: str = "margin"
) -> Any:
    """A new sheet's first page, carrying the margin ID and the feed mark, interrupted."""
    (page,) = await do_reserve(session, [new(placement)], 2)
    await add_job(
        session,
        page.job_id,
        "failed",
        margin_id=placement == "margin",
        feed_mark=True,
        sheet_id=page.sheet_id,
        result={"started": True},
        error="print_interrupted",
        finished_at=datetime.now(UTC),
    )
    await SheetCellsOutcome(factory, None).on_ended(
        page.job_id, state="failed", started=True, error_code="print_interrupted"
    )
    assert set(states(await read_cells(factory)).values()) == {"unconfirmed"}
    return page


async def test_interrupted_margin_job_blocks_a_second_id_and_mark(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    """Review I1: the first page may be on the sheet, so a second print before anyone resolves
    the cells draws neither the margin ID nor the feed mark again (spec 10.2a)."""
    page = await _interrupted_margin_job(session, async_session_factory)

    (second,) = await do_reserve(session, [existing(page.sheet_code)], 1)

    assert second.margin_id is False
    assert second.feed_mark is None


async def test_resolving_printed_sets_the_flags_and_nothing_is_reprinted(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    page = await _interrupted_margin_job(session, async_session_factory)
    unconfirmed = sorted(states(await read_cells(async_session_factory)))

    await ss.resolve_cells(session, page.sheet_code, unconfirmed, "printed", actor="tester")

    sheet = await read_sheet(async_session_factory)
    assert (sheet.id_printed, sheet.feed_mark_printed) == (True, True)
    (later,) = await do_reserve(session, [existing(page.sheet_code)], 1)
    assert later.margin_id is False
    assert later.feed_mark is None


async def test_resolving_not_printed_makes_the_next_job_print_both(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    page = await _interrupted_margin_job(session, async_session_factory)
    unconfirmed = sorted(states(await read_cells(async_session_factory)))

    await ss.resolve_cells(session, page.sheet_code, unconfirmed, "not_printed", actor="tester")

    sheet = await read_sheet(async_session_factory)
    assert (sheet.id_printed, sheet.feed_mark_printed) == (False, False)
    (next_page,) = await do_reserve(session, [existing(page.sheet_code)], 1)
    assert next_page.margin_id is True
    assert next_page.feed_mark is not None


async def test_unconfirmed_id_cell_job_blocks_a_second_feed_mark_on_a_cell_sheet(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    """The ``cell`` placement: the hub cell already blocks a second ID cell; the feed mark the
    same job carried must not come back either."""
    page = await _interrupted_margin_job(session, async_session_factory, placement="cell")

    (second,) = await do_reserve(session, [existing(page.sheet_code)], 1)

    assert second.id_cell is None
    assert second.feed_mark is None


async def test_retention_keeps_a_job_with_unconfirmed_cells(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    """F3-1: the row stays until the cells are resolved, so "printed" can still read it."""
    from app.repositories import jobs as jobs_repo

    page = await _interrupted_margin_job(session, async_session_factory)
    async with async_session_factory() as s:
        await s.execute(
            update(Job)
            .where(Job.id == page.job_id)
            .values(finished_at=datetime.now(UTC) - timedelta(days=40))
        )
        await s.commit()

    async with async_session_factory() as s:
        assert await jobs_repo.evict_terminal_older_than(s, timedelta(days=30)) == 0
    unconfirmed = sorted(states(await read_cells(async_session_factory)))
    await ss.resolve_cells(session, page.sheet_code, unconfirmed, "printed", actor="tester")
    assert (await read_sheet(async_session_factory)).id_printed is True
    async with async_session_factory() as s:  # counter-check: resolved cells end the protection
        assert await jobs_repo.evict_terminal_older_than(s, timedelta(days=30)) == 1
