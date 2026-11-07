"""Sheet print preview: item resolution, planning, PNGs, hints, bounds (Plan 3, Task 6)."""

from __future__ import annotations

import asyncio
import base64
import io
import random
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import app.models  # noqa: F401
import pytest
import pytest_asyncio
from app.calibration import service as calibration_service
from app.calibration.model import CalibrationIn
from app.models.job import Job
from app.models.printer import Printer
from app.models.printer_status_cache import PrinterStatusCache
from app.models.printer_tray import PrinterTray
from app.models.sheet import Sheet, SheetCell, SheetIdCounter
from app.page_render.transform import Deviation
from app.printer_backends.ipp.attributes import IppStatusRecord, Margins
from app.schemas.content_type import ContentType
from app.schemas.label_data import LabelData
from app.schemas.print_request import PrintLookupRequest
from app.schemas.sheet_print import (
    NewSheetModel,
    PlacementInModel,
    SheetItem,
    SheetPrintRequest,
    SheetRawLabelData,
)
from app.services.errors import AppLookupNotFoundError, IntegrationNotConfiguredError
from app.services.lookup_service import LookupFailedError, UnknownAppError
from app.services.producers.ipp_status_producer import _empty_summary, _offline_record
from app.sheets import cell_render, print_service
from app.sheets import sheet_service as ss
from app.sheets import type_service as ts
from app.sheets.cell_render import DEFAULT_CELL_RENDERER, content_box
from app.sheets.errors import (
    InsufficientCellsError,
    ItemContentMismatchError,
    ItemLookupFailedError,
    MediaKindMismatchError,
    PreviewTooLargeError,
    SheetDiscardedError,
    SheetNotFoundError,
    TrayUnknownError,
)
from app.sheets.geometry import Geometry
from app.sheets.print_service import resolve_items
from app.sheets.printer_facts import load_printer_facts
from app.sheets.sheet_page import FeedMarkPayload, MarginIdPayload
from app.sheets.sheet_service import MarkedCell
from PIL import Image
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

G48 = Geometry("A4", 21000, 29700, 4570, 2120, 4, 12, 4850, 2120, 2150, 840, None, "rectangle")
G_SMALL = Geometry("A4", 21000, 29700, 2540, 1000, 7, 27, 2790, 1000, 1350, 860, 150, "rectangle")
KEY = "avery-l4736rev"
KEY_SMALL = "avery-l4731rev"


# ---------------------------------------------------------------------------- doubles


class FakeLookup:
    """Stands in for ``AppLookupService``; remembers the highest number of calls in flight."""

    def __init__(
        self,
        fail: dict[str, Exception] | None = None,
        delays: dict[str, float] | None = None,
        default_delay: float = 0.0,
    ) -> None:
        self.fail = fail or {}
        self.delays = delays or {}
        self.default_delay = default_delay
        self.in_flight = 0
        self.max_in_flight = 0
        self.calls: list[tuple[str, str]] = []

    async def lookup(self, source_app: str, identifier: str) -> LabelData:
        self.calls.append((source_app, identifier))
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.delays.get(identifier, self.default_delay))
            if identifier in self.fail:
                raise self.fail[identifier]
            return LabelData(
                source_app=source_app,
                title=f"Product {identifier}",
                primary_id=f"G-{identifier}",
                qr_payload=f"https://g.example.invalid/{identifier}",
            )
        finally:
            self.in_flight -= 1


def grocy(i: int | str, ct: ContentType = ContentType.QR_TWO_LINES, **kw: Any) -> SheetItem:
    return SheetItem(
        content_type=ct, lookup=PrintLookupRequest(app="grocy", identifier=str(i)), **kw
    )


def raw(i: int, ct: ContentType = ContentType.QR_TWO_LINES, **kw: Any) -> SheetItem:
    """Raw data for item ``i``; ``purpose``, ``source`` and ``ref`` belong to the item."""
    item_keys = {k: kw.pop(k) for k in ("purpose", "source", "ref") if k in kw}
    fields: dict[str, Any] = {
        "title": f"Item {i}",
        "primary_id": f"R-{i}",
        "qr_payload": f"https://r.example.invalid/{i}",
    }
    fields.update(kw)
    return SheetItem(content_type=ct, data=SheetRawLabelData(**fields), **item_keys)


def req(items: list[SheetItem], placements: list[PlacementInModel], **kw: Any) -> SheetPrintRequest:
    return SheetPrintRequest(items=items, placements=placements, **kw)


def on(code: str, **kw: Any) -> PlacementInModel:
    return PlacementInModel(sheet=code, **kw)


def fresh(placement: str | None = None, key: str = KEY, **kw: Any) -> PlacementInModel:
    extra: dict[str, Any] = {} if placement is None else {"id_placement": placement}
    return PlacementInModel(new_sheet=NewSheetModel(type=key, **extra), **kw)


def record(
    dpis: list[int] | None = None, margins: Margins | None = None, online: bool = True
) -> IppStatusRecord:
    base = _empty_summary()
    summary = base.model_copy(
        update={
            "resolutions_dpi": [300, 600] if dpis is None else dpis,
            "margins_hmm": margins,
            "pdf_supported": True,
            "state": "idle",
        }
    )
    return IppStatusRecord(
        online=online,
        printer_state="idle",
        reasons=[],
        blocking_reason=None,
        warnings=[],
        markers=[],
        trays=[],
        jobs_ahead=0,
        summary=summary,
    )


