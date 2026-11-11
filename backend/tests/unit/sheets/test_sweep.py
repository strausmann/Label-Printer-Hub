"""The periodic reservation sweep (266-04): cells of jobs that ended while the hub ran.

The outcome handler settles a sheet page's cells when its job ends. When that call is lost or
raises, the cells stay ``reserved`` until the next start (the startup sweep). The periodic sweep
settles them while the hub runs, with the startup sweep's rules, but only for a job that is
over in the database, no longer known to the queue and not touched for ``min_age_s``. A row
without a job is left to the startup sweep (a running hub may be saving that job right now).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from app.models.job import Job
from app.repositories import sheets as sheets_repo
from app.sheets import type_service as ts
from app.sheets.sweep import SheetReservationSweep
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.unit.sheets.test_outcome import (
    add_job,
    read_cells,
    seed_reserved,
    states,
    sweep_world,
)
from tests.unit.sheets.test_reservation import G48, FakeBus, _fields, make_sheet

Factory = async_sessionmaker[AsyncSession]


@pytest_asyncio.fixture
async def session(async_session_factory: Factory) -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as s:
        await ts.create_type(s, _fields(), G48, actor="tester")
        yield s


class FakeQueue:
    """``has_job`` as the print queue answers it: the ids it tracks in memory."""

    def __init__(self) -> None:
        self.tracked: set[UUID] = set()

    def has_job(self, job_id: str | UUID) -> bool:
        return UUID(str(job_id)) in self.tracked


async def age_jobs(factory: Factory, *, seconds: int = 3600) -> None:
    async with factory() as s:
        await s.execute(
            update(Job).values(updated_at=datetime.now(UTC) - timedelta(seconds=seconds))
        )
        await s.commit()


def _sweep(factory: Factory, queue: FakeQueue, bus: Any = None, **kw: Any) -> SheetReservationSweep:
    return SheetReservationSweep(factory, queue, bus, **kw)


async def test_sweep_releases_terminal_jobs_only(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    world = await sweep_world(session, async_session_factory)
    await age_jobs(async_session_factory)
    bus = FakeBus()

    report = await _sweep(async_session_factory, FakeQueue(), bus).run_once()

    got = states(await read_cells(async_session_factory))
    expected = {
        "missing": "reserved",  # no job row: the startup sweep decides, never a running hub
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
    assert (report.used, report.unconfirmed, report.freed) == (1, 3, 2)
    assert report.untouched == 2 and report.spared == 1
    (event,) = bus.events
    assert event.data["changed"] == sorted(
        c for n, c in world.items() if n not in ("missing", "queued", "printing")
    )


async def test_sweep_keeps_cells_of_jobs_still_in_queue(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    """A row that looks over (an old ``done``) of a job the queue still tracks is the job's to
    settle: its outcome call may be on its way."""
    code = await make_sheet(session)
    job_id = uuid4()
    await add_job(session, job_id, "done")
    await seed_reserved(session, async_session_factory, code, 1, job_id)
    await age_jobs(async_session_factory)
    queue = FakeQueue()
    queue.tracked.add(job_id)

    report = await _sweep(async_session_factory, queue).run_once()

    assert states(await read_cells(async_session_factory)) == {1: "reserved"}
    assert report.untouched == 1 and report.used == 0


async def test_sweep_keeps_cells_of_a_job_the_queue_takes_up_during_the_sweep(
    session: AsyncSession, async_session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Concurrency: the queue takes the job up after the sweep read the cells (between the
    snapshot and the write). The queue is asked at decision time, not before the read."""
    code = await make_sheet(session)
    job_id = uuid4()
    await add_job(session, job_id, "done")
    await seed_reserved(session, async_session_factory, code, 1, job_id)
    await age_jobs(async_session_factory)
    queue = FakeQueue()
    real = sheets_repo.jobs_by_id

    async def read_then_track(s: AsyncSession, ids: Any) -> dict[UUID, Job]:
        found = await real(s, ids)
        queue.tracked.add(job_id)  # e.g. a recovery re-enqueued it meanwhile
        return found

    monkeypatch.setattr(sheets_repo, "jobs_by_id", read_then_track)

    await _sweep(async_session_factory, queue).run_once()

    assert states(await read_cells(async_session_factory)) == {1: "reserved"}


async def test_sweep_skips_young_jobs(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    """A job that ended moments ago is the outcome handler's: the sweep waits ``min_age_s``."""
    code = await make_sheet(session)
    job_id = uuid4()
    await add_job(session, job_id, "done")  # updated now
    await seed_reserved(session, async_session_factory, code, 1, job_id)

    report = await _sweep(async_session_factory, FakeQueue(), min_age_s=600).run_once()
    assert states(await read_cells(async_session_factory)) == {1: "reserved"}
    assert report.untouched == 1

    # Counter-check: the age alone kept it.
    await _sweep(async_session_factory, FakeQueue(), min_age_s=0).run_once()
    assert states(await read_cells(async_session_factory)) == {1: "used"}


async def test_the_loop_sweeps_on_its_interval_and_stops(
    session: AsyncSession, async_session_factory: Factory
) -> None:
    code = await make_sheet(session)
    job_id = uuid4()
    await seed_reserved(session, async_session_factory, code, 1, job_id)
    sweep = _sweep(async_session_factory, FakeQueue(), interval_s=0, min_age_s=0)
    await sweep.start()
    try:
        await add_job(session, job_id, "cancelled")  # ends after the loop started
        async with asyncio.timeout(5):
            while await read_cells(async_session_factory):
                await asyncio.sleep(0.02)
    finally:
        await sweep.stop()
    assert sweep._task is None


async def test_a_failing_sweep_is_logged_and_the_loop_goes_on(
    async_session_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[int] = []

    async def boom(*_a: Any, **_k: Any) -> Any:
        calls.append(1)
        raise RuntimeError("database is locked")

    monkeypatch.setattr(sheets_repo, "all_reserved_cells", boom)
    sweep = _sweep(async_session_factory, FakeQueue(), interval_s=0)
    caplog.set_level(logging.ERROR, logger="app.sheets.sweep")
    await sweep.start()
    try:
        async with asyncio.timeout(5):
            while len(calls) < 2:
                await asyncio.sleep(0.01)
    finally:
        await sweep.stop()
    assert any("sweep failed" in r.getMessage() for r in caplog.records)


async def test_stop_before_start_and_twice_is_harmless(async_session_factory: Factory) -> None:
    sweep = _sweep(async_session_factory, FakeQueue())
    await sweep.stop()
    await sweep.start()
    await sweep.start()  # idempotent
    await sweep.stop()
    await sweep.stop()


def test_bad_parameters_are_refused(async_session_factory: Factory) -> None:
    with pytest.raises(ValueError):
        _sweep(async_session_factory, FakeQueue(), interval_s=-1)
    with pytest.raises(ValueError):
        _sweep(async_session_factory, FakeQueue(), min_age_s=-1)
