"""A sheet page job through the real lifespan: its reserved cells follow the outcome (D15).

The real queue, the real ``SheetCellsOutcome`` (registered by the lifespan), the fake IPP
printer and SQLite. The renderer is a stub: this is about the cells, not the PDF.

The runner writes ``done`` and ends the job in memory *before* it calls the outcome handler
(C15), so no test waits on the job state alone: each polls the cells, bounded.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from typing import Any
from uuid import UUID

import pytest
from app.models.job import Job as DbJob
from app.models.printer import Printer
from app.models.sheet import Sheet, SheetCell
from app.services import page_jobs
from app.services.page_jobs import PagePayload
from app.sheets import type_service as ts
from httpx import ASGITransport
from sqlalchemy import select

from tests.helpers.fake_ipp_printer import FAKE_URI, FakeIppPrinter
from tests.helpers.page_jobs import PDF, payload
from tests.unit.sheets.test_reservation import (
    G48,
    MARGIN,
    ItemMeta,
    _fields,
    existing,
    make_sheet,
    reserve,
)

TIMEOUT_S = 10.0


@pytest.fixture(autouse=True)
def _stub_renderer(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A stub renderer; the handler registry is restored (the lifespan registers its own)."""
    monkeypatch.setitem(page_jobs._RENDERERS, "sheet_page", lambda _p: PDF)
    monkeypatch.setitem(page_jobs._HANDLERS, "sheet_page", page_jobs._NOOP)
    yield


async def _until(predicate: Callable[[], Awaitable[bool]]) -> None:
    async with asyncio.timeout(TIMEOUT_S):
        while not await predicate():
            await asyncio.sleep(0.02)


def _app(fake: FakeIppPrinter) -> Any:
    from app.main import create_app

    app = create_app()
    app._app.state.ipp_transport_factory = lambda _uri: ASGITransport(app=fake)
    return app._app


async def _printer() -> UUID:
    import app.db.engine as eng

    async with eng.async_session() as s:
        printer = Printer(
            name="Page",
            slug="page-sheets",
            model="x",
            backend="ipp",
            connection={"uri": FAKE_URI, "tls_verify": True},
            enabled=True,
        )
        s.add(printer)
        await s.commit()
        return printer.id


async def _reserve(count: int = 9) -> tuple[UUID, str]:
    """A sheet with 17 used cells and ``count`` cells reserved for a job; returns both ids."""
    import app.db.engine as eng

    async with eng.async_session() as s:
        await ts.create_type(s, _fields(), G48, actor="tester")
        code = await make_sheet(s, used=17)
        (page,) = await reserve(
            s,
            placements=[existing(code)],
            items=[ItemMeta("api", f"item {i}", f"ref-{i}") for i in range(count)],
            expected=None,
            hw_margins_hmm=None,
            margin=MARGIN,
            required_type_key=None,
            actor="tester",
        )
        return page.job_id, code


def _sheet_payload(code: str) -> PagePayload:
    return payload("sheet_page", sheet_code=code)


async def _states() -> list[str]:
    import app.db.engine as eng

    async with eng.async_session() as s:
        rows = (await s.execute(select(SheetCell).where(SheetCell.cell_no > 17))).scalars().all()
    return sorted(r.state for r in rows)


def _cells_are(*expected: str) -> Callable[[], Awaitable[bool]]:
    async def _check() -> bool:
        return await _states() == sorted(expected)

    return _check


async def _row(job_id: UUID) -> DbJob:
    import app.db.engine as eng

    async with eng.async_session() as s:
        row = await s.get(DbJob, job_id)
        assert row is not None
        return row


async def _submit(app: Any, pid: UUID, jid: UUID, code: str) -> None:
    await app.state.print_queue.submit_page_job(
        pid, _sheet_payload(code), api_key_id=None, source_ip=None, job_id=jid
    )


async def test_completed_job_turns_its_cells_used() -> None:
    fake = FakeIppPrinter(job_script=[3, 5, 9])
    pid = await _printer()
    jid, code = await _reserve()
    assert await _states() == ["reserved"] * 9
    app = _app(fake)
    async with app.router.lifespan_context(app):
        await _submit(app, pid, jid, code)
        await _until(_cells_are(*["used"] * 9))
        assert (await _row(jid)).state == "done"
    import app.db.engine as eng

    async with eng.async_session() as s:
        assert len((await s.execute(select(SheetCell))).scalars().all()) == 26  # acceptance 1


async def test_cancelled_before_it_started_frees_its_cells() -> None:
    fake = FakeIppPrinter(job_script=[3])  # stays pending at the printer
    pid = await _printer()
    jid, code = await _reserve()
    app = _app(fake)
    async with app.router.lifespan_context(app):
        await _submit(app, pid, jid, code)

        async def _tracked() -> bool:
            return app.state.print_queue._page_runner.is_tracking(jid)

        await _until(_tracked)
        assert await app.state.print_queue.cancel(str(jid))
        await _until(_cells_are())  # acceptance 2: the rows are gone


