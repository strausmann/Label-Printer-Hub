"""Sheet print: reserve, one page payload per page, queue submission, release (Plan 3, Task 7).

The queue is a recording double; the database, the planner, the reservation and the outcome
rows are real. The end-to-end run with a printer is in ``tests/integration/api``.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Any
from uuid import UUID, uuid4

import app.models  # noqa: F401
import pytest
import pytest_asyncio
from app.calibration import service as calibration_service
from app.calibration.model import CalibrationIn
from app.models.job import Job as DbJob
from app.models.print_batch import PrintBatch
from app.models.sheet import Sheet, SheetCell, SheetIdCounter, SheetTypeVersion
from app.printer_backends.ipp.attributes import Margins
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.schemas.sheet_print import ExpectedPageModel
from app.services.lookup_service import LookupFailedError
from app.services.page_jobs import PagePayload
from app.sheets import print_service, reservation
from app.sheets import type_service as ts
from app.sheets.errors import (
    InsufficientCellsError,
    ItemContentMismatchError,
    ItemLookupFailedError,
    MediaKindMismatchError,
    PlanChangedError,
    PrinterUnavailableError,
    TrayUnknownError,
)
from app.sheets.geometry import Geometry
from app.sheets.planner import MARGIN_TEXT_GAP_HMM
from app.sheets.print_service import page_margin_id_payload
from app.sheets.sheet_page import SheetPageDetail
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.helpers.pdf_inspect import placed_images
from tests.unit.sheets.test_print_service_preview import (
    G48,
    G_SMALL,
    KEY,
    KEY_SMALL,
    FakeLookup,
    Spy,
    fresh,
    grocy,
    make_printer,
    make_sheet,
    on,
    raw,
    record,
    req,
    run_preview,
)

pytestmark = pytest.mark.asyncio


class FakeQueue:
    """Records ``submit_page_job``; can fail on the n-th call (1-based) or for a printer."""

    def __init__(self, fail_on: int | None = None, exc: BaseException | None = None) -> None:
        self.fail_on = fail_on
        self.exc = exc if exc is not None else RuntimeError("queue is down")
        self.submitted: list[tuple[UUID, PagePayload, UUID]] = []
        self.calls = 0
        self.before_submit: Any = None  # awaited with the call number before each submit

    async def submit_page_job(
        self,
        printer_id: UUID,
        payload: PagePayload,
        *,
        api_key_id: UUID | None,
        source_ip: str | None,
        job_id: UUID | None = None,
    ) -> UUID:
        self.calls += 1
        assert job_id is not None
        if self.before_submit is not None:
            await self.before_submit(self.calls, job_id)
        if self.fail_on == self.calls:
            raise self.exc
        self.submitted.append((printer_id, payload, job_id))
        return job_id

    @property
    def payloads(self) -> list[PagePayload]:
        return [p for _, p, _ in self.submitted]

    def detail(self, n: int = 0) -> SheetPageDetail:
        return SheetPageDetail.model_validate(self.payloads[n].detail)


class FakeBus:
    def __init__(self) -> None:
        self.events: list[Any] = []
        self._n = 0

    def next_event_id(self, channel: str) -> int:
        self._n += 1
        return self._n

    def publish(self, channel: str, event: Any) -> None:
        self.events.append(event)


@pytest_asyncio.fixture
async def factory(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    async with async_session_factory() as s:
        await ts.create_type(
            s, ts.TypeFields(KEY, "L4736", "Avery", ["L4736REV-25"], None, None), G48, actor="t"
        )
        await ts.create_type(
            s,
            ts.TypeFields(KEY_SMALL, "L4731", "Avery", ["L4731REV-25"], None, None),
            G_SMALL,
            actor="t",
        )
    yield async_session_factory


@pytest_asyncio.fixture
async def session(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with factory() as s:
        yield s


async def run_print(
    factory: async_sessionmaker[AsyncSession],
    printer: Any,
    request: Any,
    *,
    queue: Any = None,
    lookup: Any = None,
    language: str | None = "en",
    bus: Any = None,
) -> Any:
    return await print_service.print_sheets(
        factory,
        printer=printer,
        request=request,
        lookup=lookup or FakeLookup(),
        queue=queue if queue is not None else FakeQueue(),
        actor="key:test",
        api_key_id=None,
        source_ip="203.0.113.7",
        language=language,
        bus=bus,
    )


async def cell_rows(factory: async_sessionmaker[AsyncSession]) -> list[SheetCell]:
    async with factory() as s:
        return list((await s.execute(select(SheetCell))).scalars().all())


async def count(factory: async_sessionmaker[AsyncSession], model: Any) -> int:
    async with factory() as s:
        return int((await s.execute(select(func.count()).select_from(model))).scalar_one())


async def counters(factory: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    async with factory() as s:
        rows = (await s.execute(select(SheetIdCounter))).scalars().all()
    return {r.prefix: r.next_value for r in rows}


# ---------------------------------------------------------------------------- the happy path


async def test_print_reserves_builds_one_payload_and_submits(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    printer = await make_printer(session, record(dpis=[300, 600]))
    code = await make_sheet(session, used=17)
    queue = FakeQueue()

    out = await run_print(
        factory, printer, req([raw(i) for i in range(9)], [on(code)]), queue=queue
    )

    (page,) = out.pages
    assert page.sheet_code == code and page.cells == list(range(18, 27))
    assert page.id_cell is None and page.margin_id is False and page.feed_mark is True
    assert page.margin_band is None and page.id_not_printed is False
    (printer_id, payload, job_id) = queue.submitted[0]
    assert printer_id == printer.id and job_id == page.job_id
    assert payload.kind == "sheet_page" and payload.media == "A4"
    assert payload.tray == "auto" and payload.render_dpi == 600
    assert payload.job_name == f"Sheet {code} · 9 labels"
    assert payload.calibration is not None and payload.calibration.method == "none"
    detail = queue.detail()
    assert str(detail.sheet_id) and detail.sheet_code == code and detail.type_key == KEY
    assert detail.geometry == asdict(G48) and detail.allow_qr is True
    assert [c.cell for c in detail.cells] == list(range(18, 27))
    assert {c.content_type for c in detail.cells} == {ContentType.QR_TWO_LINES}
    assert detail.job_summary == {"sheet_code": code, "cell_count": 9}
    # the reservation points at the job; one batch row names every job
    rows = [r for r in await cell_rows(factory) if r.state == "reserved"]
    assert sorted(r.cell_no for r in rows) == list(range(18, 27))
    assert {r.job_id for r in rows} == {job_id}
    async with factory() as s:
        batch = (await s.execute(select(PrintBatch))).scalar_one()
    assert str(batch.id) == str(out.batch_id)
    assert batch.job_ids == [str(job_id)] and batch.printer_id == printer.id
    assert batch.created_by == "key:test"


async def test_job_name_and_summary_carry_no_label_text(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    printer = await make_printer(session, record())
    code = await make_sheet(session)
    queue = FakeQueue()

    await run_print(
        factory,
        printer,
        req([raw(0, purpose="secret-purpose", title="secret-title")], [on(code)]),
        queue=queue,
    )

    (payload,) = queue.payloads
    assert "secret" not in payload.job_name
    assert "secret" not in str(payload.detail["job_summary"])


async def test_one_sheet_one_job_one_batch(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    printer = await make_printer(session, record())
    queue = FakeQueue()

    out = await run_print(factory, printer, req([raw(i) for i in range(9)], [fresh()]), queue=queue)

    (page,) = out.pages  # #277: one sheet per run
    assert len(page.cells) == 9
    assert [j for _, _, j in queue.submitted] == [page.job_id]
    async with factory() as s:
        batch = (await s.execute(select(PrintBatch))).scalar_one()
    assert batch.job_ids == [str(page.job_id)]
    assert queue.payloads[0].job_name.endswith("· 9 labels")


async def test_pages_use_the_one_snapshot_taken_before_the_reservation(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    printer = await make_printer(session, record())
    await calibration_service.put(
        session,
        printer.id,
        "auto",
        CalibrationIn(offset_x_mm=0.2, offset_y_mm=-0.8),
        measured_on=None,
        actor="t",
    )
    order: list[str] = []
    original_snapshot = calibration_service.snapshot
    original_reserve = print_service.reserve

    async def snapshot(*a: Any, **kw: Any) -> Any:
        order.append("snapshot")
        return await original_snapshot(*a, **kw)

    async def reserve(*a: Any, **kw: Any) -> Any:
        order.append("reserve")
        # the margin context carries the deviation of that same snapshot
        assert kw["margin"].deviation.offset_y_hmm == -80
        return await original_reserve(*a, **kw)

    monkeypatch.setattr(calibration_service, "snapshot", snapshot)
    monkeypatch.setattr(print_service, "reserve", reserve)
    queue = FakeQueue()

    await run_print(
        factory,
        printer,
        req([raw(i) for i in range(31)], [on(await make_sheet(session, used=17))]),
        queue=queue,
    )

    assert order == ["snapshot", "reserve"]  # taken once, before the reservation
    assert len(queue.payloads) == 1  # #277: one sheet per run
    assert {p.calibration.dy_hmm for p in queue.payloads if p.calibration} == {-80}


async def test_print_after_type_edit_uses_the_pinned_version(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    printer = await make_printer(session, record())
    code = await make_sheet(session)
    v2 = G48.__class__(**{**asdict(G48), "pitch_x": 5000, "cols": 3})
    await ts.add_version(session, KEY, v2, actor="t", change_note="v2")
    queue = FakeQueue()

    await run_print(factory, printer, req([raw(i) for i in range(3)], [on(code)]), queue=queue)

    detail = queue.detail()
    assert detail.geometry == asdict(G48)  # v1 positions
    assert [c.cell for c in detail.cells] == [1, 2, 3]
    assert detail.type_version_id is not None


# ---------------------------------------------------------------------------- content


async def test_qr_on_a_type_without_qr_is_printed_as_text(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    await ts.create_type(
        session,
        ts.TypeFields("acme-noqr", "NOQR1", "Acme", ["N-1"], None, False),
        G48,
        actor="t",
    )
    printer = await make_printer(session, record())
    sheet = await make_sheet(session, key="acme-noqr")
    queue = FakeQueue()

    await run_print(
        factory,
        printer,
        req([raw(0, ContentType.QR_TWO_LINES), raw(1, ContentType.QR_ONLY)], [on(sheet)]),
        queue=queue,
    )

    cells = queue.detail().cells
    assert [c.content_type for c in cells] == [
        ContentType.TEXT_TWO_LINES,
        ContentType.TEXT_ONE_LINE,
    ]
    assert all(c.mapped for c in cells)
    assert queue.detail().allow_qr is False


async def test_id_cell_sheet_carries_its_label(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    printer = await make_printer(session, record())
    queue = FakeQueue()

    out = await run_print(factory, printer, req([raw(0)], [fresh("cell")]), queue=queue)

    (page,) = out.pages
    assert page.id_cell == 1 and page.cells == [2] and page.margin_id is False
    detail = queue.detail()
    assert detail.id_cell is not None and detail.id_cell.cell == 1
    assert detail.id_cell.label_data["primary_id"] == page.sheet_code
    assert detail.margin_id is None


# ---------------------------------------------------------------------------- purposes


async def test_purpose_is_cleaned_and_a_long_title_is_cut_not_refused(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    class LongTitle(FakeLookup):
        async def lookup(self, source_app: str, identifier: str) -> LabelData:
            return LabelData(
                source_app=source_app,
                title="T" * 10_000,
                primary_id="P-1",
                qr_payload="https://g.example.invalid/1",
            )

    printer = await make_printer(session, record())
    code = await make_sheet(session)

    await run_print(
        factory,
        printer,
        req([raw(0, purpose="a\x07b‮c  d"), grocy(1), grocy(2, purpose="own")], [on(code)]),
        queue=FakeQueue(),
        lookup=LongTitle(),
    )

    purposes = {r.cell_no: r.purpose for r in await cell_rows(factory)}
    assert purposes[1] == "abc  d"  # control character and bidi override gone
    assert purposes[2] == "T" * 120
    assert purposes[3] == "own"


# ---------------------------------------------------------------------------- expected cells


async def test_expected_cells_mismatch_answers_the_new_plan(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    printer = await make_printer(session, record())
    code = await make_sheet(session, used=17)
    queue = FakeQueue()

    with pytest.raises(PlanChangedError) as exc:
        await run_print(
            factory,
            printer,
            req(
                [raw(i) for i in range(3)],
                [on(code)],
                expected_cells=[ExpectedPageModel(sheet=code, cells=[19, 20, 21], id_cell=None)],
            ),
            queue=queue,
        )

    assert exc.value.detail == {"plan": [{"sheet": code, "cells": [18, 19, 20], "id_cell": None}]}
    assert queue.calls == 0 and await cell_rows(factory) == [
        r for r in await cell_rows(factory) if r.cell_no <= 17
    ]


async def test_expected_cells_from_a_preview_are_accepted_for_new_and_existing_sheets(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    printer = await make_printer(session, record())
    code = await make_sheet(session, used=17)
    # #277: one sheet per run: an existing sheet (31 of 40 fit) and a new sheet, one run each.
    for placement in (on(code), fresh()):
        request = req([raw(i) for i in range(40)], [placement])
        preview = await run_preview(session, printer, request)

        out = await run_print(
            factory,
            printer,
            req(
                [raw(i) for i in range(40)],
                [placement],
                expected_cells=list(preview.expected_cells),
            ),
            queue=FakeQueue(),
        )

        assert [p.cells for p in out.pages] == [e.cells for e in preview.expected_cells]
        assert out.placed == preview.placed


async def test_insufficient_cells_refuses_and_reserves_nothing(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    printer = await make_printer(session, record())
    code = await make_sheet(session, used=48)  # #277: a short sheet places what fits; a full one

    with pytest.raises(InsufficientCellsError) as exc:
        await run_print(factory, printer, req([raw(i) for i in range(20)], [on(code)]))

    assert exc.value.detail is not None and exc.value.detail["shortfall"] == 20
    assert len(await cell_rows(factory)) == 48


# ---------------------------------------------------------------------------- refused before


async def test_nothing_reserved_on_late_failure(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    ipp = await make_printer(session, record())
    tape = await make_printer(session, record(), backend="brother_ql")
    code = await make_sheet(session)
    sheets_before = await count(factory, Sheet)
    counters_before = await counters(factory)

    # a lookup fails for item 37 of 40
    items = [grocy(i) for i in range(40)]
    lookup = FakeLookup(fail={"36": LookupFailedError("upstream")})
    queue = FakeQueue()
    with pytest.raises(ItemLookupFailedError) as exc:
        await run_print(factory, ipp, req(items, [on(code)]), queue=queue, lookup=lookup)
    assert exc.value.detail == {"item_index": 36}

    # a tape printer
    with pytest.raises(MediaKindMismatchError):
        await run_print(factory, tape, req([raw(0)], [on(code)]), queue=queue)

    # a disabled and an unknown tray
    for tray in ("off", "nope"):
        with pytest.raises(TrayUnknownError):
            await run_print(factory, ipp, req([raw(0)], [on(code)], tray=tray), queue=queue)

    # item 5 lacks a field its content type needs; item 7 has a QR no cell can draw
    broken = [raw(i) for i in range(10)]
    broken[5] = raw(5, title=None)
    with pytest.raises(ItemContentMismatchError) as mismatch:
        await run_print(factory, ipp, req(broken, [on(code)]), queue=queue)
    assert mismatch.value.detail is not None and mismatch.value.detail["item_index"] == 5
    assert mismatch.value.detail["missing_fields"] == ["title"]
    coarse = await make_printer(session, record(dpis=[200]))  # 512 emoji need a finer grid
    huge = [raw(i) for i in range(10)]
    huge[7] = raw(7, qr_payload="".join(random.Random(4).choices("😀😁😂🤣😃😄", k=512)))
    with pytest.raises(ItemContentMismatchError) as dense:
        await run_print(factory, coarse, req(huge, [fresh()]), queue=queue)
    assert dense.value.detail is not None and dense.value.detail["item_index"] == 7

    assert queue.calls == 0
    assert await cell_rows(factory) == []
    assert await count(factory, Sheet) == sheets_before  # the new sheet was not created either
    assert await counters(factory) == counters_before  # no code number was used up
    assert await count(factory, PrintBatch) == 0


async def test_content_check_maps_the_type_first(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    """A QR-only item without a payload is fine on a type without QR: it prints as text."""
    await ts.create_type(
        session, ts.TypeFields("acme-noqr", "NOQR1", "Acme", ["N-1"], None, False), G48, actor="t"
    )
    printer = await make_printer(session, record())
    sheet = await make_sheet(session, key="acme-noqr")

    item = raw(0, ContentType.QR_ONE_LINE, qr_payload=None)
    out = await run_print(factory, printer, req([item], [on(sheet)]))

    assert out.pages[0].cells == [1]


# ---------------------------------------------------------------------------- failures after


async def test_submit_failure_of_the_only_page_releases_every_cell(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    # #277: one sheet per run, so a run has one page and no page can be left submitted.
    printer = await make_printer(session, record())
    bus = FakeBus()
    queue = FakeQueue(fail_on=1)

    with pytest.raises(RuntimeError, match="queue is down"):
        await run_print(
            factory, printer, req([raw(i) for i in range(48)], [fresh()]), queue=queue, bus=bus
        )

    assert queue.submitted == []
    assert await cell_rows(factory) == []
    assert any(e.data["changed"] for e in bus.events)  # reserve and release both announced


async def test_the_batch_row_exists_with_every_job_before_the_first_submit(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    printer = await make_printer(session, record())
    seen: list[list[str]] = []

    async def look(n: int, job_id: UUID) -> None:
        async with factory() as s:
            batch = (await s.execute(select(PrintBatch))).scalar_one()
        seen.append(batch.job_ids)

    queue = FakeQueue()
    queue.before_submit = look

    out = await run_print(
        factory, printer, req([raw(i) for i in range(48)], [fresh()]), queue=queue
    )

    expected = [str(p.job_id) for p in out.pages]
    assert seen == [expected]


async def test_a_failed_batch_insert_queues_nothing_and_frees_every_cell(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    printer = await make_printer(session, record())

    async def broken(*a: Any, **kw: Any) -> Any:
        raise RuntimeError("disk full")

    monkeypatch.setattr(print_service.batches_repo, "create", broken)
    queue = FakeQueue()

    with pytest.raises(RuntimeError, match="disk full"):
        await run_print(factory, printer, req([raw(i) for i in range(48)], [fresh()]), queue=queue)

    assert queue.calls == 0 and queue.submitted == []
    assert await cell_rows(factory) == []


async def test_a_committed_job_row_keeps_its_cells_even_if_the_queue_forgot_it(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    """``submit_page_job`` can commit the row and then fail on the refresh; the queue drops the
    job from memory, but the next start re-enqueues the row: its cells must stay reserved."""
    printer = await make_printer(session, record())
    code = await make_sheet(session, used=17)
    queue = FakeQueue()

    async def commit_then_cancel(n: int, job_id: UUID) -> None:
        async with factory() as s:
            s.add(
                DbJob(
                    id=job_id,
                    printer_id=printer.id,
                    template_key=None,
                    payload={"kind": "sheet_page"},
                )
            )
            await s.commit()
        raise asyncio.CancelledError

    queue.before_submit = commit_then_cancel

    with pytest.raises(asyncio.CancelledError):
        await run_print(factory, printer, req([raw(i) for i in range(5)], [on(code)]), queue=queue)

    reserved = [r for r in await cell_rows(factory) if r.state == "reserved"]
    assert sorted(r.cell_no for r in reserved) == [18, 19, 20, 21, 22]


async def test_no_database_transaction_is_open_while_the_lookups_run(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    printer = await make_printer(session, record())
    code = await make_sheet(session)
    opened: list[AsyncSession] = []

    def tracking() -> AsyncSession:
        s = factory()
        opened.append(s)
        return s

    open_during: list[bool] = []

    class Watching(FakeLookup):
        async def lookup(self, source_app: str, identifier: str) -> LabelData:
            open_during.append(any(s.in_transaction() for s in opened))
            return await super().lookup(source_app, identifier)

    await print_service.print_sheets(
        tracking,  # type: ignore[arg-type]
        printer=printer,
        request=req([grocy(1)], [on(code)]),
        lookup=Watching(),  # type: ignore[arg-type]
        queue=FakeQueue(),
        actor="key:test",
        api_key_id=None,
        source_ip=None,
        language="en",
    )

    assert open_during == [False]


async def test_the_margin_qr_of_the_preview_has_the_size_the_job_prints(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import io

    from app.sheets.cell_render import DEFAULT_CELL_RENDERER
    from app.sheets.sheet_page import render_sheet_page
    from PIL import Image

    printer = await make_printer(session, record())
    code = await make_sheet(session, placement="margin")
    request = req([raw(0)], [on(code)])
    queue = FakeQueue()
    spy_pngs: list[bytes] = []
    original = print_service.render_preview_png

    def capture(*a: Any, **kw: Any) -> bytes:
        out = original(*a, **kw)
        spy_pngs.append(out)
        return out

    monkeypatch.setattr(print_service, "render_preview_png", capture)
    await run_preview(session, printer, request)
    monkeypatch.undo()
    await run_print(factory, printer, request, queue=queue)

    detail = queue.detail()
    assert detail.margin_id is not None and detail.margin_id.band == "top"
    g = detail.geometry
    d = detail.margin_id.usable_hmm
    left = g["margin_left"]
    top = g["margin_top"] - 100 - d  # the band starts SAFETY_HMM outside the grid

    def ink_width_px(img: Image.Image, dpi: int) -> int:
        box = (
            round(left / 2540 * dpi),
            round(top / 2540 * dpi),
            round((left + d) / 2540 * dpi),
            round((top + d) / 2540 * dpi),
        )
        bbox = img.convert("L").point(lambda v: 255 if v < 128 else 0).crop(box).getbbox()
        assert bbox is not None
        return bbox[2] - bbox[0]

    pdf = render_sheet_page(queue.payloads[0], DEFAULT_CELL_RENDERER, compress=False)
    # The margin QR is the last image the job draws. Its ink is measured from the image's own
    # pixels and its placement on the page: no rasteriser (tests must not need poppler).
    qr = placed_images(pdf)[-1]
    x0, _, x1, _ = ink_box_px(qr.image)
    job_mm = (x1 - x0) * qr.mm_per_pixel
    preview_img = Image.open(io.BytesIO(spy_pngs[0]))
    preview_mm = ink_width_px(preview_img, 150) / 150 * 25.4
    assert abs(preview_mm - job_mm) <= 25.4 / 150  # within one preview pixel


async def test_unknown_printer_in_the_queue_answers_unavailable_and_releases(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    printer = await make_printer(session, record())
    code = await make_sheet(session, used=17)
    queue = FakeQueue(fail_on=1, exc=KeyError("printer"))

    with pytest.raises(PrinterUnavailableError) as exc:
        await run_print(factory, printer, req([raw(i) for i in range(5)], [on(code)]), queue=queue)

    http = exc.value.to_http()
    assert http.status_code == 409 and http.detail["error_code"] == "printer-unavailable"
    assert [r for r in await cell_rows(factory) if r.state == "reserved"] == []
    assert len(await cell_rows(factory)) == 17


async def test_failure_while_building_a_payload_releases_everything_unsubmitted(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    printer = await make_printer(session, record())
    original = print_service.feed_mark_payload
    calls = 0

    def flaky(p: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom")
        return original(p)

    monkeypatch.setattr(print_service, "feed_mark_payload", flaky)
    queue = FakeQueue()

    with pytest.raises(RuntimeError, match="boom"):
        await run_print(factory, printer, req([raw(i) for i in range(48)], [fresh()]), queue=queue)

    assert queue.submitted == []  # every payload is built before the first submit
    assert await cell_rows(factory) == []


# ---------------------------------------------------------------------------- margin and mark


async def test_stored_margin_id_and_feed_mark_equal_the_previews(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = Spy(monkeypatch)
    printer = await make_printer(
        session, record(margins=Margins(top=600, left=500, bottom=423, right=500))
    )
    code = await make_sheet(session, placement="margin")
    # #277: one sheet per run: an existing sheet, then a new one (its code is the preview's hint)
    queue = FakeQueue()
    bands: list[str | None] = []
    for request in (
        req([raw(i) for i in range(2)], [on(code)]),
        req([raw(2)], [fresh("margin")]),
    ):
        await run_preview(session, printer, request, language="de")
        out = await run_print(factory, printer, request, queue=queue, language="de")
        bands.extend(p.margin_band for p in out.pages)

    assert len(spy.calls) == 2 and len(queue.payloads) == 2
    for n in range(2):
        d = queue.detail(n)
        assert d.margin_id == spy.margins[n]  # the same decision, field for field
        assert d.feed_mark == spy.feed_marks[n]
        assert d.margin_id is not None and d.feed_mark is not None
    assert bands == [m.band for m in spy.margins if m]


async def test_margin_id_text_is_the_shared_helper_and_the_qr_the_scan_payload(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    printer = await make_printer(session, record())
    code = await make_sheet(session, placement="margin")
    queue = FakeQueue()

    await run_print(factory, printer, req([raw(0)], [on(code)]), queue=queue)

    m = queue.detail().margin_id
    assert m is not None
    assert m.text == print_service.margin_id_text(code, "Avery L4736REV-25")
    assert m.qr_payload is not None and m.qr_payload.endswith(f"/sheet/{code}")
    assert page_margin_id_payload is print_service.page_margin_id_payload


async def test_feed_mark_shares_the_top_band_and_stops_the_id_text(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    printer = await make_printer(session, record(margins=None))  # unknown: 5 mm, top band wins
    code = await make_sheet(session, placement="margin")
    queue = FakeQueue()

    await run_print(factory, printer, req([raw(0)], [on(code)]), queue=queue)

    d = queue.detail()
    assert d.margin_id is not None and d.margin_id.band == "top"
    assert d.feed_mark is not None
    assert d.margin_id.text_end_hmm == d.feed_mark.x_hmm - MARGIN_TEXT_GAP_HMM


async def test_feed_mark_text_follows_the_language_argument(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    printer = await make_printer(session, record())
    texts: list[str] = []
    for language in ("de", "en", None):
        queue = FakeQueue()
        code = await make_sheet(session)
        await run_print(factory, printer, req([raw(0)], [on(code)]), queue=queue, language=language)
        mark = queue.detail().feed_mark
        assert mark is not None
        texts.append(mark.text)
    assert texts == [
        "▲ Oben \u2013 diese Kante zuerst",
        "▲ Top \u2013 this edge first",
        "▲ Top \u2013 this edge first",
    ]


async def test_render_dpi_comes_from_the_printer_facts(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    low = await make_printer(session, record(dpis=[150, 300]))
    never = await make_printer(session, None)
    queue = FakeQueue()

    await run_print(factory, low, req([raw(0)], [on(await make_sheet(session))]), queue=queue)
    await run_print(factory, never, req([raw(0)], [on(await make_sheet(session))]), queue=queue)

    assert [p.render_dpi for p in queue.payloads] == [300, 600]


async def test_a_page_without_room_for_the_id_is_flagged_and_takes_no_cell(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    printer = await make_printer(
        session, record(margins=Margins(top=2000, left=2000, bottom=2000, right=2000))
    )
    code = await make_sheet(session, placement="margin")
    queue = FakeQueue()

    out = await run_print(
        factory, printer, req([raw(i) for i in range(3)], [on(code)]), queue=queue
    )

    (page,) = out.pages
    assert page.id_not_printed is True and page.margin_id is False and page.margin_band is None
    assert queue.detail().margin_id is None
    assert len(await cell_rows(factory)) == 3


# ---------------------------------------------------------------------------- misc


async def test_a_raw_item_cannot_make_the_payload_unbounded() -> None:
    from app.schemas.sheet_print import SheetRawLabelData
    from pydantic import ValidationError

    for bad in (
        {"title": "x" * 513},
        {"primary_id": "x" * 513},
        {"secondary": ["x"] * 11},
        {"secondary": ["x" * 513]},
        {"items": [{"item": "x"}] * 101},
        {"items": [{"item": "x" * 513}]},
        {"qr_payload": "x" * 513},
    ):
        with pytest.raises(ValidationError):
            SheetRawLabelData(**bad)
    SheetRawLabelData(title="x" * 512, secondary=["x" * 512] * 10, items=[{"item": "y"}] * 100)


async def test_uuid_job_ids_are_fresh_per_print(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    printer = await make_printer(session, record())
    ids = set()
    for _ in range(2):
        out = await run_print(factory, printer, req([raw(0)], [on(await make_sheet(session))]))
        ids.add(out.pages[0].job_id)
    assert len(ids) == 2 and uuid4() not in ids
    assert reservation.release is not None


def ink_box_px(
    img: Any, crop: tuple[int, int, int, int] | None = None
) -> tuple[int, int, int, int]:
    """Bounding box of the dark pixels of a 1-bit PDF image (0 = black), inside ``crop``."""
    mask = img.convert("L").point(lambda v: 255 if v < 128 else 0)
    box = (mask if crop is None else mask.crop(crop)).getbbox()
    assert box is not None
    return box


# ---------------------------------------------------------------------------- cell QR size

CELL_GEOMETRIES = {
    "wide": Geometry(
        "A4", 21000, 29700, 4570, 2120, 4, 12, 4820, 2120, 2130, 985, None, "rectangle"
    ),
    "small": Geometry(
        "A4", 21000, 29700, 3000, 2000, 6, 13, 3200, 2100, 1500, 900, None, "rectangle"
    ),
    "large": Geometry(
        "A4", 21000, 29700, 6350, 3810, 3, 7, 6500, 3900, 1200, 800, None, "rectangle"
    ),
}


@pytest.mark.parametrize("dpi", [300, 600])
@pytest.mark.parametrize("shape", sorted(CELL_GEOMETRIES))
async def test_a_cell_qr_has_the_same_size_in_the_preview_and_the_job_pdf(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    shape: str,
    dpi: int,
) -> None:
    import io

    from app.sheets.cell_render import DEFAULT_CELL_RENDERER, content_box, qr_edge_px
    from app.sheets.sheet_page import render_sheet_page
    from PIL import Image

    g = CELL_GEOMETRIES[shape]
    await ts.create_type(
        session,
        ts.TypeFields(f"acme-{shape}", f"Q{shape[:3].upper()}", "Acme", ["Q-1"], None, True),
        g,
        actor="t",
    )
    printer = await make_printer(session, record(dpis=[dpi]))
    code = await make_sheet(session, key=f"acme-{shape}")
    request = req([raw(0)], [on(code)])
    pngs: list[bytes] = []
    original = print_service.render_preview_png

    def capture(*a: Any, **kw: Any) -> bytes:
        out = original(*a, **kw)
        pngs.append(out)
        return out

    monkeypatch.setattr(print_service, "render_preview_png", capture)
    await run_preview(session, printer, request)
    monkeypatch.undo()
    queue = FakeQueue()
    await run_print(factory, printer, request, queue=queue)

    pdf = render_sheet_page(queue.payloads[0], DEFAULT_CELL_RENDERER, compress=False)
    box = content_box(g, 1)
    edge_mm = qr_edge_px(box.w / 100, box.h / 100, 1000) / 1000 * 25.4  # the square, in mm

    def ink_mm(img: Image.Image, dpi: int) -> tuple[float, float]:
        """Width and height of the ink in the cell's QR square, in mm (measured at ``dpi``)."""
        x0, y0 = round(box.x / 2540 * dpi), round(box.y / 2540 * dpi)
        edge = round(edge_mm / 25.4 * dpi)
        mask = img.convert("L").point(lambda v: 255 if v < 128 else 0)
        found = mask.crop((x0, y0, x0 + edge, y0 + edge)).getbbox()
        assert found is not None
        return (found[2] - found[0]) / dpi * 25.4, (found[3] - found[1]) / dpi * 25.4

    # The job's cell image: the QR square is its top-left corner. Its scale is the image's pixel
    # size against the rectangle the page draws it in (no rasteriser).
    cell = placed_images(pdf)[0]
    edge_px = round(edge_mm / cell.mm_per_pixel)
    x0, y0, x1, y1 = ink_box_px(cell.image, (0, 0, edge_px, edge_px))
    job = ((x1 - x0) * cell.mm_per_pixel, (y1 - y0) * cell.mm_per_pixel)
    preview = ink_mm(Image.open(io.BytesIO(pngs[0])), 150)
    one_preview_pixel = 25.4 / 150
    assert abs(preview[0] - job[0]) <= one_preview_pixel, (preview, job)
    assert abs(preview[1] - job[1]) <= one_preview_pixel, (preview, job)