@pytest_asyncio.fixture
async def session(async_session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[Any]:
    async with async_session_factory() as s:
        await ts.create_type(
            s,
            ts.TypeFields(KEY, "L4736", "Avery", ["L4736REV-25"], None, None),
            G48,
            actor="t",
        )
        await ts.create_type(
            s,
            ts.TypeFields(KEY_SMALL, "L4731", "Avery", ["L4731REV-25"], None, None),
            G_SMALL,
            actor="t",
        )
        yield s


async def make_printer(
    s: AsyncSession,
    rec: IppStatusRecord | None = None,
    *,
    backend: str = "ipp",
    enabled: bool = True,
    default_tray: bool = True,
    load_hint: str | None = None,
) -> Printer:
    p = Printer(
        id=uuid4(),
        name=f"P {uuid4().hex[:6]}",
        slug=f"p-{uuid4().hex[:6]}",
        model="m",
        backend=backend,
        connection={},
        enabled=enabled,
    )
    s.add(p)
    s.add(
        PrinterTray(
            printer_id=p.id,
            tray_key="auto",
            label="Auto",
            is_default=default_tray,
            load_hint=load_hint,
        )
    )
    s.add(PrinterTray(printer_id=p.id, tray_key="manual", label="Manual", is_default=False))
    s.add(
        PrinterTray(printer_id=p.id, tray_key="off", label="Off", enabled=False, is_default=False)
    )
    if rec is not None:
        s.add(
            PrinterStatusCache(
                printer_id=p.id,
                parsed=rec.model_dump(mode="json"),
                captured_at=datetime.now(UTC),
            )
        )
    await s.commit()
    return p


async def make_sheet(
    s: AsyncSession,
    used: int = 0,
    placement: str = "manual",
    key: str = KEY,
    feed_mark_printed: bool = False,
) -> str:
    sheet = await ss.create_sheet(
        s,
        type_key=key,
        version=None,
        id_placement=placement,  # type: ignore[arg-type]
        used_cells=[MarkedCell(n) for n in range(1, used + 1)],
        note=None,
        actor="t",
    )
    if feed_mark_printed:
        sheet.feed_mark_printed = True
        await s.commit()
    return sheet.code


class Spy:
    """Wraps ``render_preview_png`` and remembers how the preview called it."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[dict[str, Any]] = []
        original = print_service.render_preview_png

        def wrapper(geometry: Geometry, cells: Any, margin: Any, **kw: Any) -> bytes:
            self.calls.append({"geometry": geometry, "cells": cells, "margin": margin, **kw})
            return original(geometry, cells, margin, **kw)

        monkeypatch.setattr(print_service, "render_preview_png", wrapper)

    @property
    def feed_marks(self) -> list[FeedMarkPayload | None]:
        return [c.get("feed_mark") for c in self.calls]

    @property
    def margins(self) -> list[MarginIdPayload | None]:
        return [c["margin"] for c in self.calls]


async def run_preview(
    s: AsyncSession,
    printer: Printer,
    request: SheetPrintRequest,
    lookup: Any = None,
    language: str | None = "en",
) -> Any:
    return await print_service.preview(
        s,
        printer=printer,
        request=request,
        lookup=lookup or FakeLookup(),
        renderer=DEFAULT_CELL_RENDERER,
        language=language,
    )


def png_of(page: Any) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(page.png_base64)))


def px(v: float) -> int:
    return round(v * 150 / 2540)


# ---------------------------------------------------------------------------- the plan


async def test_preview_plan_and_png(session: AsyncSession) -> None:
    printer = await make_printer(session, record())
    code = await make_sheet(session, used=17)
    lookup = FakeLookup()

    out = await run_preview(
        session, printer, req([grocy(i) for i in range(9)], [on(code)]), lookup=lookup
    )

    (page,) = out.pages
    new_cells = [c for c in page.cells if c.state == "new"]
    assert [c.cell for c in new_cells] == list(range(18, 27))
    assert [c.item_index for c in new_cells] == list(range(9))
    assert out.free_after == [22]
    assert page.sheet_code == code
    assert page.new_code_hint is None
    png = png_of(page)
    assert (png.size, png.mode) == ((1240, 1754), "1")
    assert [(e.sheet, e.cells, e.id_cell) for e in out.expected_cells] == [
        (code, list(range(18, 27)), None)
    ]
    assert len(page.cells) == 48
    assert {c.state for c in page.cells} == {"used", "new", "free"}


async def test_preview_page_lists_every_cell_with_state_and_purpose(
    session: AsyncSession,
) -> None:
    printer = await make_printer(session, record())
    code = await make_sheet(session, used=1)
    sheet = (await session.execute(select(Sheet).where(Sheet.code == code))).scalar_one()
    now = datetime.now(UTC)
    for n, state in ((2, "reserved"), (3, "unconfirmed")):
        session.add(
            SheetCell(
                sheet_id=sheet.id,
                cell_no=n,
                state=state,
                source="api",
                purpose=f"was {state}",
                updated_at=now,
            )
        )
    await session.commit()

    out = await run_preview(session, printer, req([raw(0)], [on(code)]))

    by = {c.cell: c for c in out.pages[0].cells}
    assert by[1].state == "used" and by[1].purpose == "marked by hand"
    assert by[2].state == "reserved" and by[2].purpose == "was reserved"
    assert by[3].state == "unconfirmed" and by[3].purpose == "was unconfirmed"
    assert by[4].state == "new" and by[4].purpose == "Item 0" and by[4].item_index == 0
    assert by[5].state == "free" and by[5].purpose is None and by[5].item_index is None


async def test_preview_marks_mapped_cells(session: AsyncSession) -> None:
    printer = await make_printer(session, record())
    code = await make_sheet(session, key=KEY_SMALL)

    out = await run_preview(
        session,
        printer,
        req([raw(0, ContentType.QR_TWO_LINES), raw(1, ContentType.TEXT_TWO_LINES)], [on(code)]),
    )

    new = [c for c in out.pages[0].cells if c.state == "new"]
    assert [(c.cell, c.mapped) for c in new] == [(1, True), (2, False)]


async def test_preview_flags_truncated_and_hardware_margin_cells(session: AsyncSession) -> None:
    printer = await make_printer(
        session, record(margins=Margins(top=2200, left=2200, bottom=2200, right=2200))
    )
    code = await make_sheet(session)
    long = "W" * 400

    out = await run_preview(session, printer, req([raw(0, title=long), raw(1)], [on(code)]))

    c0, c1 = (c for c in out.pages[0].cells if c.state == "new")
    assert c0.truncated is True and c1.truncated is False
    assert c0.hw_margin is True  # 22 mm hardware margins reach into the first row
    free = next(c for c in out.pages[0].cells if c.state == "free")
    assert free.hw_margin is False  # only new cells are flagged


async def test_preview_content_mismatch_names_the_item(session: AsyncSession) -> None:
    printer = await make_printer(session, record())
    code = await make_sheet(session)
    bad = SheetItem(content_type=ContentType.QR_TWO_LINES, data=SheetRawLabelData(primary_id="X"))

    with pytest.raises(ItemContentMismatchError) as err:
        await run_preview(session, printer, req([raw(0), raw(1), bad], [on(code)]))

    assert err.value.status == 422
    assert err.value.error_code == "content_type_data_mismatch"
    assert err.value.detail is not None
    assert err.value.detail["item_index"] == 2
    assert set(err.value.detail["missing_fields"]) == {"qr_payload", "title"}


async def test_preview_draws_a_placeholder_for_a_qr_too_fine_for_150_dpi(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    dpis: list[int] = []
    original = DEFAULT_CELL_RENDERER.render

    def spy(**kw: Any) -> Any:
        dpis.append(kw["dpi"])
        return original(**kw)

    monkeypatch.setattr(DEFAULT_CELL_RENDERER, "render", spy, raising=False)
    printer = await make_printer(session, record(dpis=[600]))
    code = await make_sheet(session)
    dense = raw(0, qr_payload="".join(random.Random(3).choices("äöüßéñ", k=512)))

    out = await run_preview(session, printer, req([dense], [on(code)]))

    (cell,) = [c for c in out.pages[0].cells if c.state == "new"]
    assert cell.item_index == 0
    assert set(dpis) == {150}  # the preview never renders at the job's resolution
    # the placeholder is a hatched box with ink on both diagonals of the QR square
    box = content_box(G48, 1)
    edge = min(px(box.w), px(box.h))
    left, top = px(box.x), px(box.y)
    img = png_of(out.pages[0]).convert("L")
    square = img.crop((left, top, left + edge, top + edge))
    dark = sum(1 for v in square.getdata() if v == 0)
    assert 0.05 * edge * edge < dark < 0.6 * edge * edge


async def test_preview_refuses_a_qr_no_resolution_can_draw(session: AsyncSession) -> None:
    printer = await make_printer(session, record(dpis=[200]))  # 512 emoji need a finer grid
    code = await make_sheet(session)
    emoji = "".join(random.Random(4).choices("😀😁😂🤣😃😄", k=512))

    with pytest.raises(ItemContentMismatchError) as err:
        await run_preview(session, printer, req([raw(0), raw(1, qr_payload=emoji)], [on(code)]))

    assert err.value.detail is not None and err.value.detail["item_index"] == 1
    assert err.value.detail["missing_fields"] == ["qr_payload"]


async def test_preview_carries_the_tray_load_hint(session: AsyncSession) -> None:
    printer = await make_printer(session, record(), load_hint="Print side up, top edge first")
    code = await make_sheet(session)

    out = await run_preview(session, printer, req([raw(0)], [on(code)]))

    assert out.pages[0].load_hint == "Print side up, top edge first"


async def test_preview_discarded_sheet_is_refused(session: AsyncSession) -> None:
    printer = await make_printer(session, record())
    code = await make_sheet(session)
    await ss.discard_sheet(session, code, actor="t")

    with pytest.raises(SheetDiscardedError):
        await run_preview(session, printer, req([raw(0)], [on(code)]))


# ---------------------------------------------------------------------------- no side effects


async def _state(s: AsyncSession) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for model in (Sheet, SheetCell, SheetIdCounter, Job):
        out[model.__name__] = (await s.execute(select(func.count()).select_from(model))).scalar()
    out["lock_seq"] = (await s.execute(text("SELECT seq FROM sheet_write_lock"))).scalar()
    return out


async def test_preview_has_no_side_effects(session: AsyncSession) -> None:
    printer = await make_printer(session, record())
    code = await make_sheet(session, used=3)
    before = await _state(session)

    await run_preview(
        session,
        printer,
        req([grocy(i) for i in range(6)], [on(code, count=2), fresh("cell", count=4)]),
    )

    assert await _state(session) == before
    assert await ss.peek_next_code(session, KEY) == "L4736-0002"  # no counter step was taken


# ---------------------------------------------------------------------------- reprint hints


async def _printed_before(
    s: AsyncSession, code: str, cell: int, state: str, ref: str, source: str = "grocy"
) -> datetime:
    sheet = (await s.execute(select(Sheet).where(Sheet.code == code))).scalar_one()
    when = datetime(2026, 11, 1, 12, 30, tzinfo=UTC)
    s.add(
        SheetCell(
            sheet_id=sheet.id,
            cell_no=cell,
            state=state,
            source=source,
            purpose="Milk",
            ref=ref,
            updated_at=when,
        )
    )
    await s.commit()
    return when


async def test_preview_reprint_hint(session: AsyncSession) -> None:
    printer = await make_printer(session, record())
    old = await make_sheet(session)
    when = await _printed_before(session, old, 5, "used", "42")
    target = await make_sheet(session)

    out = await run_preview(session, printer, req([grocy(7), grocy(42)], [on(target)]))

    (hint,) = out.reprint_hints
    assert (hint.item_index, hint.sheet_code, hint.cell) == (1, old, 5)
    assert hint.printed_at.replace(tzinfo=UTC) == when


async def test_preview_reprint_hint_only_from_used_cells(session: AsyncSession) -> None:
    printer = await make_printer(session, record())
    old = await make_sheet(session)
    await _printed_before(session, old, 5, "reserved", "42")
    await _printed_before(session, old, 6, "unconfirmed", "42")
    target = await make_sheet(session)

    out = await run_preview(session, printer, req([grocy(42)], [on(target)]))

    assert out.reprint_hints == []


async def test_preview_reprint_hint_ignores_other_sources_and_raw_items(
    session: AsyncSession,
) -> None:
    printer = await make_printer(session, record())
    old = await make_sheet(session)
    await _printed_before(session, old, 5, "used", "42", source="snipeit")
    await _printed_before(session, old, 6, "used", "R-0", source="api")
    target = await make_sheet(session)

    out = await run_preview(session, printer, req([grocy(42), raw(0)], [on(target)]))

    assert out.reprint_hints == []


# ---------------------------------------------------------------------------- new sheets


async def test_preview_new_sheet_hint(session: AsyncSession) -> None:
    printer = await make_printer(session, record())
    await make_sheet(session)
    await make_sheet(session)  # the counter now stands at 3

    out = await run_preview(session, printer, req([raw(0), raw(1)], [fresh("cell")]))

    (page,) = out.pages
    assert page.sheet_code is None
    assert page.new_code_hint == "L4736-0003"
    ids = [c for c in page.cells if c.is_id]
    assert [(c.cell, c.state, c.purpose) for c in ids] == [(1, "new", "Sheet ID")]
    assert page.margin_id is False
    assert [e.sheet for e in out.expected_cells] == ["new"]
    assert out.expected_cells[0].id_cell == 1


async def test_preview_new_sheet_defaults_to_margin_id(session: AsyncSession) -> None:
    printer = await make_printer(session, record(margins=None))

    out = await run_preview(session, printer, req([raw(0)], [fresh()]))

    (page,) = out.pages
    assert [c for c in page.cells if c.is_id] == []
    assert page.margin_id is True
    assert page.margin_band == "top"
    assert page.id_not_printed is False
    assert page.new_code_hint == "L4736-0001"


async def test_preview_two_new_sheets_of_a_type_get_consecutive_hints(
    session: AsyncSession,
) -> None:
    printer = await make_printer(session, record())

    out = await run_preview(
        session, printer, req([raw(i) for i in range(4)], [fresh(count=2), fresh()])
    )

    assert [p.new_code_hint for p in out.pages] == ["L4736-0001", "L4736-0002"]


async def test_preview_margin_payload_uses_the_hint_for_a_new_sheet_and_the_code_otherwise(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = Spy(monkeypatch)
    printer = await make_printer(session, record())
    code = await make_sheet(session, placement="margin")

    await run_preview(session, printer, req([raw(0), raw(1)], [on(code, count=1), fresh(count=1)]))

    existing, new = spy.margins
    assert existing is not None and existing.qr_payload is not None
    assert existing.qr_payload.endswith(f"/sheet/{code}")
    assert new is not None and new.qr_payload is not None
    assert new.qr_payload.endswith("/sheet/L4736-0002")
    assert "L4736-0002" in new.text and "Avery L4736REV-25" in new.text


async def test_preview_margin_band_and_unprintable(session: AsyncSession) -> None:
    open_printer = await make_printer(session, record(margins=None))
    tight_printer = await make_printer(
        session, record(margins=Margins(top=2000, left=2000, bottom=2000, right=2000))
    )

    out = await run_preview(session, open_printer, req([raw(0)], [fresh()]))
    assert out.pages[0].margin_band == "top"

    out = await run_preview(session, tight_printer, req([raw(0)], [fresh()]))
    (page,) = out.pages
    assert page.margin_band is None
    assert page.id_not_printed is True
    assert page.margin_id is False


async def test_preview_never_answered_printer_counts_as_600_dpi_and_5_mm(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = Spy(monkeypatch)
    placeholder = _offline_record(None)
    printer = await make_printer(session, placeholder)

    out = await run_preview(session, printer, req([raw(0)], [fresh()]))

    assert spy.calls[0]["render_dpi"] == 600
    assert out.pages[0].margin_band == "top"


async def test_preview_passes_the_jobs_render_dpi(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = Spy(monkeypatch)
    low = await make_printer(session, record(dpis=[150, 300]))
    high = await make_printer(session, record(dpis=[600, 1200]))

    await run_preview(session, low, req([raw(0)], [fresh()]))
    await run_preview(session, high, req([raw(0)], [fresh()]))

    assert [c["render_dpi"] for c in spy.calls] == [300, 600]


async def test_preview_margin_depth_follows_the_trays_calibration(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = Spy(monkeypatch)
    printer = await make_printer(
        session, record(margins=Margins(top=500, left=500, bottom=500, right=500))
    )
    await calibration_service.put(
        session,
        printer.id,
        "auto",
        CalibrationIn(offset_x_mm=0, offset_y_mm=-0.8),
        measured_on=None,
        actor="t",
    )

    await run_preview(session, printer, req([raw(0)], [fresh()]))  # default tray: calibrated
    await run_preview(session, printer, req([raw(0)], [fresh()], tray="manual"))  # identity

    # top band: 2150 - 500 (hardware) - |dy| - 100 (safety)
    assert [m.usable_hmm for m in spy.margins if m is not None] == [1470, 1550]


# ---------------------------------------------------------------------------- feed mark


async def test_preview_feed_mark_follows_hub_language(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = Spy(monkeypatch)
    printer = await make_printer(session, record())

    for language in ("de", "en", None, "fr"):
        code = await make_sheet(session)  # a fresh manual sheet each time
        await run_preview(session, printer, req([raw(0)], [on(code)]), language=language)

    texts = [m.text if m is not None else None for m in spy.feed_marks]
    assert texts == [
        "▲ Oben \u2013 diese Kante zuerst",
        "▲ Top \u2013 this edge first",
        "▲ Top \u2013 this edge first",
        "▲ Top \u2013 this edge first",
    ]


async def test_preview_shows_feed_mark(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = Spy(monkeypatch)
    printer = await make_printer(session, record())
    fresh_code = await make_sheet(session)
    marked_code = await make_sheet(session, feed_mark_printed=True)

    out = await run_preview(
        session, printer, req([raw(0), raw(1)], [on(fresh_code, count=1), on(marked_code)])
    )

    with_mark, without = out.pages
    assert with_mark.feed_mark is True and without.feed_mark is False
    mark = spy.feed_marks[0]
    assert mark is not None and spy.feed_marks[1] is None
    band = (px(mark.x_hmm), 0, px(G48.page_w), px(G48.margin_top))
    assert png_of(with_mark).convert("L").crop(band).getextrema()[0] == 0  # ink
    top = (0, 0, px(G48.page_w), px(G48.margin_top))
    assert png_of(without).convert("L").crop(top).getextrema()[0] == 255  # blank


async def test_preview_feed_mark_does_not_make_a_page_on_its_own(session: AsyncSession) -> None:
    printer = await make_printer(session, record())
    code = await make_sheet(session)

    out = await run_preview(session, printer, req([raw(0)], [on(code)]))

    assert out.pages[0].feed_mark is True
    assert [c.cell for c in out.pages[0].cells if c.state == "new"] == [1]


# ---------------------------------------------------------------------------- bounds and kinds


async def test_preview_page_bound(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    spy = Spy(monkeypatch)
    rendered: list[int] = []
    original = DEFAULT_CELL_RENDERER.render

    def counting(**kw: Any) -> Any:
        rendered.append(1)
        return original(**kw)

    monkeypatch.setattr(DEFAULT_CELL_RENDERER, "render", counting, raising=False)
    printer = await make_printer(session, record())
    placements = [fresh(count=1) for _ in range(11)]

    with pytest.raises(PreviewTooLargeError) as err:
        await run_preview(session, printer, req([raw(i) for i in range(11)], placements))

    assert err.value.status == 422 and err.value.error_code == "preview_too_large"
    assert err.value.detail == {"pages": 11, "max": 10}
    assert spy.calls == [] and rendered == []


async def test_preview_renders_exactly_the_bound(session: AsyncSession) -> None:
    printer = await make_printer(session, record())
    placements = [fresh(count=1) for _ in range(10)]

    out = await run_preview(session, printer, req([raw(i) for i in range(10)], placements))

    assert len(out.pages) == 10


async def test_preview_refusals_make_no_lookups(session: AsyncSession) -> None:
    printer = await make_printer(session, record())
    nearly_full = await make_sheet(session, used=47)
    lookup = FakeLookup()

    with pytest.raises(PreviewTooLargeError):
        await run_preview(
            session,
            printer,
            req([grocy(i) for i in range(11)], [fresh(count=1) for _ in range(11)]),
            lookup=lookup,
        )
    with pytest.raises(SheetNotFoundError):
        await run_preview(session, printer, req([grocy(1)], [on("L4736-9999")]), lookup=lookup)
    with pytest.raises(InsufficientCellsError):
        await run_preview(
            session, printer, req([grocy(1), grocy(2)], [on(nearly_full)]), lookup=lookup
        )

    assert lookup.calls == []


async def test_preview_refuses_a_tape_printer(session: AsyncSession) -> None:
    tape = await make_printer(session, backend="mock")
    code = await make_sheet(session)
    lookup = FakeLookup()

    with pytest.raises(MediaKindMismatchError):
        await run_preview(session, tape, req([grocy(1)], [on(code)]), lookup=lookup)

    assert lookup.calls == []  # nothing was looked up for a printer that cannot print this


@pytest.mark.parametrize("tray", ["off", "nope"])
async def test_preview_refuses_a_disabled_or_unknown_tray(session: AsyncSession, tray: str) -> None:
    printer = await make_printer(session, record())
    code = await make_sheet(session)

    with pytest.raises(TrayUnknownError) as err:
        await run_preview(session, printer, req([raw(0)], [on(code)], tray=tray))

    assert err.value.detail == {"trays": [tray]}


# ---------------------------------------------------------------------------- resolve_tray


async def test_resolve_tray_default_named_and_errors(session: AsyncSession) -> None:
    printer = await make_printer(session, record())
    no_default = await make_printer(session, record(), default_tray=False)

    assert await calibration_service.resolve_tray(session, printer.id, None) == "auto"
    assert await calibration_service.resolve_tray(session, printer.id, "manual") == "manual"
    with pytest.raises(TrayUnknownError):
        await calibration_service.resolve_tray(session, printer.id, "off")
    with pytest.raises(TrayUnknownError):
        await calibration_service.resolve_tray(session, no_default.id, None)


async def test_resolve_tray_default_must_be_enabled(session: AsyncSession) -> None:
    printer = await make_printer(session, record())
    tray = await session.get(PrinterTray, (printer.id, "auto"))
    assert tray is not None
    tray.enabled = False
    await session.commit()

    with pytest.raises(TrayUnknownError):
        await calibration_service.resolve_tray(session, printer.id, None)


# ---------------------------------------------------------------------------- printer facts


async def test_printer_facts_read_resolution_and_margins(session: AsyncSession) -> None:
    margins = Margins(top=100, left=200, bottom=300, right=400)
    p1 = await make_printer(session, record(dpis=[300, 1200], margins=margins))
    p2 = await make_printer(session, record(dpis=[], margins=None))

    f1 = await load_printer_facts(session, p1.id)
    f2 = await load_printer_facts(session, p2.id)

    assert (f1.render_dpi, f1.margins_hmm, f1.resolutions_dpi) == (600, margins, [300, 1200])
    assert (f2.render_dpi, f2.margins_hmm) == (600, None)


async def test_printer_facts_placeholder_and_missing_cache_are_unknown(
    session: AsyncSession,
) -> None:
    placeholder = _offline_record(None)
    p1 = await make_printer(session, placeholder)
    p2 = await make_printer(session)

    for p in (p1, p2):
        f = await load_printer_facts(session, p.id)
        assert (f.render_dpi, f.margins_hmm, f.resolutions_dpi) == (600, None, [])


async def test_printer_facts_use_the_highest_resolution_capped_at_600(
    session: AsyncSession,
) -> None:
    low = await make_printer(session, record(dpis=[150, 300]))

    assert (await load_printer_facts(session, low.id)).render_dpi == 300


# ---------------------------------------------------------------------------- resolve_items


async def test_resolve_items_raw_and_lookup() -> None:
    lookup = FakeLookup()
    items = [raw(0, purpose="Shelf label", source="shelf", ref="r-0"), grocy(42)]

    out = await resolve_items(items, lookup)  # type: ignore[arg-type]

    assert out[0].label.source_app == "manual" and out[0].label.title == "Item 0"
    assert (out[0].meta.source, out[0].meta.purpose, out[0].meta.ref) == (
        "shelf",
        "Shelf label",
        "r-0",
    )
    assert out[1].label.primary_id == "G-42"
    assert (out[1].meta.source, out[1].meta.purpose, out[1].meta.ref) == (
        "grocy",
        "Product 42",
        "42",
    )
    assert out[1].content_type == ContentType.QR_TWO_LINES
    assert lookup.calls == [("grocy", "42")]


async def test_resolve_items_default_source_and_purpose_chain() -> None:
    items = [
        raw(0),  # purpose from the title
        SheetItem(
            content_type=ContentType.QR_ONLY,
            data=SheetRawLabelData(qr_payload="https://x.example.invalid/1", primary_id="ONLY-ID"),
        ),
        SheetItem(
            content_type=ContentType.QR_ONLY,
            data=SheetRawLabelData(qr_payload="https://x.example.invalid/2"),
        ),
    ]

    out = await resolve_items(items, FakeLookup())  # type: ignore[arg-type]

    assert [m.meta.source for m in out] == ["api", "api", "api"]
    assert [m.meta.purpose for m in out] == ["Item 0", "ONLY-ID", "Label"]
    assert [m.meta.ref for m in out] == [None, None, None]


async def test_resolve_items_cleans_an_explicit_purpose() -> None:
    items = [raw(0, purpose="Two\x07 ‮parts\n here")]

    out = await resolve_items(items, FakeLookup())  # type: ignore[arg-type]

    assert out[0].meta.purpose == "Two parts here"


async def test_resolve_items_cuts_a_long_default_purpose_instead_of_refusing() -> None:
    # A raw title is capped at 512 by the request schema; a lookup's title is not (OC-43, C13).
    class LongTitle(FakeLookup):
        async def lookup(self, source_app: str, identifier: str) -> LabelData:
            return LabelData(source_app=source_app, title="T" * 10_000, primary_id="P")

    items = [raw(0, title="T" * 512), grocy(1)]

    out = await resolve_items(items, LongTitle())  # type: ignore[arg-type]

    assert [o.meta.purpose for o in out] == ["T" * 120, "T" * 120]


async def test_resolve_items_runs_at_most_eight_lookups_at_once() -> None:
    lookup = FakeLookup(default_delay=0.02)

    out = await resolve_items([grocy(i) for i in range(40)], lookup)  # type: ignore[arg-type]

    assert len(out) == 40
    assert 2 <= lookup.max_in_flight <= 8
    assert [o.label.primary_id for o in out] == [f"G-{i}" for i in range(40)]  # request order


async def test_resolve_items_reports_the_lowest_failing_index() -> None:
    # Item 20 fails at once; item 3 fails later: the answer names 3, not the first to finish.
    lookup = FakeLookup(
        fail={"3": LookupFailedError("boom"), "20": LookupFailedError("boom")},
        delays={"3": 0.08},
    )

    with pytest.raises(ItemLookupFailedError) as err:
        await resolve_items([grocy(i) for i in range(30)], lookup)  # type: ignore[arg-type]

    assert err.value.detail == {"item_index": 3}


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (
            UnknownAppError("no such app: secret-host.example.invalid"),
            422,
            "integration_unknown_app",
        ),
        (
            LookupFailedError("http://secret-host.example.invalid/api failed"),
            502,
            "integration_lookup_failed",
        ),
        (
            AppLookupNotFoundError("secret-host.example.invalid has no such item"),
            404,
            "app-lookup-not-found",
        ),
        (
            IntegrationNotConfiguredError("secret-host.example.invalid has no url"),
            503,
            "integration_not_configured",
        ),
    ],
)
async def test_resolve_items_carries_status_and_code_of_the_underlying_error(
    exc: Exception, status: int, code: str
) -> None:
    lookup = FakeLookup(fail={"5": exc})

    with pytest.raises(ItemLookupFailedError) as err:
        await resolve_items([grocy(i) for i in range(8)], lookup)  # type: ignore[arg-type]

    assert (err.value.status, err.value.error_code) == (status, code)
    assert err.value.detail == {"item_index": 5}
    assert "secret-host" not in err.value.message  # fixed text, never the upstream's


async def test_resolve_items_unexpected_error_is_not_swallowed() -> None:
    lookup = FakeLookup(fail={"1": RuntimeError("bug")})

    with pytest.raises(RuntimeError):
        await resolve_items([grocy(0), grocy(1)], lookup)  # type: ignore[arg-type]


async def test_identical_lookups_run_once_and_fan_out() -> None:
    lookup = FakeLookup()

    out = await resolve_items([grocy(42) for _ in range(40)], lookup)  # type: ignore[arg-type]

    assert lookup.calls == [("grocy", "42")]
    assert [o.label.primary_id for o in out] == ["G-42"] * 40
    assert [o.meta.ref for o in out] == ["42"] * 40


async def test_deduplicated_lookups_still_report_the_lowest_failing_index() -> None:
    # "9" fails fast, "4" fails slowly; item 1 is the first copy of "4", item 0 is fine.
    lookup = FakeLookup(
        fail={"4": LookupFailedError("x"), "9": LookupFailedError("x")}, delays={"4": 0.05}
    )
    items = [grocy(1), grocy(4), grocy(9), grocy(4), grocy(9)]

    with pytest.raises(ItemLookupFailedError) as err:
        await resolve_items(items, lookup)  # type: ignore[arg-type]

    assert err.value.detail == {"item_index": 1}
    assert sorted(lookup.calls) == [("grocy", "1"), ("grocy", "4"), ("grocy", "9")]


async def test_preview_renders_at_most_two_pages_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    import threading
    import time

    lock = threading.Lock()
    state = {"now": 0, "max": 0}

    def slow(*_a: Any, **_k: Any) -> Any:
        with lock:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        time.sleep(0.15)
        with lock:
            state["now"] -= 1
        return "drawn"

    monkeypatch.setattr(print_service, "_draw_page", slow)

    results = await asyncio.gather(*(print_service.draw_page_bounded() for _ in range(5)))

    assert results == ["drawn"] * 5
    assert state["max"] == 2


async def test_public_margin_payload_builder_matches_what_the_preview_draws(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = Spy(monkeypatch)
    printer = await make_printer(session, record())
    await run_preview(session, printer, req([raw(0)], [fresh()]))
    drawn = spy.margins[0]
    placements, infos, _ = await print_service._placements(session, req([raw(0)], [fresh()]))
    scan = print_service.scan_payload_builder("http://localhost:8000")
    from app.sheets.planner import MarginContext, plan

    margin = MarginContext(deviation=Deviation(), scan_payload=scan, render_dpi=600, language="en")
    pl = plan(placements, 1, hw_margins_hmm=None, margin=margin)
    built = print_service.page_margin_id_payload(
        pl.pages[0], infos[id(placements[0].sheet)].type_label, scan
    )

    assert built == drawn
    assert built is not None and built.text_end_hmm is not None  # shares the top band


def test_qr_module_cache_never_holds_an_oversized_payload() -> None:
    cache = cell_render._qr_version_cached
    cache.cache_clear()

    assert print_service._qr_modules("x" * 5000) is None
    assert cache.cache_info().currsize == 0  # not cached, not even as a key


def test_qr_module_cache_keeps_a_normal_payload() -> None:
    cache = cell_render._qr_version_cached
    cache.cache_clear()
    payload = "https://r.example.invalid/1"

    first = print_service._qr_modules(payload)
    second = print_service._qr_modules(payload)

    assert first == second and first is not None
    assert (cache.cache_info().currsize, cache.cache_info().hits) == (1, 1)


def test_qr_module_count_is_found_without_building_the_matrix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import qrcode.main

    def boom(self: Any, *a: Any, **k: Any) -> None:
        raise AssertionError("the matrix must not be built to learn the symbol size")

    monkeypatch.setattr(qrcode.main.QRCode, "make", boom)
    cell_render._qr_version_cached.cache_clear()

    assert print_service._qr_modules("https://r.example.invalid/1") is not None


def test_qr_module_count_equals_the_symbol_build_qr_makes() -> None:
    import random
    import string

    import qrcode
    import qrcode.constants

    rnd = random.Random(20261107)
    alphabets = [
        string.digits,
        string.ascii_uppercase + string.digits + " $%*+-./:",
        string.ascii_letters + string.digits + "/:.-_?=&%",
        "äöüß€ñ中文 " + string.ascii_letters,
    ]
    for _ in range(2000):
        alphabet = rnd.choice(alphabets)
        payload = "".join(rnd.choices(alphabet, k=rnd.randint(1, 512)))
        qr = qrcode.QRCode(
            version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, border=4
        )
        qr.add_data(payload)
        qr.make(fit=True)
        assert print_service._qr_modules(payload) == len(qr.get_matrix()) - 8, payload


def test_the_placeholder_hatch_stays_inside_the_qr_square() -> None:
    image = Image.new("1", (300, 100), 1)
    for y in range(100):
        image.putpixel((130, y), 0)  # text just right of a 100 px QR square
    before = image.copy()

    print_service._qr_placeholder(image, 100)

    outside = (100, 0, 300, 100)
    assert list(image.crop(outside).getdata()) == list(before.crop(outside).getdata())
    assert sum(1 for v in image.crop((0, 0, 100, 100)).getdata() if v == 0) > 300  # hatched


async def test_a_lookup_qr_payload_over_512_characters_is_refused_with_its_index() -> None:
    class LongPayload(FakeLookup):
        async def lookup(self, source_app: str, identifier: str) -> LabelData:
            label = await super().lookup(source_app, identifier)
            if identifier == "2":
                return label.model_copy(update={"qr_payload": "https://g/" + "x" * 600})
            return label

    with pytest.raises(ItemContentMismatchError) as err:
        await resolve_items([grocy(1), grocy(2)], LongPayload())  # type: ignore[arg-type]

    assert err.value.detail == {"item_index": 1, "missing_fields": ["qr_payload"]}


def test_a_raw_qr_payload_is_capped_at_512_characters() -> None:
    ok = raw(0, qr_payload="x" * 512)
    assert ok.data is not None and len(ok.data.qr_payload or "") == 512

    with pytest.raises(ValueError, match="qr_payload"):
        raw(0, qr_payload="x" * 513)


async def test_preview_skips_the_qr_mask_search_but_the_job_renderer_keeps_it(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    import qrcode.main
    from app.sheets.cell_render import build_qr

    searched: list[int] = []
    original = qrcode.main.QRCode.best_mask_pattern

    def counting(self: Any) -> int:
        searched.append(1)
        return original(self)

    monkeypatch.setattr(qrcode.main.QRCode, "best_mask_pattern", counting)
    printer = await make_printer(session, record())
    code = await make_sheet(session)

    await run_preview(session, printer, req([raw(0), raw(1)], [on(code)]))
    assert searched == []  # a picture does not need the best of eight masks

    assert build_qr("https://r.example.invalid/1", 200) is not None
    assert searched == [1]  # what a job prints still does


def test_build_qr_draws_the_same_pixels_as_the_library_image_without_its_slow_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import random
    import string

    import qrcode
    import qrcode.constants
    import qrcode.main
    from app.sheets.cell_render import build_qr

    rnd = random.Random(7)
    payloads = [
        "".join(rnd.choices(string.ascii_letters + string.digits + "/:.-_", k=rnd.randint(1, 400)))
        for _ in range(25)
    ]

    def reference(payload: str, edge_px: int) -> Image.Image:
        qr = qrcode.QRCode(
            version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, border=4
        )
        qr.add_data(payload)
        qr.make(fit=True)
        qr.box_size = edge_px // len(qr.get_matrix())
        symbol = qr.make_image(fill_color="black", back_color="white").convert("1")
        canvas = Image.new("1", (edge_px, edge_px), 1)
        canvas.paste(symbol, ((edge_px - symbol.width) // 2, (edge_px - symbol.height) // 2))
        return canvas

    expected = [reference(p, 425) for p in payloads]

    def boom(self: Any, *a: Any, **k: Any) -> None:
        raise AssertionError("the library's per-module drawing is the slow path")

    monkeypatch.setattr(qrcode.main.QRCode, "make_image", boom)
    for payload, want in zip(payloads, expected, strict=True):
        got = build_qr(payload, 425)
        assert got is not None and got.tobytes() == want.tobytes()


def test_an_item_cannot_claim_the_sheet_id_source() -> None:
    with pytest.raises(ValueError, match="reserved"):
        raw(0, source="hub")


def test_scan_payload_builder() -> None:
    build = print_service.scan_payload_builder("https://hub.example.invalid/sub/")
    assert build("L4736-0001") == "https://hub.example.invalid/sub/sheet/L4736-0001"
    assert print_service.scan_payload_builder("")("L4736-0001") == "sheet:L4736-0001"
