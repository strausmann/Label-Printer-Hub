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


# ---------------------------------------------------------------- feed-direction mark (Task 5c)


def _mark_payload(page: Any, code: str) -> PagePayload:
    """What Task 7 will store for a reserved page: the cells and, if decided, the mark."""
    from dataclasses import asdict

    from app.schemas.content_type import ContentType
    from app.schemas.label_data import LabelData
    from app.sheets.sheet_page import (
        SheetCellPayload,
        SheetPageDetail,
        feed_mark_payload,
    )

    cells = [
        SheetCellPayload(
            cell=a.cell,
            content_type=ContentType.TEXT_TWO_LINES,
            label_data=LabelData(source_app="t", primary_id=f"A-{a.cell}", title="Item").model_dump(
                mode="json"
            ),
            mapped=False,
        )
        for a in page.assignments
    ]
    detail = SheetPageDetail(
        sheet_id=page.sheet_id,
        sheet_code=code,
        type_key="avery-l4736rev",
        type_version_id=page.type_version_id,
        geometry=asdict(G48),
        allow_qr=True,
        cells=cells,
        feed_mark=feed_mark_payload(page.feed_mark) if page.feed_mark is not None else None,
        job_summary={"sheet_code": code, "cell_count": len(cells)},
    )
    return PagePayload(
        kind="sheet_page",
        media="A4",
        tray="auto",
        render_dpi=300,
        job_name=f"Sheet {code}",
        calibration=None,
        detail=detail.model_dump(mode="json"),
    )


async def _reserve_manual(margin: Any, n: int = 2) -> tuple[Any, str]:
    import app.db.engine as eng

    async with eng.async_session() as s:
        code = await make_sheet(s)
        (page,) = await reserve(
            s,
            placements=[existing(code)],
            items=[ItemMeta("api", f"item {i}", f"ref-{i}") for i in range(n)],
            expected=None,
            hw_margins_hmm=None,
            margin=margin,
            required_type_key=None,
            actor="tester",
        )
        return page, code


async def _sheet_row() -> Sheet:
    import app.db.engine as eng

    async with eng.async_session() as s:
        return (await s.execute(select(Sheet))).scalar_one()


async def test_only_the_first_job_of_a_sheet_carries_the_mark() -> None:
    """Acceptance 7a: two jobs onto a fresh ``manual`` sheet; the mark is on the first only."""
    import app.db.engine as eng

    fake = FakeIppPrinter(job_script=[3, 5, 9])
    pid = await _printer()
    async with eng.async_session() as s:
        await ts.create_type(s, _fields(), G48, actor="tester")
    page1, code = await _reserve_manual(MARGIN)
    assert page1.feed_mark is not None
    app = _app(fake)
    async with app.router.lifespan_context(app):
        await app.state.print_queue.submit_page_job(
            pid, _mark_payload(page1, code), api_key_id=None, source_ip=None, job_id=page1.job_id
        )

        async def _flag() -> bool:
            return (await _sheet_row()).feed_mark_printed

        await _until(_flag)
        first = await _row(page1.job_id)
        assert first.payload["detail"]["feed_mark"]["text"] == "▲ Top \u2013 this edge first"
        async with eng.async_session() as s:
            (page2,) = await reserve(
                s,
                placements=[existing(code)],
                items=[ItemMeta("api", "again", "ref")],
                expected=None,
                hw_margins_hmm=None,
                margin=MARGIN,
                required_type_key=None,
                actor="tester",
            )
        assert page2.feed_mark is None
        await app.state.print_queue.submit_page_job(
            pid, _mark_payload(page2, code), api_key_id=None, source_ip=None, job_id=page2.job_id
        )
        await _until(_cells_are_all("used", 3))
        second = await _row(page2.job_id)
        assert second.payload["detail"]["feed_mark"] is None


def _cells_are_all(state: str, count: int) -> Callable[[], Awaitable[bool]]:
    async def _check() -> bool:
        import app.db.engine as eng

        async with eng.async_session() as s:
            rows = (await s.execute(select(SheetCell))).scalars().all()
        return len(rows) == count and {r.state for r in rows} == {state}

    return _check


