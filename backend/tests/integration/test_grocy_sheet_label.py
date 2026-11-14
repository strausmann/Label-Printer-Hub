# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Grocy labels onto the sheets of a page printer (#281, R-281-13 to R-281-17).

The real app and lifespan run against a temp database with one IPP page printer in front of
``FakeIppPrinter`` and one tape printer behind a recording ``MockPrinterBackend``. The battery
type is mapped to the page printer and the sheet type ``acme-t1`` (4 x 12 cells). Every wait
is bounded; cells are polled in the database (C15: the job state alone says nothing about them).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import app.models  # noqa: F401
import httpx
import pytest
from app.auth.verifier import _cache as verifier_cache
from app.config import get_settings
from app.models.job import Job
from app.models.printer import Printer
from app.models.sheet import Sheet, SheetCell
from app.printer_backends.ipp.attributes import Margins
from app.printer_backends.mock_backend import MockPrinterBackend
from app.schemas.grocy_label import GROCY_LABEL_BUDGET_S
from app.services.backend_router import BackendRouter
from app.services.event_bus import BusEvent
from app.services.print_queue import PrintQueue
from app.services.rate_limiter import _rate_limiter
from app.sheets import print_service as sheet_print_service
from app.sheets import type_service as ts
from app.sheets.geometry import Geometry
from app.sheets.grocy_sheet import GrocySheetLabels
from app.sheets.reservation import ItemMeta, PlacementRequest
from httpx import ASGITransport
from sqlalchemy import func, select

from tests.helpers.fake_ipp_printer import FakeIppPrinter
from tests.integration.api.test_sheet_print_api import _printer, _sheet, _type
from tests.integration.api.test_sheet_types_api import _factory, _insert_key

pytestmark = pytest.mark.asyncio

URL = "/api/v1/webhook/grocy/label"
WAIT_S = 5.0
TYPE = "acme-t1"
BATTERY = {"battery": "Smoke detector", "grocycode": "grcy:b:4"}
PRODUCT = {"product": "Oat milk", "grocycode": "grcy:p:12"}
MAPPING = {
    "integrations.grocy.label.enabled": True,
    "integrations.grocy.label.battery.printer": "page-1",
    "integrations.grocy.label.battery.sheet_type": TYPE,
}


@dataclass
class Rig:
    client: httpx.AsyncClient
    app: Any
    fake: FakeIppPrinter
    tape: MockPrinterBackend
    page_id: UUID
    token: str
    restricted: str
    key: dict[str, str]
    events: list[BusEvent] = field(default_factory=list)

    async def post(self, body: Any = BATTERY, *, token: str | None = None, **kw: Any) -> Any:
        if "content" not in kw:
            kw["json"] = body
        return await self.client.post(f"{URL}?token={token or self.token}", **kw)

    def print_jobs(self) -> int:
        return sum(1 for r in self.fake.received if r.operation == "Print-Job")

    def job_events(self, job_id: str) -> list[tuple[str, str]]:
        return [
            (str(e.data["from_state"]), str(e.data["to_state"]))
            for e in self.events
            if e.event_type == "job.state_changed" and e.data.get("job_id") == job_id
        ]


@pytest.fixture(autouse=True)
def _tape_backend(monkeypatch: pytest.MonkeyPatch) -> MockPrinterBackend:
    backend = MockPrinterBackend()
    monkeypatch.setattr(BackendRouter, "_build_one", staticmethod(lambda _cfg: backend))
    monkeypatch.setattr(
        "app.services.printer_runtime._resolve_model_id_from_config",
        AsyncMock(return_value="PT-P750W"),
    )
    get_settings.cache_clear()
    _rate_limiter.clear()
    verifier_cache.clear()
    return backend