async def test_the_dry_plan_of_a_print_runs_off_the_event_loop(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R10-5 / R10-2: the plan before the lookups is CPU work and must not block the loop."""
    import threading

    loop_thread = threading.get_ident()
    seen: list[int] = []
    real_plan = print_service.plan

    def recording(*args: Any, **kwargs: Any) -> Any:
        seen.append(threading.get_ident())
        return real_plan(*args, **kwargs)

    monkeypatch.setattr(print_service, "plan", recording)
    printer = await make_printer(session, record())
    code = await make_sheet(session)

    await run_print(factory, printer, req([raw(0)], [on(code)]))

    assert seen and seen[0] != loop_thread  # the dry plan; the locked one runs in reserve


# ---------------------------------------------------------------------------- tiny labels


@pytest.mark.parametrize("label_hmm", [300, 320, 350])
async def test_a_label_too_small_for_a_line_is_refused_before_anything_is_reserved(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    label_hmm: int,
) -> None:
    """Codex P2 / review item P1-1: a 3 mm label with an unknown radius has a content box of
    -0.2 mm (3.2 mm: exactly 0; 3.5 mm: 0.3 mm, no line). Refused like a QR that does not fit:
    ``content_type_data_mismatch`` with the item's index, nothing reserved, nothing queued."""
    g = Geometry(
        "A4", 21000, 29700, label_hmm, label_hmm, 4, 8, label_hmm + 50, label_hmm + 50, 1500, 900,
        None, "rectangle",
    )  # fmt: skip
    await ts.create_type(
        session, ts.TypeFields("acme-tiny", "TNY", "Acme", ["T-1"], None, True), g, actor="t"
    )
    printer = await make_printer(session, record())
    code = await make_sheet(session, key="acme-tiny")
    queue = FakeQueue()

    with pytest.raises(ItemContentMismatchError) as err:
        await run_print(factory, printer, req([raw(0), raw(1)], [on(code)]), queue=queue)

    assert err.value.detail == {"item_index": 0, "missing_fields": ["label_size"]}
    assert await cell_rows(factory) == []
    assert queue.submitted == []


async def test_the_preview_of_a_tiny_label_is_refused_the_same_way(
    session: AsyncSession,
) -> None:
    g = Geometry(
        "A4", 21000, 29700, 300, 300, 4, 8, 350, 350, 1500, 900, None, "rectangle"
    )  # fmt: skip
    await ts.create_type(
        session, ts.TypeFields("acme-tiny2", "TN2", "Acme", ["T-1"], None, True), g, actor="t"
    )
    printer = await make_printer(session, record())
    code = await make_sheet(session, key="acme-tiny2")

    with pytest.raises(ItemContentMismatchError) as err:
        await run_preview(session, printer, req([raw(0)], [on(code)]))

    assert err.value.detail["item_index"] == 0


async def test_a_version_added_during_the_lookups_is_not_printed_on_unchecked_geometry(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex P2: with ``new_sheet.version`` left out, the fit check used the current version read
    before the (slow) lookups and ``reserve`` resolved the current version again. A version an
    admin added in between was printed on without ever being checked. The version is now
    resolved once, before the check, and reserved explicitly."""
    printer = await make_printer(session, record())
    original = print_service.resolve_items

    async def slow(*args: Any, **kwargs: Any) -> Any:
        out = await original(*args, **kwargs)
        v2 = Geometry(**{**asdict(G48), "pitch_x": 5000, "cols": 3})
        async with factory() as other:  # the admin, while the lookups ran
            await ts.add_version(other, KEY, v2, actor="admin", change_note="v2")
        return out

    monkeypatch.setattr(print_service, "resolve_items", slow)
    queue = FakeQueue()

    out = await run_print(factory, printer, req([raw(0)], [fresh()]), queue=queue)

    detail = queue.detail()
    assert detail.geometry == asdict(G48)  # the version that was checked, not the new one
    assert out.pages[0].cells == [1]
    async with factory() as s:
        sheet = (await s.execute(select(Sheet))).scalar_one()
        version = await s.get(SheetTypeVersion, sheet.type_version_id)
    assert version is not None and version.version == 1


def test_id_cell_fit_check_refuses_a_box_without_room_for_a_line_or_the_qr() -> None:
    """Issue #210: the ID cell gets the checks an item gets, and nothing is echoed."""
    from app.sheets.errors import IdCellContentMismatchError
    from app.sheets.geometry import Geometry
    from app.sheets.print_service import check_id_cell_fits

    def scan(code: str) -> str:
        return f"https://hub.example.invalid/s/{code}"

    def check(label_mm: int, *, allow_qr: bool) -> None:
        g = Geometry(
            "A4", 21000, 29700, label_mm, label_mm, 1, 1, label_mm, label_mm, 1500, 2000, None,
            "rectangle",
        )  # fmt: skip
        check_id_cell_fits(g, allow_qr=allow_qr, code="AT1-0001", scan=scan, render_dpi=300)

    with pytest.raises(IdCellContentMismatchError) as no_line:
        check(350, allow_qr=False)
    assert no_line.value.detail == {"cell": "id", "missing_fields": ["label_size"]}
    with pytest.raises(IdCellContentMismatchError) as no_qr:
        check(600, allow_qr=True)  # room for a line, not for the symbol
    assert no_qr.value.detail == {"cell": "id", "missing_fields": ["qr_payload"]}
    check(600, allow_qr=False)  # text only: no symbol to fit
    check(2000, allow_qr=True)


def test_id_cell_fits_45_7x21_2(monkeypatch: pytest.MonkeyPatch) -> None:
    """266-10: on a 45.7 x 21.2 mm cell the ID label shows the code in full and the type label
    as its title (shortened to fit if need be); "sheet ID" is no longer part of the title."""
    from app.sheets import cell_render
    from app.sheets.cell_render import DEFAULT_CELL_RENDERER, content_box

    g = Geometry("A4", 21000, 29700, 4570, 2120, 4, 12, 4820, 2120, 2130, 985, None, "rectangle")
    label = print_service.id_cell_label(
        "L4736-0001", "Avery Zweckform L4736REV", "https://hub.example.invalid/sheet/L4736-0001"
    )
    assert label.title == "Avery Zweckform L4736REV"
    shown: dict[str, str] = {}
    real = cell_render._fit_line

    def spy(text: str, *args: Any) -> tuple[str, int, bool]:
        out = real(text, *args)
        shown[text] = out[0]
        return out

    monkeypatch.setattr(cell_render, "_fit_line", spy)
    box = content_box(g, 1)
    for dpi in (300, 600):
        shown.clear()
        DEFAULT_CELL_RENDERER.render(
            box_w_mm=box.w / 100,
            box_h_mm=box.h / 100,
            dpi=dpi,
            content_type=ContentType.QR_TWO_LINES,
            data=label,
        )
        assert shown["L4736-0001"] == "L4736-0001"  # the code line is never cut
        title = shown[label.title]
        assert "sheet ID" not in title and title.rstrip("…").startswith("Avery Zweckform")