async def test_mark_language_fixed_at_reservation(monkeypatch: pytest.MonkeyPatch) -> None:
    """The mark's text is decided when the reservation runs: a later change of the hub
    language does not reach the PDF the printer receives."""
    from dataclasses import replace

    import app.db.engine as eng
    from app.sheets.sheet_page import render_sheet_page

    from tests.helpers import pdf_inspect as pi

    monkeypatch.setitem(
        page_jobs._RENDERERS, "sheet_page", lambda p: render_sheet_page(p, compress=False)
    )
    fake = FakeIppPrinter(job_script=[3, 5, 9])
    pid = await _printer()
    async with eng.async_session() as s:
        await ts.create_type(s, _fields(), G48, actor="tester")
    app = _app(fake)
    async with app.router.lifespan_context(app):
        store = app.state.settings_store
        async with eng.async_session() as s:
            await store.set_many(s, {"general.language": "de"})
        page, code = await _reserve_manual(replace(MARGIN, language=store.get("general.language")))
        payload = _mark_payload(page, code)
        async with eng.async_session() as s:
            await store.set_many(s, {"general.language": "en"})
        assert store.get("general.language") == "en"
        await app.state.print_queue.submit_page_job(
            pid, payload, api_key_id=None, source_ip=None, job_id=page.job_id
        )
        await _until(_cells_are_all("used", 2))

    (doc,) = [r.document for r in fake.received if r.operation == "Print-Job"]
    assert "▲ Oben \u2013 diese Kante zuerst" in pi.texts(doc)
    assert "▲ Top \u2013 this edge first" not in pi.texts(doc)


# ---------------------------------------------------------------------------- 266-09, 266-13