async def _seed_base() -> tuple[UUID, str, str, dict[str, str]]:
    await _type()
    page_id = await _printer("page-1")
    async with _factory()() as s:
        s.add(
            Printer(
                name="Tape",
                slug="tape-1",
                model="PT-P750W",
                backend="ptouch",
                connection={"host": "198.51.100.10", "port": 9100},
                enabled=True,
            )
        )
        await s.commit()
    token = await _insert_key(["print"])
    restricted = await _insert_key(["print"], allowed_printer_ids=[str(uuid4())])
    key = {"X-Label-Hub-Key": token}
    return page_id, token, restricted, key


@asynccontextmanager
async def running(
    tape: MockPrinterBackend,
    settings: dict[str, Any] | None = None,
    *,
    fake: FakeIppPrinter | None = None,
    seeded: tuple[UUID, str, str, dict[str, str]] | None = None,
) -> AsyncIterator[Rig]:
    from app.main import create_app

    fake = fake or FakeIppPrinter(job_script=[9])  # done at the first poll
    page_id, token, restricted, key = seeded or await _seed_base()
    app = create_app()._app
    app.state.ipp_transport_factory = lambda _uri: ASGITransport(app=fake)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client,
    ):
        async with _factory()() as s:
            await app.state.settings_store.set_many(s, {**MAPPING, **(settings or {})})
        rig = Rig(client, app, fake, tape, page_id, token, restricted, key)
        channel = f"printer:{page_id}:queue"
        queue = app.state.event_bus.subscribe(channel, "t8b-events")

        async def _drain() -> None:
            while True:
                event = await queue.get()
                if event is not None:
                    rig.events.append(event)

        drain = asyncio.create_task(_drain())
        try:
            yield rig
        finally:
            drain.cancel()
            app.state.event_bus.unsubscribe(channel, "t8b-events")


async def _until(predicate: Callable[[], Awaitable[bool]], timeout: float = WAIT_S) -> None:
    async with asyncio.timeout(timeout):
        while not await predicate():
            await asyncio.sleep(0.02)


async def _job(job_id: str | UUID) -> Job:
    async with _factory()() as s:
        row = await s.get(Job, UUID(str(job_id)), populate_existing=True)
    assert row is not None
    return row


async def _ends(job_id: str, state: str) -> Job:
    async def _in_state() -> bool:
        row = await _job(job_id)
        if row.state != state and row.state in ("done", "failed", "failed_restart", "cancelled"):
            raise AssertionError(f"job ended {row.state} ({row.error}), expected {state}")
        return row.state == state

    await _until(_in_state)
    return await _job(job_id)


async def _cells() -> list[tuple[str, SheetCell]]:
    async with _factory()() as s:
        rows = await s.execute(
            select(Sheet.code, SheetCell)
            .join(Sheet, Sheet.id == SheetCell.sheet_id)
            .order_by(Sheet.code, SheetCell.cell_no)
        )
        return [(code, cell) for code, cell in rows.all()]


async def _grocy_cells() -> list[tuple[str, int, str]]:
    return [(code, c.cell_no, c.state) for code, c in await _cells() if c.source == "grocy"]


async def _sheet_codes() -> list[str]:
    async with _factory()() as s:
        return list((await s.execute(select(Sheet.code).order_by(Sheet.code))).scalars())


async def _sheet_row(code: str) -> Sheet:
    async with _factory()() as s:
        return (await s.execute(select(Sheet).where(Sheet.code == code))).scalar_one()


async def _job_count() -> int:
    async with _factory()() as s:
        return int((await s.execute(select(func.count()).select_from(Job))).scalar_one())


def _code(resp: Any) -> str:
    return str(resp.json()["detail"]["error_code"])


async def _settled(n: int) -> bool:
    """``n`` Grocy cells, all ``used`` (the outcome handler runs after the job ends, C15)."""
    cells = await _grocy_cells()
    return len(cells) == n and all(state == "used" for _c, _n, state in cells)


async def _used(code: str, cell: int) -> bool:
    return any(c == code and n == cell and st == "used" for c, n, st in await _grocy_cells())