async def test_cancelled_after_it_started_is_unconfirmed() -> None:
    fake = FakeIppPrinter(job_script=[5])  # printing: ink may be on paper
    pid = await _printer()
    jid, code = await _reserve()
    app = _app(fake)
    async with app.router.lifespan_context(app):
        await _submit(app, pid, jid, code)

        async def _started() -> bool:
            return bool(((await _row(jid)).result or {}).get("started"))

        await _until(_started)
        assert await app.state.print_queue.cancel(str(jid))
        await _until(_cells_are(*["unconfirmed"] * 9))


async def test_restart_mid_job_ends_used() -> None:
    """Acceptance 17: ``[5]`` -> restart -> ``[9]``; the cells stay reserved across it."""
    fake = FakeIppPrinter(job_script=[5])
    pid = await _printer()
    jid, code = await _reserve()
    first = _app(fake)
    async with first.router.lifespan_context(first):
        await _submit(first, pid, jid, code)

        async def _started() -> bool:
            return bool(((await _row(jid)).result or {}).get("started"))

        await _until(_started)
    assert await _states() == ["reserved"] * 9  # the shutdown settled nothing

    fake.job_script = [5, 9]
    second = _app(fake)
    async with second.router.lifespan_context(second):
        await _until(_cells_are(*["used"] * 9))
    assert [r.operation for r in fake.received].count("Print-Job") == 1


async def test_restart_during_upload_settles_through_on_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The handler is registered before ``queue.start()``: recovery calls ``on_unknown`` from
    inside ``start()``. The sweep is switched off, so only that path can have made the cells
    ``unconfirmed`` (C5)."""
    import app.main as main_module

    swept: list[int] = []

    async def no_sweep(*_a: Any, **_k: Any) -> None:
        swept.append(1)

    monkeypatch.setattr(main_module, "sweep_orphan_reservations", no_sweep)
    fake = FakeIppPrinter(job_script=[9])
    pid = await _printer()
    jid, code = await _reserve()
    import app.db.engine as eng

    async with eng.async_session() as s:  # what a crash during the upload leaves behind
        s.add(
            DbJob(
                id=jid,
                printer_id=pid,
                template_key=None,
                payload=_sheet_payload(code).model_dump(mode="json"),
                state="printing",
                result={"phase": "uploading", "started": False},
            )
        )
        await s.commit()
    app = _app(fake)
    async with app.router.lifespan_context(app):
        await _until(_cells_are(*["unconfirmed"] * 9))
    assert swept == [1]  # the sweep did run (as the stub), and had no part in it
    assert "Print-Job" not in [r.operation for r in fake.received]
    assert (await _row(jid)).state == "failed_restart"


async def test_startup_sweep_settles_a_job_that_ended_while_the_hub_was_down() -> None:
    fake = FakeIppPrinter(job_script=[9])
    pid = await _printer()
    jid, code = await _reserve()
    import app.db.engine as eng

    async with eng.async_session() as s:
        s.add(
            DbJob(
                id=jid,
                printer_id=pid,
                template_key=None,
                payload=_sheet_payload(code).model_dump(mode="json"),
                state="done",
            )
        )
        await s.commit()
    app = _app(fake)
    async with app.router.lifespan_context(app):
        await _until(_cells_are(*["used"] * 9))
    async with eng.async_session() as s:
        assert (await s.execute(select(Sheet))).scalar_one().last_used_at is not None


async def test_startup_sweep_runs_before_the_first_retention_eviction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T5-1 b: retention must not delete a job row the sweep still has to read."""
    import app.main as main_module
    from app.services.cleanup_task import CleanupTask

    order: list[str] = []
    real_sweep = main_module.sweep_orphan_reservations
    real_start = CleanupTask.start

    async def sweep(*a: Any, **k: Any) -> Any:
        order.append("sweep")
        return await real_sweep(*a, **k)

    async def start(self: CleanupTask) -> None:
        order.append("cleanup")
        await real_start(self)

    monkeypatch.setattr(main_module, "sweep_orphan_reservations", sweep)
    monkeypatch.setattr(CleanupTask, "start", start)
    app = _app(FakeIppPrinter())
    async with app.router.lifespan_context(app):
        pass

    assert order == ["sweep", "cleanup"]


async def test_lifespan_unregisters_its_handler_at_shutdown() -> None:
    app = _app(FakeIppPrinter())
    async with app.router.lifespan_context(app):
        assert "sheet_page" in page_jobs._HANDLERS
    assert "sheet_page" not in page_jobs._HANDLERS