async def test_print_interrupted_logs_cause_type(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The page's row is committed, then its save raises: the request answers 502
    ``print_interrupted``, the row ends ``failed`` (no restart prints it), the cells are free,
    and the cause is logged by type and batch, never with the error text (it may carry the
    payload: a database error quotes its parameters)."""
    import logging

    from tests.integration.api.test_sheet_print_api import _body, _cells, _sheet, running

    qr = "https://r.example.invalid/0"
    async with running() as rig:
        store = rig.app.state.print_queue._store
        real = store.save_queued

        async def saved_then_raises(job: Any) -> None:
            await real(job)
            raise RuntimeError(f"database is locked [parameters: {qr}]")

        monkeypatch.setattr(store, "save_queued", saved_then_raises)
        code = await _sheet()
        caplog.set_level(logging.INFO)
        resp = await rig.print(_body(code, 3))

        assert resp.status_code == 502, resp.text
        detail = resp.json()["detail"]
        assert detail["error_code"] == "print_interrupted"
        batch_id = detail["error_detail"]["batch_id"]
        (job_id,) = detail["error_detail"]["job_ids"]
        row = await _row(UUID(job_id))
        assert row.state == "failed" and (row.error or "").startswith("print_interrupted:")
        await _until(lambda: _no_cells(_cells))
    records = [r for r in caplog.records if batch_id in r.getMessage()]
    assert records, caplog.text
    assert any("RuntimeError" in r.getMessage() for r in records)
    assert qr not in caplog.text


async def test_partial_print_interrupted_marks_cells(monkeypatch: pytest.MonkeyPatch) -> None:
    """267-14: the page job is queued (its row is committed, the printer receives it) and the
    print then fails before the route has the page: the request answers 502 ``print_interrupted``
    and names the job, the batch keeps it, and the page is not given up. It prints, and its
    cells are marked ``used`` instead of being freed under it."""
    import app.db.engine as eng
    from app.models.print_batch import PrintBatch
    from app.sheets import print_service

    from tests.integration.api.test_sheet_print_api import _body, _sheet, _used, running

    def raising(_page: Any) -> Any:
        raise RuntimeError("the page was queued, then this broke")

    async with running() as rig:
        code = await _sheet()
        monkeypatch.setattr(print_service, "_printed_page", raising)
        resp = await rig.print(_body(code, 3))

        assert resp.status_code == 502, resp.text
        detail = resp.json()["detail"]
        assert detail["error_code"] == "print_interrupted"
        (job_id,) = detail["error_detail"]["job_ids"]
        # The queued page goes on: the fake printer gets the document, the cells end used.
        await rig.until_sheet(code, _used(1, 2, 3))
        assert [r.operation for r in rig.fake.received].count("Print-Job") == 1
        async with eng.async_session() as s:
            batch = await s.get(PrintBatch, UUID(detail["error_detail"]["batch_id"]))
        assert batch is not None and batch.job_ids == [job_id]
        assert (await _row(UUID(job_id))).error is None


async def _no_cells(cells: Callable[[], Awaitable[list[Any]]]) -> bool:
    return await cells() == []


async def test_reservation_sweep_starts_after_the_runtime_and_stops_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """266-04: the periodic sweep runs while the printers are live, and is the first thing
    stopped, before the producers and the queue it asks."""
    from app.services.printer_runtime import PrinterRuntime
    from app.sheets.sweep import SheetReservationSweep

    order: list[str] = []

    def recording(cls: Any, name: str, label: str) -> None:
        real = getattr(cls, name)

        async def wrapper(self: Any, *a: Any, **k: Any) -> Any:
            order.append(label)
            return await real(self, *a, **k)

        monkeypatch.setattr(cls, name, wrapper)

    recording(PrinterRuntime, "start", "runtime.start")
    recording(PrinterRuntime, "stop", "runtime.stop")
    recording(SheetReservationSweep, "start", "sweep.start")
    recording(SheetReservationSweep, "stop", "sweep.stop")
    app = _app(FakeIppPrinter())
    async with app.router.lifespan_context(app):
        assert isinstance(app.state.sheet_reservation_sweep, SheetReservationSweep)
        assert app.state.sheet_reservation_sweep._queue is app.state.print_queue

    assert order == ["runtime.start", "sweep.start", "sweep.stop", "runtime.stop"]


# ---------------------------------------------------------------- recovery check (263-47)


async def _seed_queued_sheet_page(pid: UUID, *, free_the_cells: bool) -> UUID:
    """A ``queued`` sheet page row as a failed end write leaves it: reserved cells, or (the case
    the check exists for) cells that were freed meanwhile and taken by nobody yet."""
    import app.db.engine as eng
    from sqlalchemy import delete

    async with eng.async_session() as s:
        await ts.create_type(s, _fields(), G48, actor="tester")
    page, code = await _reserve_manual(MARGIN, n=2)
    async with eng.async_session() as s:
        s.add(
            DbJob(
                id=page.job_id,
                printer_id=pid,
                template_key=None,
                payload=_mark_payload(page, code).model_dump(mode="json"),
                state="queued",
            )
        )
        if free_the_cells:
            await s.execute(delete(SheetCell).where(SheetCell.job_id == page.job_id))
        await s.commit()
    return page.job_id


async def test_restart_prints_a_queued_sheet_page_whose_cells_are_still_its_own() -> None:
    fake = FakeIppPrinter(job_script=[9])
    pid = await _printer()
    jid = await _seed_queued_sheet_page(pid, free_the_cells=False)
    app = _app(fake)
    async with app.router.lifespan_context(app):

        async def _done() -> bool:
            return (await _row(jid)).state == "done"

        await _until(_done)
    assert [r.operation for r in fake.received].count("Print-Job") == 1


async def test_restart_refuses_a_queued_sheet_page_whose_cells_were_freed() -> None:
    """The page would print over whatever another print reserved there: it ends ``failed``
    (never started) instead, and nothing reaches the printer."""
    fake = FakeIppPrinter(job_script=[9])
    pid = await _printer()
    jid = await _seed_queued_sheet_page(pid, free_the_cells=True)
    app = _app(fake)
    async with app.router.lifespan_context(app):

        async def _failed() -> bool:
            return (await _row(jid)).state == "failed"

        await _until(_failed)
        await asyncio.sleep(0.1)
    row = await _row(jid)
    assert (row.error or "").startswith("recovery_refused:")
    assert "Print-Job" not in [r.operation for r in fake.received]