class _Gate:
    """Holds ``PrintQueue.submit_stored_page_job`` until released (the hand-off)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.before: Callable[[UUID], Awaitable[None]] | None = None
        self.passed = 0  # hand-offs that went on after the release
        original = PrintQueue.submit_stored_page_job
        gate = self

        async def held(queue: PrintQueue, printer_id: UUID, payload: Any, **kw: Any) -> UUID:
            gate.entered.set()
            if gate.before is not None:
                await gate.before(kw["job_id"])
            await gate.release.wait()
            gate.passed += 1
            return await original(queue, printer_id, payload, **kw)

        monkeypatch.setattr(PrintQueue, "submit_stored_page_job", held)

    async def wait_entered(self) -> None:
        async with asyncio.timeout(WAIT_S):
            await self.entered.wait()


# ---------------------------------------------------------------------------- printing


async def test_battery_label_goes_to_the_started_sheet(_tape_backend: MockPrinterBackend) -> None:
    seeded = await _seed_base()
    code = await _sheet(used=5)
    async with running(_tape_backend, seeded=seeded) as rig:
        resp = await rig.post()
        assert resp.status_code == 202, resp.text
        job_id = resp.json()["job_id"]
        await _until(lambda: _used(code, 6))
        row = await _ends(job_id, "done")
    (cell,) = [c for code_, c in await _cells() if c.source == "grocy"]
    assert (cell.cell_no, cell.state, cell.ref, cell.job_id) == (6, "used", "grcy:b:4", row.id)
    (item,) = row.payload["detail"]["cells"]
    assert item["cell"] == 6
    assert item["label_data"]["source_app"] == "grocy"
    assert item["label_data"]["qr_payload"] == "grcy:b:4"
    assert row.printer_id == rig.page_id
    assert rig.print_jobs() == 1
    assert rig.tape.printed_images == []


async def test_full_sheet_opens_a_new_sheet(_tape_backend: MockPrinterBackend) -> None:
    seeded = await _seed_base()
    full = await _sheet(used=48)
    async with running(_tape_backend, seeded=seeded) as rig:
        resp = await rig.post()
        assert resp.status_code == 202, resp.text
        await _ends(resp.json()["job_id"], "done")
        await _until(lambda: _settled(1))
    codes = await _sheet_codes()
    (new,) = [c for c in codes if c != full]
    assert await _grocy_cells() == [(new, 1, "used")]
    assert (await _sheet_row(new)).id_placement == "margin"


async def test_response_does_not_wait_for_the_reservation(
    _tape_backend: MockPrinterBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = await _seed_base()
    code = await _sheet(used=5)
    original = sheet_print_service.reserve

    async def slow(*args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(3.0)
        return await original(*args, **kwargs)

    monkeypatch.setattr(sheet_print_service, "reserve", slow)
    async with running(_tape_backend, seeded=seeded) as rig:
        started = time.monotonic()
        resp = await rig.post()
        elapsed = time.monotonic() - started
        assert resp.status_code == 202, resp.text
        assert elapsed < GROCY_LABEL_BUDGET_S, elapsed

        async def reserved() -> bool:
            return (code, 6, "reserved") in await _grocy_cells()

        await _until(reserved)
        await _until(lambda: _used(code, 6))


async def test_two_labels_at_once_take_different_cells(_tape_backend: MockPrinterBackend) -> None:
    seeded = await _seed_base()
    old = await _sheet(used=47)
    async with running(_tape_backend, seeded=seeded) as rig:
        first, second = await asyncio.gather(rig.post(), rig.post())
        assert (first.status_code, second.status_code) == (202, 202)
        for resp in (first, second):
            await _ends(resp.json()["job_id"], "done")
        await _until(lambda: _settled(2))
    (new,) = [c for c in await _sheet_codes() if c != old]
    assert sorted(await _grocy_cells()) == sorted([(old, 48, "used"), (new, 1, "used")])


async def test_two_labels_without_a_sheet_open_one_sheet(
    _tape_backend: MockPrinterBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without the per-type lock both tasks meet at the barrier, both choose a new sheet and two
    sheets open. With it, the first times out, reserves and leaves; the second then chooses the
    first one's sheet."""
    barrier = asyncio.Barrier(2)

    async def meet(_self: GrocySheetLabels, _code: str | None) -> None:
        with suppress(TimeoutError, asyncio.BrokenBarrierError):
            await asyncio.wait_for(barrier.wait(), 0.5)

    monkeypatch.setattr(GrocySheetLabels, "_after_choice", meet)
    async with running(_tape_backend) as rig:
        first, second = await asyncio.gather(rig.post(), rig.post())
        for resp in (first, second):
            assert resp.status_code == 202, resp.text
            await _ends(resp.json()["job_id"], "done")
        await _until(lambda: _settled(2))
    (only,) = await _sheet_codes()
    assert sorted(await _grocy_cells()) == [(only, 1, "used"), (only, 2, "used")]


