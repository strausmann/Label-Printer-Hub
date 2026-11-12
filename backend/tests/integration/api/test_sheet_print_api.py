"""HTTP tests of POST /api/v1/print/{printer}/sheet: the print through the real queue (Task 7).

The full app with its lifespan: the real print queue and ``SheetCellsOutcome``, the fake IPP
printer behind the page printer, SQLite. The runner ends a job in memory before the outcome
handler settles the cells (C15), so no test waits on the job state alone: each polls the sheet,
bounded.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import app.models  # noqa: F401
import httpx
import pytest
from app.api.routes.sheet_print import get_lookup_service
from app.calibration import service as calibration_service
from app.calibration.model import CalibrationIn
from app.models.job import Job
from app.models.print_batch import PrintBatch
from app.models.printer import Printer
from app.models.printer_status_cache import PrinterStatusCache
from app.models.printer_tray import PrinterTray
from app.models.sheet import Sheet, SheetCell
from app.printer_backends.ipp.attributes import IppStatusRecord, Margins
from app.schemas.label_data import LabelData
from app.services.lookup_service import LookupFailedError
from app.services.producers.ipp_status_producer import _empty_summary
from app.sheets import sheet_service as ss
from app.sheets import type_service as ts
from app.sheets.geometry import Geometry
from app.sheets.sheet_service import MarkedCell
from httpx import ASGITransport
from sqlalchemy import func, select

from tests.helpers.fake_ipp_printer import FAKE_URI, FakeIppPrinter
from tests.integration.api.test_sheet_types_api import _factory, _insert_key

pytestmark = pytest.mark.asyncio

G48 = Geometry("A4", 21000, 29700, 4570, 2120, 4, 12, 4820, 2120, 2130, 985, None, "rectangle")
G_SMALL = Geometry("A4", 21000, 29700, 2540, 1000, 7, 27, 2790, 1000, 1350, 860, 150, "rectangle")
TIMEOUT_S = 15.0
DE_MARK = "▲ Oben \u2013 diese Kante zuerst"
EN_MARK = "▲ Top \u2013 this edge first"


def _record(margins: Margins | None = None) -> IppStatusRecord:
    summary = _empty_summary().model_copy(
        update={
            "resolutions_dpi": [600],
            "margins_hmm": margins,
            "pdf_supported": True,
            "state": "idle",
        }
    )
    return IppStatusRecord(
        online=True,
        printer_state="idle",
        reasons=[],
        blocking_reason=None,
        warnings=[],
        markers=[],
        trays=[],
        jobs_ahead=0,
        summary=summary,
    )


@dataclass
class Rig:
    client: httpx.AsyncClient
    app: Any
    fake: FakeIppPrinter
    printer: str  # slug
    printer_id: UUID
    key: dict[str, str]
    reader: dict[str, str]
    sent: list[dict[str, Any]] = field(default_factory=list)

    def url(self, printer: str | None = None) -> str:
        return f"/api/v1/print/{printer or self.printer}/sheet"

    async def print(self, body: dict[str, Any], **kw: Any) -> httpx.Response:
        return await self.client.post(
            self.url(kw.pop("printer", None)), json=body, headers=kw.pop("headers", self.key)
        )

    async def sheet(self, code: str) -> dict[str, Any]:
        resp = await self.client.get(f"/api/v1/sheets/{code}", headers=self.reader)
        assert resp.status_code == 200, resp.text
        out: dict[str, Any] = resp.json()
        return out

    async def until_sheet(
        self, code: str, predicate: Callable[[dict[str, Any]], bool]
    ) -> dict[str, Any]:
        """Poll the sheet, bounded (C15: the job state alone proves nothing about the cells)."""
        async with asyncio.timeout(TIMEOUT_S):
            while True:
                sheet = await self.sheet(code)
                if predicate(sheet):
                    return sheet
                await asyncio.sleep(0.02)

    async def job_payload(self, job_id: str) -> dict[str, Any]:
        async with _factory()() as s:
            row = await s.get(Job, UUID(job_id))
        assert row is not None
        return dict(row.payload)


async def _type(key: str = "acme-t1", prefix: str = "AT1", g: Geometry = G48) -> None:
    async with _factory()() as s:
        await ts.create_type(
            s, ts.TypeFields(key, prefix, "Acme", ["T-1"], None, None), g, actor="t"
        )


async def _printer(slug: str, *, enabled: bool = True, backend: str = "ipp") -> UUID:
    async with _factory()() as s:
        p = Printer(
            id=uuid4(),
            name=f"P {slug}",
            slug=slug,
            model="m",
            backend=backend,
            connection={"uri": FAKE_URI, "tls_verify": True},
            enabled=enabled,
        )
        s.add(p)
        s.add(PrinterTray(printer_id=p.id, tray_key="auto", label="Auto", is_default=True))
        s.add(PrinterTray(printer_id=p.id, tray_key="off", label="Off", enabled=False))
        s.add(
            PrinterStatusCache(
                printer_id=p.id,
                parsed=_record().model_dump(mode="json"),  # margins: the producer fills them
                captured_at=datetime.now(UTC),
            )
        )
        await s.commit()
        return p.id


async def _sheet(used: int = 0, placement: str = "manual", key: str = "acme-t1") -> str:
    async with _factory()() as s:
        sheet = await ss.create_sheet(
            s,
            type_key=key,
            version=None,
            id_placement=placement,  # type: ignore[arg-type]
            used_cells=[MarkedCell(n) for n in range(1, used + 1)],
            note=None,
            actor="t",
        )
        return sheet.code


def _item(i: int, **kw: Any) -> dict[str, Any]:
    return {
        "content_type": "qr_two_lines",
        "data": {
            "title": f"Item {i}",
            "primary_id": f"R-{i}",
            "qr_payload": f"https://r.example.invalid/{i}",
        },
        **kw,
    }


def _body(code: str, n: int = 3, **kw: Any) -> dict[str, Any]:
    return {"items": [_item(i) for i in range(n)], "placements": [{"sheet": code}], **kw}


def _err(resp: httpx.Response) -> dict[str, Any]:
    detail = resp.json()["detail"]
    assert set(detail) == {"error_code", "error_message", "error_detail"}, detail
    out: dict[str, Any] = detail
    return out


async def _cells(code: str | None = None) -> list[SheetCell]:
    async with _factory()() as s:
        rows = list((await s.execute(select(SheetCell))).scalars().all())
    return rows


async def _count(model: Any) -> int:
    async with _factory()() as s:
        return int((await s.execute(select(func.count()).select_from(model))).scalar_one())


@asynccontextmanager
async def running(
    script: list[int] | None = None,
    *,
    margins: Margins | None = None,
    printer_enabled: bool = True,
    seeds: Callable[[], Awaitable[None]] | None = None,
) -> AsyncIterator[Rig]:
    """The app with its lifespan, one IPP page printer in front of the fake, two keys."""
    from app.main import create_app

    fake = FakeIppPrinter(job_script=script or [3, 5, 9])
    await _type()
    printer_id = await _printer("page-1", enabled=printer_enabled)
    if seeds is not None:
        await seeds()
    key = {"X-Label-Hub-Key": await _insert_key(["print"])}
    reader = {"X-Label-Hub-Key": await _insert_key(["read"])}
    app = create_app()._app
    app.state.ipp_transport_factory = lambda _uri: ASGITransport(app=fake)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c,
    ):
        rig = Rig(c, app, fake, "page-1", printer_id, key, reader)
        if margins is not None:
            await _set_margins(rig, margins)
        yield rig


async def _set_margins(rig: Rig, margins: Margins) -> None:
    """Replace the status the producer wrote at start with one that has asymmetric margins.

    The seeded status has no margins; the producer's first answer has the fake's. The test waits
    for that answer, then writes its own: the producer polls every 30 s, so the test's status
    outlives the test."""
    async with asyncio.timeout(TIMEOUT_S):
        while True:
            async with _factory()() as s:
                row = await s.get(PrinterStatusCache, rig.printer_id)
                polled = (
                    row is not None
                    and ((row.parsed or {}).get("summary") or {}).get("margins_hmm") is not None
                    and row.captured_at is not None
                )
                if polled and row is not None:
                    parsed = _record(margins).model_dump(mode="json")
                    row.parsed = parsed
                    row.captured_at = datetime.now(UTC)
                    await s.commit()
                    return
            await asyncio.sleep(0.02)


def _used(*cells: int) -> Callable[[dict[str, Any]], bool]:
    def check(sheet: dict[str, Any]) -> bool:
        states = {c["cell"]: c["state"] for c in sheet["cells"]}
        return all(states.get(n) == "used" for n in cells)

    return check


# ---------------------------------------------------------------------------- end to end


async def test_print_end_to_end_cells_used() -> None:
    async with running() as rig:
        code = await _sheet(used=17)
        resp = await rig.print(_body(code, 9))

        assert resp.status_code == 202, resp.text
        body = resp.json()
        (page,) = body["pages"]
        assert page["sheet_code"] == code and page["cells"] == list(range(18, 27))
        assert UUID(body["batch_id"]) and UUID(page["job_id"])
        sheet = await rig.until_sheet(code, _used(*range(18, 27)))  # acceptance 1
        assert sheet["used"] == 26 and sheet["reserved"] == 0
        assert {c["purpose"] for c in sheet["cells"] if c["cell"] > 17} == {
            f"Item {i}" for i in range(9)
        }
        (printed,) = [r for r in rig.fake.received if r.operation == "Print-Job"]
        assert printed.document.startswith(b"%PDF")
        assert printed.job_attributes["media-col"] is not None
        flat = repr(printed.job_attributes) + repr(printed.attributes)
        assert "labels" in flat and "none" in flat  # media-type=labels, print-scaling=none
        # the wire name is the readable name plus the hub's token (C14)
        wire = printed.attributes["job-name"][0]
        assert isinstance(wire, str)
        assert re.fullmatch(rf"Sheet {code} · 9 labels \[[0-9a-f]{{12}}\]", wire), wire
        async with _factory()() as s:
            batch = (await s.execute(select(PrintBatch))).scalar_one()
        assert str(batch.id) == body["batch_id"] and batch.job_ids == [page["job_id"]]


async def test_print_takes_one_sheet_and_reports_the_rest() -> None:
    # #277: one sheet per run: 31 of 60 items fit, the other 29 stay with the caller.
    async with running() as rig:
        code = await _sheet(used=17)  # 31 free
        body = {"items": [_item(i) for i in range(60)], "placements": [{"sheet": code}]}
        resp = await rig.print(body)

        assert resp.status_code == 202, resp.text
        (page,) = resp.json()["pages"]
        assert len(page["cells"]) == 31
        assert (resp.json()["placed"], resp.json()["remaining"]) == (31, 29)
        await rig.until_sheet(code, _used(*range(18, 49)))
        async with _factory()() as s:
            batch = (await s.execute(select(PrintBatch))).scalar_one()
        assert batch.job_ids == [page["job_id"]]

        two = {**body, "placements": [{"sheet": code}, {"new_sheet": {"type": "acme-t1"}}]}
        refused = await rig.print(two)
        assert refused.status_code == 422, refused.text
        assert _err(refused)["error_code"] == "preview_too_large"


async def test_print_after_type_edit_uses_v1() -> None:
    async with running() as rig:
        code = await _sheet()
        v2 = Geometry(**{**G48.__dict__, "pitch_x": 5000, "cols": 3})
        async with _factory()() as s:
            await ts.add_version(s, "acme-t1", v2, actor="t", change_note="v2")

        resp = await rig.print(_body(code, 5))

        assert resp.status_code == 202, resp.text
        payload = await rig.job_payload(resp.json()["pages"][0]["job_id"])
        assert payload["detail"]["geometry"]["pitch_x"] == 4820  # acceptance 9: v1
        assert payload["detail"]["geometry"]["cols"] == 4
        sheet = await rig.until_sheet(code, _used(1, 2, 3, 4, 5))
        assert sheet["version"] == 1


async def test_expected_cells_mismatch() -> None:
    async with running() as rig:
        code = await _sheet(used=17)
        preview = await rig.client.post(
            f"/api/v1/print/{rig.printer}/sheet/preview", json=_body(code, 3), headers=rig.reader
        )
        expected = preview.json()["expected_cells"]
        async with _factory()() as s:  # someone marks cell 18 by hand in between
            await ss.mark_cells(s, code, [MarkedCell(18)], actor="other")

        resp = await rig.print({**_body(code, 3), "expected_cells": expected})

        assert resp.status_code == 409, resp.text  # acceptance 13
        detail = _err(resp)
        assert detail["error_code"] == "plan_changed"
        assert detail["error_detail"]["plan"] == [
            {"sheet": code, "cells": [19, 20, 21], "id_cell": None}
        ]
        assert [c for c in await _cells() if c.job_id is not None] == []  # nothing reserved
        assert rig.fake.received == [] or all(r.operation != "Print-Job" for r in rig.fake.received)


async def test_insufficient_over_http() -> None:
    async with running() as rig:
        code = await _sheet(used=48)  # #277: a sheet with room places what fits; a full one not

        resp = await rig.print(_body(code, 20))

        assert resp.status_code == 409, resp.text  # acceptance 3
        detail = _err(resp)
        assert detail["error_code"] == "insufficient_cells"
        assert detail["error_detail"]["free_cells"] == [0]  # free cells per page
        assert detail["error_detail"]["shortfall"] == 20


async def test_qr_mapped_on_small_type_printed_as_text() -> None:
    async with running() as rig:
        await _type("acme-small", "SM1", G_SMALL)
        code = await _sheet(key="acme-small")
        items = [_item(0), _item(1, content_type="qr_only")]

        resp = await rig.print({"items": items, "placements": [{"sheet": code}]})

        assert resp.status_code == 202, resp.text  # acceptance 21 (print side)
        payload = await rig.job_payload(resp.json()["pages"][0]["job_id"])
        cells = payload["detail"]["cells"]
        assert [c["content_type"] for c in cells] == ["text_two_lines", "text_one_line"]
        assert all(c["mapped"] for c in cells) and payload["detail"]["allow_qr"] is False


async def test_print_margin_id_in_stored_band() -> None:
    margins = Margins(top=600, left=500, bottom=423, right=500)

    async def calibrate() -> None:
        async with _factory()() as s:
            await calibration_service.put(
                s,
                (await s.execute(select(Printer.id).where(Printer.slug == "page-1"))).scalar_one(),
                "auto",
                CalibrationIn(offset_x_mm=0, offset_y_mm=-0.8),
                measured_on=None,
                actor="t",
            )

    async with running(margins=margins, seeds=calibrate) as rig:
        code = await _sheet(placement="margin")

        resp = await rig.print(_body(code, 3))

        assert resp.status_code == 202, resp.text
        (page,) = resp.json()["pages"]
        assert page["margin_id"] is True and page["margin_band"] == "bottom"
        detail = (await rig.job_payload(page["job_id"]))["detail"]
        assert detail["margin_id"]["band"] == "bottom"
        assert detail["margin_id"]["usable_hmm"] == 1527
        sheet = await rig.until_sheet(code, lambda s: s["id_printed"] and s["used"] == 3)
        assert sheet["id_printed"] is True


async def test_print_feed_mark_follows_hub_language(monkeypatch: pytest.MonkeyPatch) -> None:
    async with running() as rig:
        store = rig.app.state.settings_store
        original = store.get
        language = {"value": "de"}
        monkeypatch.setattr(
            store,
            "get",
            lambda key: language["value"] if key == "general.language" else original(key),
        )
        texts: list[str] = []
        for value in ("de", "en"):
            language["value"] = value
            code = await _sheet()
            resp = await rig.print(_body(code, 1))
            assert resp.status_code == 202, resp.text
            payload = await rig.job_payload(resp.json()["pages"][0]["job_id"])
            texts.append(payload["detail"]["feed_mark"]["text"])
            await rig.until_sheet(code, _used(1))
        assert texts == [DE_MARK, EN_MARK]


async def test_print_carries_feed_mark_once() -> None:
    async with running() as rig:
        code = await _sheet()

        first = await rig.print(_body(code, 2))
        assert first.status_code == 202, first.text
        page_1 = first.json()["pages"][0]
        sheet = await rig.until_sheet(code, lambda s: s["feed_mark_printed"] and s["used"] == 2)
        second = await rig.print(_body(code, 2))

        assert second.status_code == 202, second.text
        page_2 = second.json()["pages"][0]
        assert page_1["feed_mark"] is True and page_2["feed_mark"] is False
        assert (await rig.job_payload(page_1["job_id"]))["detail"]["feed_mark"] is not None
        assert (await rig.job_payload(page_2["job_id"]))["detail"]["feed_mark"] is None
        assert sheet["feed_mark_printed"] is True
        await rig.until_sheet(code, _used(1, 2, 3, 4))


async def test_print_without_room_prints_without_id() -> None:
    margins = Margins(top=2000, left=2000, bottom=2000, right=2000)
    async with running(margins=margins) as rig:
        code = await _sheet(placement="margin")

        resp = await rig.print(_body(code, 3))

        assert resp.status_code == 202, resp.text  # acceptance 7
        (page,) = resp.json()["pages"]
        assert page["id_not_printed"] is True and page["margin_id"] is False
        assert page["margin_band"] is None and page["id_cell"] is None
        detail = (await rig.job_payload(page["job_id"]))["detail"]
        assert detail["margin_id"] is None and detail["id_cell"] is None
        sheet = await rig.until_sheet(code, _used(1, 2, 3))
        assert sheet["id_printed"] is False and sheet["used"] == 3


async def test_other_client_reads_same_sheet() -> None:
    async with running() as rig:
        code = await _sheet(used=17)
        other = {"X-Label-Hub-Key": await _insert_key(["read"])}
        items = [_item(i, purpose=f"Jam {i}") for i in range(3)]

        resp = await rig.print({"items": items, "placements": [{"sheet": code}]})

        assert resp.status_code == 202, resp.text
        seen = await rig.client.get(f"/api/v1/sheets/{code}", headers=other)  # key B, acceptance 11
        cells = {c["cell"]: c for c in seen.json()["cells"] if c["cell"] > 17}
        assert sorted(cells) == [18, 19, 20]
        assert [cells[n]["purpose"] for n in (18, 19, 20)] == ["Jam 0", "Jam 1", "Jam 2"]
        await rig.until_sheet(code, _used(18, 19, 20))


# ---------------------------------------------------------------------------- refusals


async def test_nothing_reserved_on_late_failure() -> None:
    class Failing:
        async def lookup(self, source_app: str, identifier: str) -> LabelData:
            if identifier == "36":
                raise LookupFailedError("upstream")
            return LabelData(
                source_app=source_app, title="t", primary_id="p", qr_payload="https://x.invalid/1"
            )

    async with running() as rig:
        rig.app.dependency_overrides[get_lookup_service] = lambda: Failing()
        await _printer("tape-1", backend="brother_ql")
        code = await _sheet()
        sheets = await _count(Sheet)
        lookups = [
            {"content_type": "qr_two_lines", "lookup": {"app": "grocy", "identifier": str(i)}}
            for i in range(40)
        ]

        late = await rig.print({"items": lookups, "placements": [{"sheet": code}]})
        assert late.status_code == 502, late.text
        assert _err(late)["error_detail"] == {"item_index": 36}

        tape = await rig.print(_body(code), printer="tape-1")
        assert tape.status_code == 409 and _err(tape)["error_code"] == "media_kind_mismatch"

        off = await rig.print(_body(code, tray="off"))
        assert off.status_code == 422 and _err(off)["error_code"] == "tray_unknown"

        broken = _body(code, 10, placements=[{"new_sheet": {"type": "acme-t1"}}])
        del broken["items"][5]["data"]["title"]
        mismatch = await rig.print(broken)
        assert mismatch.status_code == 422, mismatch.text
        assert _err(mismatch)["error_code"] == "content_type_data_mismatch"
        assert _err(mismatch)["error_detail"]["item_index"] == 5

        assert (await _cells()) == []
        assert await _count(Sheet) == sheets
        assert await _count(PrintBatch) == 0
        assert all(r.operation != "Print-Job" for r in rig.fake.received)


async def test_purpose_sanitised() -> None:
    async with running() as rig:
        code = await _sheet()
        item = _item(0, purpose="Jam\x07 ‮jar")

        ok = await rig.print({"items": [item], "placements": [{"sheet": code}]})

        assert ok.status_code == 202, ok.text
        sheet = await rig.until_sheet(code, _used(1))
        assert sheet["cells"][0]["purpose"] == "Jam jar"
        long = await rig.print(
            {"items": [_item(1, purpose="x" * 130)], "placements": [{"sheet": code}]}
        )
        assert long.status_code == 422
        detail = _err(long)
        assert detail["error_code"] == "invalid_request"
        assert "x" * 20 not in long.text  # the input is not echoed
        assert len(sheet["cells"]) == 1


async def test_validation_errors_name_paths_and_never_echo() -> None:
    async with running() as rig:
        code = await _sheet()
        secret = "ZQX-private-label-text"
        body = {
            "items": [_item(i, purpose=secret) for i in range(501)],
            "placements": [{"sheet": code}],
        }

        resp = await rig.print(body)

        assert resp.status_code == 422
        assert _err(resp)["error_code"] == "invalid_request"
        assert secret not in resp.text
        assert _err(resp)["error_detail"] == {"errors": ["items"]}
        extra = await rig.print({**_body(code), "options": {"copies": 2}})  # OC-3: no copies
        assert extra.status_code == 422 and "copies" not in extra.text


async def test_scopes_and_printer_restriction() -> None:
    async with running() as rig:
        code = await _sheet()
        reader = await rig.print(_body(code), headers=rig.reader)
        assert reader.status_code == 403

        other = await _printer("page-2")
        restricted = {"X-Label-Hub-Key": await _insert_key(["print"], [str(other)])}
        denied = await rig.print(_body(code), headers=restricted)
        assert denied.status_code == 403
        anonymous = await rig.client.post(rig.url(), json=_body(code))
        assert anonymous.status_code in (401, 403)

        assert await _cells() == []


async def test_a_disabled_printer_is_refused_and_reserves_nothing() -> None:
    async with running(printer_enabled=False) as rig:
        code = await _sheet()

        resp = await rig.print(_body(code))

        assert resp.status_code == 409, resp.text
        assert _err(resp)["error_code"] == "printer_disabled"
        assert await _cells() == []


async def test_unknown_printer_is_404() -> None:
    async with running() as rig:
        code = await _sheet()
        resp = await rig.print(_body(code), printer="no-such-printer")
        assert resp.status_code == 404 and _err(resp)["error_code"] == "printer_not_found"


async def test_a_printer_the_queue_does_not_know_answers_409_and_releases() -> None:
    async with running() as rig:
        await _printer("page-late")  # added after the start: the queue does not know it
        code = await _sheet(used=17)

        resp = await rig.print(_body(code, 5), printer="page-late")

        assert resp.status_code == 409, resp.text  # C24
        assert _err(resp)["error_code"] == "printer-unavailable"
        assert len(await _cells()) == 17  # only the hand-marked cells
        assert await _count(PrintBatch) == 0


async def test_preview_then_print_store_the_same_margin_and_mark() -> None:
    margins = Margins(top=600, left=500, bottom=423, right=500)
    async with running(margins=margins) as rig:
        code = await _sheet(placement="margin")
        body = _body(code, 3)
        preview = await rig.client.post(
            f"/api/v1/print/{rig.printer}/sheet/preview", json=body, headers=rig.reader
        )
        assert preview.status_code == 200, preview.text
        (shown,) = preview.json()["pages"]

        resp = await rig.print({**body, "expected_cells": preview.json()["expected_cells"]})

        assert resp.status_code == 202, resp.text
        (page,) = resp.json()["pages"]
        detail = (await rig.job_payload(page["job_id"]))["detail"]
        assert page["margin_band"] == shown["margin_band"] == detail["margin_id"]["band"]
        assert page["margin_id"] is shown["margin_id"] and page["feed_mark"] is shown["feed_mark"]
        assert (detail["feed_mark"] is not None) is shown["feed_mark"]
        await rig.until_sheet(code, _used(1, 2, 3))


async def test_openapi_documents_the_print_route() -> None:
    async with running() as rig:
        schema = (await rig.client.get("/openapi.json")).json()
        op = schema["paths"]["/api/v1/print/{printer_key}/sheet"]["post"]
        assert "202" in op["responses"]
        assert {"403", "404", "409", "422", "502", "503"} <= set(op["responses"])
        assert "SheetPrintResponse" in schema["components"]["schemas"]


@pytest.mark.parametrize("suffix", ["", "/preview"])
async def test_every_documented_error_of_the_sheet_print_routes_has_the_envelope_body(
    suffix: str,
) -> None:
    async with running() as rig:
        schema = (await rig.client.get("/openapi.json")).json()
        op = schema["paths"][f"/api/v1/print/{{printer_key}}/sheet{suffix}"]["post"]
        errors = {code: r for code, r in op["responses"].items() if code[0] in "45"}
        assert {"403", "404", "409", "422", "502", "503"} <= set(errors)
        for code, response in errors.items():
            ref = response["content"]["application/json"]["schema"]["$ref"]
            assert ref.endswith("/SheetApiErrorResponse"), code


async def test_a_print_onto_a_label_too_small_for_a_line_is_422_and_reserves_nothing() -> None:
    """Codex P2 / review item P1-1: a 3 mm label (unknown radius, content box -0.2 mm)."""
    g = Geometry("A4", 21000, 29700, 300, 300, 4, 8, 350, 350, 1500, 900, None, "rectangle")
    async with running() as rig:
        await _type("acme-tiny", "TNY", g)
        code = await _sheet(key="acme-tiny")

        resp = await rig.print(_body(code, 2))

        assert resp.status_code == 422, resp.text
        detail = _err(resp)
        assert detail["error_code"] == "content_type_data_mismatch"
        assert detail["error_detail"] == {"item_index": 0, "missing_fields": ["label_size"]}
        assert "r.example.invalid" not in resp.text  # no echo of the item
        assert await _cells() == []
        assert not [r for r in rig.fake.received if r.operation == "Print-Job"]


class _SubmitProbe:
    """A stand-in for ``submit_page_job`` that waits until ``n`` callers are inside it, then
    reads how many pooled connections are checked out, and refuses the job (issue #210)."""

    def __init__(self, n: int) -> None:
        self.n = n
        self.inside = 0
        self.checked_out: int | None = None
        # What the pool already hands out when the probe is made, before any of the requests: the
        # test asserts the requests add nothing to it, not that the whole pool is idle (266-15).
        import app.db.engine as engine_module

        self.baseline: int = engine_module.engine.pool.checkedout()  # type: ignore[attr-defined]
        self.everyone_in = asyncio.Event()

    async def __call__(self, *_a: Any, **_k: Any) -> UUID:
        import app.db.engine as engine_module

        self.inside += 1
        if self.inside >= self.n:
            await asyncio.sleep(0.1)  # let the others' sessions settle
            self.checked_out = engine_module.engine.pool.checkedout()  # type: ignore[attr-defined]
            self.everyone_in.set()
        async with asyncio.timeout(10):
            await self.everyone_in.wait()
        raise KeyError("printer")  # -> PrinterUnavailableError, the reservation is freed


async def test_no_connection_is_held_while_page_jobs_are_submitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #210 (the class of R10-1): ``_queue_pages`` kept the service session, and with it a
    pooled connection, while ``submit_page_job`` opened its own. While eight concurrent prints
    are all inside the submit, nothing is checked out, and another request still gets through."""
    n = 8
    async with running() as rig:
        codes = [await _sheet() for _ in range(n)]
        probe = _SubmitProbe(n)
        monkeypatch.setattr(rig.app.state.print_queue, "submit_page_job", probe)
        tasks = [asyncio.create_task(rig.print(_body(code, 1))) for code in codes]
        async with asyncio.timeout(15):
            await probe.everyone_in.wait()
            other = await rig.client.get(f"/api/v1/sheets/{codes[0]}", headers=rig.reader)
        responses = await asyncio.gather(*tasks)

    assert probe.checked_out is not None
    assert probe.checked_out <= probe.baseline
    assert other.status_code == 200, other.text
    assert {r.status_code for r in responses} == {409}
    assert await _cells() == []


async def test_the_key_reads_its_own_sheet_batch_and_another_key_gets_404() -> None:
    """#294 fix round 2: a sheet batch stores its owner as ``key:<uuid>`` (the write actor);
    the key that printed it reads it, another print key gets the missing-batch 404."""
    async with running() as rig:
        code = await _sheet(used=0)
        resp = await rig.print(_body(code, 2))
        assert resp.status_code == 202, resp.text
        url = f"/api/v1/batches/{resp.json()['batch_id']}"
        mine = await rig.client.get(url, headers=rig.key)
        assert mine.status_code == 200, mine.text
        other = {"X-Label-Hub-Key": await _insert_key(["print"])}
        foreign = await rig.client.get(url, headers=other)
        assert (foreign.status_code, foreign.content) == (404, b'{"detail":"Batch not found"}')
