"""HTTP tests of the sheet ID on creation (``id_placement="cell"``) and the margin check (Task 8).

The full app with its lifespan, like ``test_sheet_print_api``: the real print queue and
``SheetCellsOutcome``, the fake IPP printer behind the page printer, SQLite. The ID cell's
content is asserted on the stored ``jobs.payload.detail.id_cell`` (pre-flight C27): a 1-bit
image cannot be told from text in the PDF.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import httpx
import pytest
from app.config import get_settings
from app.models.print_batch import PrintBatch
from app.models.sheet import Sheet
from app.printer_backends.ipp.attributes import Margins
from app.sheets import planner
from app.sheets import print_service as print_service_module
from app.sheets.geometry import Geometry
from app.sheets.print_service import scan_payload_builder

from tests.integration.api.test_sheet_print_api import (
    DE_MARK,
    EN_MARK,
    Rig,
    _body,
    _cells,
    _count,
    _err,
    _printer,
    _set_margins,
    _sheet,
    _type,
    _used,
    running,
)
from tests.integration.api.test_sheet_types_api import _insert_key

pytestmark = pytest.mark.asyncio

# One column, one row: the mark's room is exactly the label width.
G_MARK_32 = Geometry(
    "A4", 21000, 29700, 3200, 2000, 1, 1, 3200, 2000, 1500, 2000, None, "rectangle"
)
G_MARK_30 = Geometry(
    "A4", 21000, 29700, 3000, 2000, 1, 1, 3000, 2000, 1500, 2000, None, "rectangle"
)


QR_KEY = "avery-zweckform-l4736rev"  # seeded: 4 x 12 cells, QR allowed
TEXT_KEY = "avery-zweckform-l4731rev"  # seeded: 7 x 27 cells, text only


def _scan(code: str) -> str:
    return scan_payload_builder(str(get_settings().public_url))(code)


def _create_body(type_key: str, **kw: Any) -> dict[str, Any]:
    return {"type": type_key, "id_placement": "cell", "printer": "page-1", **kw}


async def _create(rig: Rig, body: dict[str, Any], **kw: Any) -> httpx.Response:
    return await rig.client.post("/api/sheets", json=body, headers=kw.pop("headers", rig.key))


async def _margin_check(rig: Rig, type_key: str, **kw: Any) -> httpx.Response:
    params = {"type": type_key, "printer": kw.pop("printer", "page-1"), **kw}
    return await rig.client.get("/api/sheets/margin-check", params=params, headers=rig.reader)


async def _cancel_pending(rig: Rig, job_id: str) -> None:
    """Cancel a job that waits at the printer: it ended cleanly, nothing was printed."""
    queue = rig.app.state.print_queue
    async with asyncio.timeout(15):
        while not queue._page_runner.is_tracking(UUID(job_id)):
            await asyncio.sleep(0.02)
    assert await queue.cancel(job_id)


# ---------------------------------------------------------------------------- cell option


async def test_create_cell_queues_id_label() -> None:
    async with running() as rig:
        resp = await _create(
            rig, _create_body(QR_KEY, used_cells=[{"cell": n} for n in range(1, 6)])
        )

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["code"] == "L4736-0001" and body["id_placement"] == "cell"
        assert body["job_id"] is not None
        reserved = [c for c in body["cells"] if c["state"] == "reserved"]
        assert [(c["cell"], c["source"]) for c in reserved] == [(6, "hub")]
        sheet = await rig.until_sheet("L4736-0001", lambda s: s["id_printed"] and _used(6)(s))
        assert sheet["used"] == 6 and sheet["reserved"] == 0  # acceptance 6
        detail = (await rig.job_payload(body["job_id"]))["detail"]
        assert detail["cells"] == [] and detail["margin_id"] is None
        assert detail["id_cell"]["cell"] == 6
        assert detail["id_cell"]["content_type"] == "qr_two_lines"
        assert detail["id_cell"]["label_data"]["qr_payload"] == _scan("L4736-0001")
        (printed,) = [r for r in rig.fake.received if r.operation == "Print-Job"]
        assert printed.document.startswith(b"%PDF")

        text_only = await _create(rig, _create_body(TEXT_KEY))

        assert text_only.status_code == 201, text_only.text
        id_cell = (await rig.job_payload(text_only.json()["job_id"]))["detail"]["id_cell"]
        assert id_cell["content_type"] == "text_two_lines" and id_cell["mapped"] is True
        assert id_cell["cell"] == 1


async def test_id_only_job_carries_feed_mark(monkeypatch: pytest.MonkeyPatch) -> None:
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
            resp = await _create(rig, _create_body(QR_KEY))
            assert resp.status_code == 201, resp.text
            detail = (await rig.job_payload(resp.json()["job_id"]))["detail"]
            texts.append(detail["feed_mark"]["text"])
            await rig.until_sheet(resp.json()["code"], lambda s: s["feed_mark_printed"])
        assert texts == [DE_MARK, EN_MARK]  # OC-58


async def test_margin_check_measures_the_mark_in_the_current_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with running() as rig:
        await _type("mark-32", "M32", G_MARK_32)
        await _type("mark-30", "M30", G_MARK_30)
        store = rig.app.state.settings_store
        original = store.get
        language = {"value": "de"}
        monkeypatch.setattr(
            store,
            "get",
            lambda key: language["value"] if key == "general.language" else original(key),
        )
        seen: dict[tuple[str, str], bool] = {}
        for value in ("de", "en"):
            language["value"] = value
            for key in ("mark-32", "mark-30"):
                resp = await _margin_check(rig, key)
                assert resp.status_code == 200, resp.text
                seen[(key, value)] = resp.json()["feed_mark"]
        assert seen == {
            ("mark-32", "de"): True,
            ("mark-32", "en"): True,
            ("mark-30", "de"): False,  # the German text is 30.06 mm at 6 pt
            ("mark-30", "en"): True,
        }


async def test_id_job_clean_failure_then_next_job_carries_id() -> None:
    async with running(script=[3]) as rig:  # the job stays pending at the printer
        resp = await _create(
            rig, _create_body(QR_KEY, used_cells=[{"cell": n} for n in range(1, 6)])
        )
        assert resp.status_code == 201, resp.text
        code, job_id = resp.json()["code"], resp.json()["job_id"]

        await _cancel_pending(rig, job_id)

        sheet = await rig.until_sheet(code, lambda s: s["reserved"] == 0)
        assert sheet["id_printed"] is False and sheet["used"] == 5  # cell 6 is free again
        again = await rig.print(_body(code, 2))  # OC-40: the next job reserves an ID cell
        assert again.status_code == 202, again.text
        (page,) = again.json()["pages"]
        assert page["id_cell"] == 6 and page["cells"] == [7, 8]


async def test_margin_only_first_completed_job() -> None:
    async with running() as rig:
        code = await _sheet(placement="margin", key=QR_KEY)

        first = await rig.print(_body(code, 2))

        assert first.status_code == 202, first.text
        await rig.until_sheet(code, lambda s: s["id_printed"] and _used(1, 2)(s))
        second = await rig.print(_body(code, 2))
        assert second.status_code == 202, second.text
        assert (await rig.job_payload(first.json()["pages"][0]["job_id"]))["detail"]["margin_id"]
        second_detail = (await rig.job_payload(second.json()["pages"][0]["job_id"]))["detail"]
        assert second_detail["margin_id"] is None  # acceptance 7: only the first completed job


async def test_margin_id_is_drawn_again_when_the_first_job_failed_cleanly() -> None:
    async with running(script=[3]) as rig:
        fresh = await _sheet(placement="margin", key=QR_KEY)
        failing = await rig.print(_body(fresh, 2))
        assert failing.status_code == 202, failing.text
        job_id = failing.json()["pages"][0]["job_id"]
        await _cancel_pending(rig, job_id)
        await rig.until_sheet(fresh, lambda s: s["reserved"] == 0)

        next_job = await rig.print(_body(fresh, 2))

        assert next_job.status_code == 202, next_job.text
        detail = (await rig.job_payload(next_job.json()["pages"][0]["job_id"]))["detail"]
        assert detail["margin_id"] is not None  # drawn again: the first one never printed


async def test_create_without_placement_is_margin_and_queues_nothing() -> None:
    async with running() as rig:
        resp = await rig.client.post(
            "/api/sheets", json={"type": QR_KEY, "printer": "page-1"}, headers=rig.key
        )

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["id_placement"] == "margin" and body["job_id"] is None
        assert body["cells"] == [] and await _cells() == []
        assert await _count(PrintBatch) == 0
        assert all(r.operation != "Print-Job" for r in rig.fake.received)
        unknown = await rig.client.post(
            "/api/sheets", json={"type": QR_KEY, "id_placement": "manual"}, headers=rig.key
        )
        assert unknown.status_code == 201 and unknown.json()["job_id"] is None


# ---------------------------------------------------------------------------- refusals


async def test_cell_needs_a_printer_the_caller_may_use_and_leaves_nothing_behind() -> None:
    async with running() as rig:
        sheets = await _count(Sheet)

        no_printer = await _create(rig, {"type": QR_KEY, "id_placement": "cell"})
        assert no_printer.status_code == 422, no_printer.text
        assert _err(no_printer)["error_code"] == "invalid_request"
        assert _err(no_printer)["error_detail"] == {"errors": ["printer"]}

        unknown = await _create(rig, _create_body(QR_KEY, printer="no-such-printer"))
        assert unknown.status_code == 404 and _err(unknown)["error_code"] == "printer_not_found"

        other = await _printer("page-2")
        restricted = {"X-Label-Hub-Key": await _insert_key(["print"], [str(other)])}
        denied = await _create(rig, _create_body(QR_KEY), headers=restricted)
        assert denied.status_code == 403

        reader = await _create(rig, _create_body(QR_KEY), headers=rig.reader)
        assert reader.status_code == 403

        off = await _create(rig, _create_body(QR_KEY, tray="off"))
        assert off.status_code == 422 and _err(off)["error_code"] == "tray_unknown"

        assert await _count(Sheet) == sheets and await _cells() == []
        assert await _count(PrintBatch) == 0


async def test_a_tape_printer_is_a_media_kind_mismatch_on_both_routes() -> None:
    """P8-4: the ID-only job and the margin check refuse a printer that is not a page printer
    (409), and the refusal leaves no sheet and no cell behind."""
    async with running() as rig:
        await _printer("tape-1", backend="brother_ql")

        created = await _create(rig, _create_body(QR_KEY, printer="tape-1"))
        checked = await _margin_check(rig, QR_KEY, printer="tape-1")

        assert created.status_code == 409, created.text
        assert _err(created)["error_code"] == "media_kind_mismatch"
        assert checked.status_code == 409, checked.text
        assert _err(checked)["error_code"] == "media_kind_mismatch"
        assert await _count(Sheet) == 0 and await _cells() == []
        assert await _count(PrintBatch) == 0


async def test_cell_on_a_disabled_printer_is_refused() -> None:
    async with running(printer_enabled=False) as rig:
        resp = await _create(rig, _create_body(QR_KEY))

        assert resp.status_code == 409, resp.text
        assert _err(resp)["error_code"] == "printer_disabled"
        assert await _count(Sheet) == 0 and await _cells() == []


async def test_cell_with_no_free_cell_creates_no_sheet() -> None:
    async with running() as rig:
        full = [{"cell": n} for n in range(1, 49)]

        resp = await _create(rig, _create_body(QR_KEY, used_cells=full))

        assert resp.status_code == 409, resp.text
        assert _err(resp)["error_code"] == "insufficient_cells"
        assert await _count(Sheet) == 0 and await _cells() == []  # the counter step rolled back
        retry = await _create(rig, _create_body(QR_KEY))
        assert retry.status_code == 201 and retry.json()["code"] == "L4736-0001"


async def test_cell_submit_failure_keeps_the_sheet_without_a_reservation() -> None:
    async with running() as rig:
        await _printer("page-late")  # added after the start: the queue does not know it

        resp = await _create(
            rig,
            _create_body(QR_KEY, printer="page-late", used_cells=[{"cell": 1}, {"cell": 2}]),
        )

        assert resp.status_code == 409, resp.text
        detail = _err(resp)
        assert detail["error_code"] == "printer-unavailable"
        code = detail["error_detail"]["sheet_code"]  # the client can still reach the sheet
        sheet = await rig.sheet(code)
        assert sheet["id_placement"] == "cell" and sheet["id_printed"] is False
        assert sheet["reserved"] == 0 and sheet["used"] == 2
        assert await _count(PrintBatch) == 0
        # OC-40: the ID goes onto the next job's first free cell
        nxt = await rig.print(_body(code, 2))
        assert nxt.status_code == 202, nxt.text
        assert nxt.json()["pages"][0]["id_cell"] == 3


async def test_cell_validation_errors_never_echo_the_input() -> None:
    async with running() as rig:
        secret = "ZQX-private-purpose"

        resp = await _create(
            rig, _create_body(QR_KEY, used_cells=[{"cell": 1, "purpose": secret * 10}])
        )

        assert resp.status_code == 422
        assert _err(resp)["error_code"] == "invalid_request"
        assert secret not in resp.text
        extra = await _create(rig, _create_body(QR_KEY, nope=1))
        assert extra.status_code == 422 and "nope" not in extra.text


# ---------------------------------------------------------------------------- margin check


async def test_margin_check_uses_probable_code_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[str | None] = []
    original = planner.choose_margin_placement

    def spy(*args: Any, **kwargs: Any) -> Any:
        recorded.append(kwargs.get("payload"))
        return original(*args, **kwargs)

    monkeypatch.setattr(planner, "choose_margin_placement", spy)
    monkeypatch.setattr(print_service_module, "choose_margin_placement", spy)
    async with running() as rig:
        first = await _margin_check(rig, QR_KEY)
        assert first.status_code == 200, first.text
        assert recorded == [_scan("L4736-0001")]

        await _sheet(key=QR_KEY)
        recorded.clear()
        second = await _margin_check(rig, QR_KEY)

        assert second.status_code == 200, second.text
        assert recorded == [_scan("L4736-0002")]
        assert None not in recorded


async def test_margin_never_refused() -> None:
    async with running(margins=Margins(top=1000, left=1000, bottom=1000, right=1000)) as rig:
        created = await rig.client.post(
            "/api/sheets",
            json={"type": TEXT_KEY, "id_placement": "margin", "printer": "page-1"},
            headers=rig.key,
        )
        assert created.status_code == 201, created.text  # never refused

        check = await _margin_check(rig, TEXT_KEY)

        assert check.status_code == 200, check.text
        body = check.json()
        assert body["printable"] is False and body["band"] is None and body["reason"]
        assert body["corner"] is None and body["usable_mm"] is None and body["qr"] is False
        assert body["bands_mm"] == {"top": 2.5, "bottom": 2.5, "right": -2.4, "left": -2.4}


async def test_margin_check_without_reported_margins_assumes_five_millimetres() -> None:
    async with running() as rig:
        await _set_margins(rig, None)  # type: ignore[arg-type]  # the printer reports none
        check = await _margin_check(rig, TEXT_KEY)

        body = check.json()
        assert body["band"] == "top" and body["usable_mm"] == 7.5
        assert body["qr"] is False and body["printable"] is True and body["reason"] is None
        assert body["corner"] == "top_left" and body["feed_mark"] is True


async def test_margin_check_scopes_and_unknowns() -> None:
    async with running() as rig:
        other = await _printer("page-2")
        restricted = {"X-Label-Hub-Key": await _insert_key(["read"], [str(other)])}
        url = "/api/sheets/margin-check"

        denied = await rig.client.get(
            url, params={"type": QR_KEY, "printer": "page-1"}, headers=restricted
        )
        assert denied.status_code == 403
        no_type = await _margin_check(rig, "no-such-type")
        assert no_type.status_code == 404 and _err(no_type)["error_code"] == "sheet_type_not_found"
        no_printer = await _margin_check(rig, QR_KEY, printer="nope")
        assert no_printer.status_code == 404
        anonymous = await rig.client.get(url, params={"type": QR_KEY, "printer": "page-1"})
        assert anonymous.status_code in (401, 403)
        off = await _margin_check(rig, QR_KEY, tray="off")
        assert off.status_code == 422 and _err(off)["error_code"] == "tray_unknown"
        missing = await rig.client.get(url, params={"type": QR_KEY}, headers=rig.reader)
        assert missing.status_code == 422 and _err(missing)["error_code"] == "invalid_request"


async def test_margin_check_disabled_printer_is_refused() -> None:
    async with running(printer_enabled=False) as rig:
        resp = await _margin_check(rig, QR_KEY)

        assert resp.status_code == 409 and _err(resp)["error_code"] == "printer_disabled"


async def test_openapi_documents_margin_check_and_the_created_sheet() -> None:
    async with running() as rig:
        schema = (await rig.client.get("/openapi.json")).json()
        paths = schema["paths"]
        assert "/api/sheets/margin-check" in paths
        created = paths["/api/sheets"]["post"]["responses"]["201"]
        ref = created["content"]["application/json"]["schema"]["$ref"]
        assert ref.endswith("/SheetCreated")
        assert "job_id" in schema["components"]["schemas"]["SheetCreated"]["properties"]
        assert "job_id" not in schema["components"]["schemas"]["SheetRead"]["properties"]
        params = {p["name"] for p in paths["/api/sheets/margin-check"]["get"]["parameters"]}
        assert params == {"type", "printer", "tray"}


async def test_scan_payload_short_form_without_public_url() -> None:
    assert scan_payload_builder("")("L4736-0001") == "sheet:L4736-0001"
    assert scan_payload_builder("   ")("L4736-0001") == "sheet:L4736-0001"
    assert (
        scan_payload_builder("https://hub.example.invalid/")("L4736-0001")
        == "https://hub.example.invalid/sheet/L4736-0001"
    )


async def test_cell_unexpected_error_after_the_commit_keeps_the_sheet_and_names_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with running() as rig:

        async def boom(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("ZQX-internal-detail")

        monkeypatch.setattr(rig.app.state.print_queue, "submit_page_job", boom)

        resp = await _create(rig, _create_body(QR_KEY, used_cells=[{"cell": 1}]))

        assert resp.status_code == 500, resp.text
        detail = _err(resp)
        assert detail["error_code"] == "sheet_id_job_failed"
        assert "ZQX-internal-detail" not in resp.text  # the cause is logged, not returned
        sheet = await rig.sheet(detail["error_detail"]["sheet_code"])
        assert sheet["reserved"] == 0 and sheet["used"] == 1 and sheet["id_printed"] is False


async def test_margin_check_counts_the_space_the_feed_mark_takes() -> None:
    # A narrow 1 x 12 type whose side bands are dead: the top band would win with a QR, but the
    # feed mark shortens it, so the bottom band wins. The check must say what the job does.
    narrow = Geometry(
        "A4", 21000, 29700, 5000, 2000, 1, 12, 5000, 2000, 3000, 8000, None, "rectangle"
    )
    margins = Margins(top=500, left=7900, bottom=500, right=7900)
    async with running(margins=margins) as rig:
        await _type("narrow-1", "NR1", narrow)
        check = await _margin_check(rig, "narrow-1")
        assert check.status_code == 200, check.text

        code = await _sheet(placement="margin", key="narrow-1")
        resp = await rig.print(_body(code, 1))

        assert resp.status_code == 202, resp.text
        stored = (await rig.job_payload(resp.json()["pages"][0]["job_id"]))["detail"]
        assert stored["margin_id"]["band"] == "bottom"
        assert check.json()["band"] == stored["margin_id"]["band"]
        assert check.json()["feed_mark"] is True


async def test_creating_a_cell_sheet_holds_no_connection_while_the_service_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex P2 (same class as R10-1): the route kept the connection that resolved the printer
    while ``create_sheet_with_id_label`` opened its own sessions."""
    import app.db.engine as engine_module
    from app.sheets.errors import PrinterUnavailableError

    started = 0

    async def slow(*args: Any, **kwargs: Any) -> Any:
        nonlocal started
        started += 1
        await asyncio.sleep(2.5)
        raise PrinterUnavailableError()

    async with running() as rig:
        monkeypatch.setattr(print_service_module, "create_sheet_with_id_label", slow)
        tasks = [asyncio.create_task(_create(rig, _create_body(QR_KEY))) for _ in range(8)]
        async with asyncio.timeout(10):
            while started < 8:
                await asyncio.sleep(0.02)
        pool = engine_module.engine.pool
        idle = False
        for _ in range(100):
            if pool.checkedout() == 0:  # type: ignore[attr-defined]
                idle = True
                break
            await asyncio.sleep(0.02)
        await asyncio.gather(*tasks)

    assert idle