async def test_sheet_filled_meanwhile_retries_once(
    _tape_backend: MockPrinterBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.sheets.planner import MarginContext
    from app.sheets.reservation import reserve

    seeded = await _seed_base()
    old = await _sheet(used=40)
    seen: list[str | None] = []

    async def fill(_self: GrocySheetLabels, code: str | None) -> None:
        seen.append(code)
        if code is None:
            return
        # A direct reservation of the rest (never a second Grocy label: it would wait on the
        # per-type lock).
        from app.page_render.transform import Deviation

        async with _factory()() as s:
            await reserve(
                s,
                placements=[PlacementRequest(sheet_code=code, new_sheet=None)],
                items=[ItemMeta("api", f"other {i}", None) for i in range(8)],
                expected=None,
                hw_margins_hmm=None,
                margin=MarginContext(Deviation(), lambda c: c, 600, None),
                required_type_key=None,
                actor="t",
            )

    monkeypatch.setattr(GrocySheetLabels, "_after_choice", fill)
    async with running(_tape_backend, seeded=seeded) as rig:
        resp = await rig.post()
        assert resp.status_code == 202, resp.text
        await _ends(resp.json()["job_id"], "done")
        await _until(lambda: _settled(1))
    assert seen == [old, None]
    (new,) = [c for c in await _sheet_codes() if c != old]
    assert await _grocy_cells() == [(new, 1, "used")]


# ---------------------------------------------------------------------------- refusals


@pytest.mark.parametrize("sheet_type", ["", "no-such-type", "archived"])
async def test_unusable_sheet_type_503(_tape_backend: MockPrinterBackend, sheet_type: str) -> None:
    """``test_empty_sheet_type_503``, ``test_unknown_sheet_type_503``,
    ``test_archived_sheet_type_503`` of the plan, one parametrised test."""
    seeded = await _seed_base()
    key = sheet_type
    if sheet_type == "archived":
        key = TYPE
        async with _factory()() as s:
            await ts.archive_type(s, TYPE, actor="t")
    async with running(
        _tape_backend, {"integrations.grocy.label.battery.sheet_type": key}, seeded=seeded
    ) as rig:
        before = await _job_count()
        resp = await rig.post()
        assert resp.status_code == 503, resp.text
        assert _code(resp) == "grocy_label_sheet_type_unavailable"
        assert TYPE not in resp.text and "page-1" not in resp.text
        assert await _job_count() == before


async def test_disabled_page_printer_503_printer_unavailable(
    _tape_backend: MockPrinterBackend,
) -> None:
    seeded = await _seed_base()
    async with _factory()() as s:
        printer = await s.get(Printer, seeded[0])
        assert printer is not None
        printer.enabled = False
        await s.commit()
    async with running(_tape_backend, seeded=seeded) as rig:
        resp = await rig.post()
        assert resp.status_code == 503, resp.text
        assert _code(resp) == "grocy_label_printer_unavailable"


async def test_page_target_403_before_sheet_type_check(_tape_backend: MockPrinterBackend) -> None:
    async with running(
        _tape_backend, {"integrations.grocy.label.battery.sheet_type": "no-such-type"}
    ) as rig:
        resp = await rig.post(token=rig.restricted)
        assert resp.status_code == 403, resp.text
        assert _code(resp) == "printer_not_allowed"


async def test_unparseable_json_on_page_target_is_202_with_failed_job(
    _tape_backend: MockPrinterBackend,
) -> None:
    settings = {
        "integrations.grocy.label.printer": "page-1",
        "integrations.grocy.label.sheet_type": TYPE,
    }
    async with running(_tape_backend, settings) as rig:
        resp = await rig.post(content=b"{not json", headers={"content-type": "application/json"})
        assert resp.status_code == 202, resp.text
        job_id = resp.json()["job_id"]
        row = await _job(job_id)
        assert ("queued", "failed") in rig.job_events(job_id)
    assert row.state == "failed" and row.printer_id == rig.page_id
    assert (row.error or "").startswith("grocy_label_invalid")
    assert await _cells() == []


async def test_held_printer_fails_the_job(
    _tape_backend: MockPrinterBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with running(_tape_backend) as rig:
        monkeypatch.setattr(rig.app.state.print_queue, "is_identity_held", lambda _pid: True)
        resp = await rig.post()
        assert resp.status_code == 202, resp.text
        job_id = resp.json()["job_id"]
        row = await _ends(job_id, "failed")
        assert ("queued", "failed") in rig.job_events(job_id)
    assert (row.error or "").startswith("printer-identity-mismatch")
    assert await _cells() == []
    assert rig.print_jobs() == 0


async def test_qr_too_large_for_cell_fails_the_job(_tape_backend: MockPrinterBackend) -> None:
    seeded = await _seed_base()
    # Cells of 4 mm without a corner radius: a content box of 2 mm holds a line of text, not
    # the QR of the longest Grocycode (about 2.8 mm at 600 dpi).
    tiny = Geometry("A4", 21000, 29700, 400, 400, 10, 10, 500, 500, 2000, 2000, 0, "rectangle")
    async with _factory()() as s:
        await ts.create_type(
            s, ts.TypeFields("acme-tiny", "ATN", "Acme", ["T-0"], None, True), tiny, actor="t"
        )
    long_code = {"battery": "Smoke detector", "grocycode": "grcy:b:4" + (":" + "x" * 64) * 3}
    async with running(
        _tape_backend, {"integrations.grocy.label.battery.sheet_type": "acme-tiny"}, seeded=seeded
    ) as rig:
        resp = await rig.post(long_code)
        assert resp.status_code == 202, resp.text
        row = await _ends(resp.json()["job_id"], "failed")
    assert (row.error or "").startswith("content_type_data_mismatch")
    assert await _cells() == []
    assert rig.print_jobs() == 0


async def test_three_lines_without_due_date_prints_two_lines_on_a_sheet(
    _tape_backend: MockPrinterBackend,
) -> None:
    async with running(
        _tape_backend, {"integrations.grocy.label.battery.content_type": "qr_three_lines"}
    ) as rig:
        resp = await rig.post()
        assert resp.status_code == 202, resp.text
        row = await _ends(resp.json()["job_id"], "done")
    (item,) = row.payload["detail"]["cells"]
    assert item["content_type"] == "qr_two_lines"


async def test_tape_target_unchanged(_tape_backend: MockPrinterBackend) -> None:
    settings = {
        "integrations.grocy.label.product.printer": "tape-1",
        "integrations.grocy.label.product.sheet_type": TYPE,
        "integrations.grocy.label.sheet_type": TYPE,
    }
    async with running(_tape_backend, settings) as rig:
        resp = await rig.post(PRODUCT)
        assert resp.status_code == 202, resp.text
        row = await _ends(resp.json()["job_id"], "done")
    assert row.printer_id != rig.page_id
    assert len(rig.tape.printed_images) == 1
    assert await _cells() == []
    assert rig.print_jobs() == 0


# ---------------------------------------------------------------------------- before the hand-off


async def test_cancelled_before_hand_off_frees_the_cell(
    _tape_backend: MockPrinterBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = _Gate(monkeypatch)
    seeded = await _seed_base()
    code = await _sheet(used=5)
    async with running(_tape_backend, seeded=seeded) as rig:
        resp = await rig.post()
        assert resp.status_code == 202, resp.text
        job_id = resp.json()["job_id"]
        await gate.wait_entered()
        assert await _grocy_cells() == [(code, 6, "reserved")]
        cancel = await rig.client.post(f"/api/v1/jobs/{job_id}/cancel", headers=rig.key)
        assert 200 <= cancel.status_code < 300, cancel.text
        gate.release.set()

        async def freed() -> bool:
            return await _grocy_cells() == []

        await _until(freed, 1.0)  # at once: the sweep runs every 300 s
        await asyncio.sleep(0.2)
        row = await _job(job_id)
        events = rig.job_events(job_id)
    assert row.state == "cancelled"
    assert ("queued", "failed") not in events
    assert rig.print_jobs() == 0


async def test_restart_before_hand_off_frees_the_cell(
    _tape_backend: MockPrinterBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = _Gate(monkeypatch)
    seeded = await _seed_base()
    code = await _sheet(used=5)
    async with running(_tape_backend, seeded=seeded) as rig:
        resp = await rig.post()
        assert resp.status_code == 202, resp.text
        job_id = resp.json()["job_id"]
        await gate.wait_entered()
        assert await _grocy_cells() == [(code, 6, "reserved")]
    # The stop ended it at once; the next start has nothing to bring back.
    assert await _grocy_cells() == []
    row = await _job(job_id)
    assert (row.state, (row.error or "").split(":")[0]) == ("failed", "deferred_interrupted")
    gate.release.set()
    async with running(_tape_backend, seeded=seeded) as rig2:
        await asyncio.sleep(0.5)
        assert (await _job(job_id)).state == "failed"
    assert await _grocy_cells() == []
    assert rig.print_jobs() == 0 and rig2.print_jobs() == 0


async def test_crash_before_hand_off_frees_the_cell(_tape_backend: MockPrinterBackend) -> None:
    """No stop ran: the stored row is ``queued`` and ``deferred`` and its cell ``reserved``.
    The recovery ends it ``deferred_interrupted`` and frees the cell: never ``unconfirmed``
    (``failed_restart`` would read as "maybe printed"), never printed."""
    seeded = await _seed_base()
    code = await _sheet(used=5)
    sheet = await _sheet_row(code)
    job_id = uuid4()
    async with _factory()() as s:
        s.add(
            Job(
                id=job_id,
                printer_id=seeded[0],
                template_key=None,
                payload={
                    "deferred": True,
                    "deferred_kind": "sheet_page",
                    "label_data": {"source_app": "grocy", "qr_payload": "grcy:b:4"},
                    "content_type": "qr_two_lines",
                    "sheet_type": TYPE,
                },
            )
        )
        s.add(
            SheetCell(
                sheet_id=sheet.id,
                cell_no=6,
                state="reserved",
                job_id=job_id,
                source="grocy",
                ref="grcy:b:4",
            )
        )
        await s.commit()
    async with running(_tape_backend, seeded=seeded) as rig:

        async def ended() -> bool:
            return (await _job(job_id)).state != "queued"

        await _until(ended)  # the recovery and the start-up sweep both ran before the yield
        cells = await _grocy_cells()
        row = await _job(job_id)
        await asyncio.sleep(0.3)
    assert cells == []  # freed, not unconfirmed: the cell first, then the job
    assert row.state == "failed"
    assert (row.error or "").startswith("deferred_interrupted")
    assert rig.print_jobs() == 0


async def test_rewire_before_hand_off_frees_the_cell(
    _tape_backend: MockPrinterBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = _Gate(monkeypatch)
    seeded = await _seed_base()
    code = await _sheet(used=5)
    async with running(_tape_backend, seeded=seeded) as rig:
        resp = await rig.post()
        assert resp.status_code == 202, resp.text
        job_id = resp.json()["job_id"]
        await gate.wait_entered()
        assert await _grocy_cells() == [(code, 6, "reserved")]
        async with _factory()() as s:
            printer = await s.get(Printer, rig.page_id)
        assert printer is not None
        await rig.app.state.printer_runtime.attach(printer)  # an attached id is re-wired
        row = await _job(job_id)
        cells = await _grocy_cells()
        gate.release.set()
        await asyncio.sleep(0.3)
        later = await _job(job_id)
        events = rig.job_events(job_id)
    assert cells == []
    assert (row.state, (row.error or "").split(":")[0]) == ("failed", "deferred_interrupted")
    assert later.state == "failed"
    assert gate.passed == 0  # the task was cancelled before the re-wire's recovery ran
    assert ("queued", "failed") in events
    assert rig.print_jobs() == 0


async def test_margin_id_not_printed_twice_during_hand_off(
    _tape_backend: MockPrinterBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = _Gate(monkeypatch)
    async with running(_tape_backend) as rig:
        resp = await rig.post()
        assert resp.status_code == 202, resp.text
        job_id = resp.json()["job_id"]
        await gate.wait_entered()
        (code,) = await _sheet_codes()  # the new sheet of the Grocy label, margin placement
        body = {
            "items": [
                {
                    "content_type": "qr_two_lines",
                    "data": {"title": "UI", "primary_id": "U-1", "qr_payload": "u"},
                }
            ],
            "placements": [{"sheet": code}],
        }
        ui = await rig.client.post("/api/v1/print/page-1/sheet", json=body, headers=rig.key)
        assert ui.status_code == 202, ui.text
        (page,) = ui.json()["pages"]
        assert page["margin_id"] is False
        gate.release.set()
        grocy = await _ends(job_id, "done")
    assert grocy.payload["detail"]["margin_id"]  # the Grocy page carries it, once


async def test_cancel_racing_the_hand_off_is_not_lost(
    _tape_backend: MockPrinterBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review I-1: the cancel route sees the job untracked, then the task hands it off before
    the route's write. The cancel must still reach the queue: row ``cancelled``, cell free, no
    print. Driven by events: the task waits until the route has checked, the route's write waits
    until the hand-off is done."""
    import app.repositories.jobs as jobs_repo

    checked = asyncio.Event()
    handed = asyncio.Event()

    async def after_check(_self: GrocySheetLabels, _code: str | None) -> None:
        await checked.wait()

    original_submit = PrintQueue.submit_stored_page_job

    async def submit(queue: PrintQueue, *args: Any, **kwargs: Any) -> UUID:
        done = await original_submit(queue, *args, **kwargs)
        handed.set()
        return done

    original_cancel = jobs_repo.cancel_queued_unhanded

    async def late(session: Any, job_id: UUID) -> Any:
        checked.set()  # the route has looked at the queue: untracked
        async with asyncio.timeout(WAIT_S):
            await handed.wait()
        return await original_cancel(session, job_id)

    monkeypatch.setattr(GrocySheetLabels, "_after_choice", after_check)
    monkeypatch.setattr(PrintQueue, "submit_stored_page_job", submit)
    monkeypatch.setattr(jobs_repo, "cancel_queued_unhanded", late)
    seeded = await _seed_base()
    code = await _sheet(used=5)
    async with running(_tape_backend, seeded=seeded) as rig:
        queue = rig.app.state.print_queue
        await queue.pause_printer(rig.page_id, reason="user", source="user")
        resp = await rig.post()
        assert resp.status_code == 202, resp.text
        job_id = resp.json()["job_id"]
        cancel = await rig.client.post(f"/api/v1/jobs/{job_id}/cancel", headers=rig.key)
        assert 200 <= cancel.status_code < 300, cancel.text
        assert handed.is_set()  # the interleaving really happened

        async def freed() -> bool:
            return await _grocy_cells() == []

        await _until(freed, 1.0)
        await queue.resume_printer(rig.page_id)
        await asyncio.sleep(0.5)  # the worker would take a job that was left queued
        row = await _job(job_id)
    assert (code, row.state) == (code, "cancelled")
    assert rig.print_jobs() == 0


# ---------------------------------------------------------------------------- review fix round 1


async def test_refused_sheet_is_skipped_on_the_re_choice(_tape_backend: MockPrinterBackend) -> None:
    """Review I-2: a sheet the planner refuses (its ID goes in a cell that is still due, and only
    one cell is free) does not stop the type: the re-choice skips it, for this label and the
    next."""
    seeded = await _seed_base()
    refused = await _sheet(used=47)
    async with _factory()() as s:  # an ID placed in a cell, not printed yet (the API offers it
        sheet = await _sheet_row_in(s, refused)  # for new sheets of a print only)
        sheet.id_placement = "cell"
        await s.commit()
    async with running(_tape_backend, seeded=seeded) as rig:
        for _ in range(2):
            resp = await rig.post()
            assert resp.status_code == 202, resp.text
            await _ends(resp.json()["job_id"], "done")
        await _until(lambda: _settled(2))
    (new,) = [c for c in await _sheet_codes() if c != refused]
    assert sorted(await _grocy_cells()) == [(new, 1, "used"), (new, 2, "used")]


async def _set_page_margins(app: Any, printer_id: UUID, margins: Margins) -> None:
    """The page printer's status with these hardware margins (after the producer's first poll)."""
    from app.models.printer_status_cache import PrinterStatusCache

    from tests.integration.api.test_sheet_print_api import _record

    async with asyncio.timeout(WAIT_S):
        while True:
            async with _factory()() as s:
                row = await s.get(PrinterStatusCache, printer_id)
                summary = ((row.parsed if row else None) or {}).get("summary") or {}
                if row is not None and summary.get("margins_hmm") is not None:
                    row.parsed = _record(margins).model_dump(mode="json")
                    await s.commit()
                    return
            await asyncio.sleep(0.02)


async def test_label_avoids_the_hardware_margin(_tape_backend: MockPrinterBackend) -> None:
    """Review M-1: the webhook has no preview, so a cell that reaches into the printer's
    hardware margin is not used. A top margin of 30 mm covers the first row of the 4 x 12 type
    (it starts 21.3 mm down): the label lands in cell 5 of a new sheet, and a started sheet
    whose only free cell is in the margin counts as full."""
    seeded = await _seed_base()
    edge = await _sheet(used=0)
    async with _factory()() as s:
        sheet = await _sheet_row_in(s, edge)
        s.add_all(
            SheetCell(sheet_id=sheet.id, cell_no=n, state="used", source="api")
            for n in range(5, 49)
        )
        await s.commit()
    async with running(_tape_backend, seeded=seeded) as rig:
        await _set_page_margins(rig.app, rig.page_id, Margins(top=3000, left=0, bottom=0, right=0))
        resp = await rig.post()
        assert resp.status_code == 202, resp.text
        await _ends(resp.json()["job_id"], "done")
        await _until(lambda: _settled(1))
    (new,) = [c for c in await _sheet_codes() if c != edge]
    assert await _grocy_cells() == [(new, 5, "used")]


async def _sheet_row_in(session: Any, code: str) -> Sheet:
    return (await session.execute(select(Sheet).where(Sheet.code == code))).scalar_one()
