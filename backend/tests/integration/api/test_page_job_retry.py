"""HTTP tests of ``POST /api/v1/jobs/{id}/retry`` for a sheet page (Task 9, spec 11.4, OC-42).

The full app with its lifespan, like ``test_sheet_print_api``: the real print queue and
``SheetCellsOutcome``, the fake IPP printer, SQLite. A job is failed on purpose and the retry is
read back from the stored payload and the sheet, never from the response alone. Every wait is
bounded; the cells are polled because the runner ends a job in memory before the outcome handler
settles them (C15).
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import httpx
import pytest
from app.calibration import service as calibration_service
from app.calibration.model import CalibrationIn
from app.models.api_key import ApiKey
from app.models.job import Job
from app.models.printer import Printer
from app.models.printer_tray import PrinterTray
from app.services.page_jobs import PagePayload
from app.sheets import print_service
from sqlalchemy import func, select

from tests.integration.api.test_sheet_print_api import (
    DE_MARK,
    EN_MARK,
    TIMEOUT_S,
    Rig,
    _body,
    _cells,
    _err,
    _item,
    _sheet,
    _used,
    running,
)
from tests.integration.api.test_sheet_types_api import _factory

pytestmark = pytest.mark.asyncio

REJECTED = 0x040A  # client-error-document-format-not-supported: refused before any byte printed
ABORTED_AFTER_START = [3, 5, 8]  # the printer started the job, then aborted it


async def _job(job_id: str | UUID) -> Job:
    async with _factory()() as s:
        row = await s.get(Job, UUID(str(job_id)))
    assert row is not None
    return row


async def _until_job(job_id: str, state: str) -> Job:
    async with asyncio.timeout(TIMEOUT_S):
        while True:
            row = await _job(job_id)
            if row.state == state:
                return row
            await asyncio.sleep(0.02)


async def _key_id(rig: Rig) -> UUID:
    """The id of the rig's print key: rows stored by hand belong to it (#294)."""
    prefix = rig.key["X-Label-Hub-Key"][:16]
    async with _factory()() as s:
        key = (await s.execute(select(ApiKey).where(ApiKey.key_prefix == prefix))).scalar_one()
    return key.id


async def _job_count() -> int:
    async with _factory()() as s:
        return int((await s.execute(select(func.count()).select_from(Job))).scalar_one())


async def _fail_cleanly(rig: Rig, body: dict[str, Any]) -> tuple[str, str]:
    """Print so that the printer refuses the document: the job ends ``failed``, cells free."""
    rig.fake.print_status = REJECTED
    resp = await rig.print(body)
    assert resp.status_code == 202, resp.text
    (page,) = resp.json()["pages"]
    await _until_job(page["job_id"], "failed")
    code = page["sheet_code"]
    await rig.until_sheet(code, lambda s: s["reserved"] == 0 and s["unconfirmed"] == 0)
    rig.fake.print_status = 0
    return page["job_id"], code


async def _retry(rig: Rig, job_id: str, **kw: Any) -> httpx.Response:
    return await rig.client.post(f"/api/v1/jobs/{job_id}/retry", headers=kw.pop("headers", rig.key))


async def _retried_detail(rig: Rig, resp: httpx.Response) -> dict[str, Any]:
    assert resp.status_code == 201, resp.text
    detail: dict[str, Any] = (await rig.job_payload(resp.json()["id"]))["detail"]
    return detail


def _cell_numbers(detail: dict[str, Any]) -> list[int]:
    return [c["cell"] for c in detail["cells"]]


# ---------------------------------------------------------------------------- the happy path


async def test_retry_reserves_the_same_cells_and_prints_without_a_restart() -> None:
    async with running() as rig:
        code = await _sheet(used=4)
        body = _body(code, 3)
        body["items"][0].update(source="grocy", ref="42", purpose="Flour")
        first_id, _ = await _fail_cleanly(rig, body)
        first = (await rig.job_payload(first_id))["detail"]
        prints_before = sum(1 for r in rig.fake.received if r.operation == "Print-Job")

        resp = await _retry(rig, first_id)

        assert resp.status_code == 201, resp.text
        assert resp.json()["id"] != first_id
        detail = await _retried_detail(rig, resp)
        assert _cell_numbers(detail) == _cell_numbers(first) == [5, 6, 7]
        assert [c["label_data"] for c in detail["cells"]] == [
            c["label_data"] for c in first["cells"]
        ]
        sheet = await rig.until_sheet(code, _used(5, 6, 7))
        by_cell = {c["cell"]: c for c in sheet["cells"]}
        assert (by_cell[5]["source"], by_cell[5]["ref"], by_cell[5]["purpose"]) == (
            "grocy",
            "42",
            "Flour",
        )  # the record of the first attempt, not a default
        assert by_cell[6]["purpose"] == "Item 1"
        prints = [r for r in rig.fake.received if r.operation == "Print-Job"]
        assert len(prints) == prints_before + 1  # the fake received the new PDF
        assert prints[-1].document.startswith(b"%PDF")
        old = await _job(first_id)
        assert old.state == "failed"  # the first job stays as history


async def test_retry_keeps_the_callers_cell_order() -> None:
    async with running() as rig:
        code = await _sheet()
        body = _body(code, 3, placements=[{"sheet": code, "cells": [9, 2, 5]}])
        first_id, _ = await _fail_cleanly(rig, body)

        resp = await _retry(rig, first_id)

        detail = await _retried_detail(rig, resp)
        assert [(c["cell"], c["label_data"]["primary_id"]) for c in detail["cells"]] == [
            (9, "R-0"),
            (2, "R-1"),
            (5, "R-2"),
        ]
        await rig.until_sheet(code, _used(2, 5, 9))


async def test_retry_keeps_the_id_cell_where_it_was() -> None:
    async with running() as rig:
        body = {
            "items": [_item(i) for i in range(2)],
            "placements": [{"new_sheet": {"type": "acme-t1", "id_placement": "cell"}}],
        }
        first_id, code = await _fail_cleanly(rig, body)
        first = (await rig.job_payload(first_id))["detail"]
        assert first["id_cell"]["cell"] == 1 and _cell_numbers(first) == [2, 3]

        resp = await _retry(rig, first_id)

        detail = await _retried_detail(rig, resp)
        assert detail["id_cell"]["cell"] == 1 and _cell_numbers(detail) == [2, 3]
        assert detail["id_cell"]["label_data"] == first["id_cell"]["label_data"]
        sheet = await rig.until_sheet(code, lambda s: s["id_printed"] and _used(1, 2, 3)(s))
        assert next(c for c in sheet["cells"] if c["cell"] == 1)["source"] == "hub"


# ---------------------------------------------------------------------------- decided again


async def test_retry_mark_in_current_language(monkeypatch: pytest.MonkeyPatch) -> None:
    async with running() as rig:
        store = rig.app.state.settings_store
        original = store.get
        language = {"value": "en"}
        monkeypatch.setattr(
            store,
            "get",
            lambda key: language["value"] if key == "general.language" else original(key),
        )
        code = await _sheet()
        first_id, _ = await _fail_cleanly(rig, _body(code, 1))
        first = (await rig.job_payload(first_id))["detail"]
        assert first["feed_mark"]["text"] == EN_MARK
        language["value"] = "de"  # changed between the first attempt and the retry

        resp = await _retry(rig, first_id)

        detail = await _retried_detail(rig, resp)
        assert detail["feed_mark"]["text"] == DE_MARK  # read at retry time, not copied (I1)
        await rig.until_sheet(code, lambda s: s["feed_mark_printed"])


async def test_retry_redraws_margin_id() -> None:
    async with running() as rig:
        code = await _sheet(placement="margin")
        first_id, _ = await _fail_cleanly(rig, _body(code, 2))
        first = (await rig.job_payload(first_id))["detail"]
        assert first["margin_id"] is not None and first["feed_mark"] is not None

        resp = await _retry(rig, first_id)

        detail = await _retried_detail(rig, resp)
        # margin_id_in_flight is read before the retry inserts its own rows (C26); read after,
        # the rows without a job row would suppress the ID for good and this stays None.
        assert detail["margin_id"] is not None
        assert detail["margin_id"]["band"] == first["margin_id"]["band"]
        assert detail["feed_mark"] is not None  # the mark likewise
        sheet = await rig.until_sheet(code, lambda s: s["id_printed"] and s["feed_mark_printed"])
        assert sheet["used"] == 2


async def test_retry_does_not_draw_the_margin_id_twice() -> None:
    """Another job on the sheet now carries the ID: the retry leaves it out."""
    async with running() as rig:
        code = await _sheet(placement="margin")
        first_id, _ = await _fail_cleanly(rig, _body(code, 1))
        rig.fake.job_script = [3]  # the next job waits at the printer, still queued/printing
        other = await rig.print(_body(code, 1, placements=[{"sheet": code, "cells": [20]}]))
        assert other.status_code == 202, other.text
        assert other.json()["pages"][0]["margin_id"] is True

        resp = await _retry(rig, first_id)

        detail = await _retried_detail(rig, resp)
        assert detail["margin_id"] is None and detail["feed_mark"] is None


async def test_retry_takes_a_fresh_calibration_snapshot() -> None:
    async with running() as rig:
        code = await _sheet()
        first_id, _ = await _fail_cleanly(rig, _body(code, 1))
        first = await _job(first_id)
        assert first.payload["calibration"]["method"] == "none"
        async with _factory()() as s:
            await calibration_service.put(
                s,
                rig.printer_id,
                "auto",
                CalibrationIn(offset_x_mm=0.5, offset_y_mm=-0.3),
                measured_on=None,
                actor="t",
            )

        resp = await _retry(rig, first_id)

        assert resp.status_code == 201, resp.text
        snap = (await _job(resp.json()["id"])).payload["calibration"]
        assert snap["method"] == "manual"
        assert (snap["dx_hmm"], snap["dy_hmm"]) == (50, -30)


# ---------------------------------------------------------------------------- refusals


async def test_retry_cells_taken_names_the_cells_and_writes_nothing() -> None:
    async with running() as rig:
        code = await _sheet()
        first_id, _ = await _fail_cleanly(rig, _body(code, 3))
        marked = await rig.client.post(
            f"/api/v1/sheets/{code}/cells/mark",
            json={"cells": [{"cell": 2}, {"cell": 3}]},
            headers=rig.key,
        )
        assert marked.status_code == 200, marked.text
        jobs = await _job_count()

        resp = await _retry(rig, first_id)

        assert resp.status_code == 409, resp.text
        err = _err(resp)
        assert err["error_code"] == "cells_taken" and err["error_detail"] == {"cells": [2, 3]}
        assert [(c.cell_no, c.state) for c in await _cells()] == [(2, "used"), (3, "used")]
        assert await _job_count() == jobs  # no row was created


async def test_retry_refused_while_cells_are_unconfirmed() -> None:
    async with running(script=ABORTED_AFTER_START) as rig:
        code = await _sheet()
        resp = await rig.print(_body(code, 2))
        assert resp.status_code == 202, resp.text
        job_id = resp.json()["pages"][0]["job_id"]
        failed = await _until_job(job_id, "failed")
        assert failed.error is not None and failed.error.startswith("interrupted")
        await rig.until_sheet(code, lambda s: s["unconfirmed"] == 2)
        jobs = await _job_count()

        refused = await _retry(rig, job_id)

        assert refused.status_code == 409, refused.text
        err = _err(refused)
        assert err["error_code"] == "cells_unconfirmed"
        assert err["error_detail"] == {"cells": [1, 2]}
        assert await _job_count() == jobs
        resolved = await rig.client.post(
            f"/api/v1/sheets/{code}/cells/resolve",
            json={"cells": [1, 2], "outcome": "not_printed"},
            headers=rig.key,
        )
        assert resolved.status_code == 200, resolved.text
        rig.fake.job_script = [3, 5, 9]

        again = await _retry(rig, job_id)

        assert again.status_code == 201, again.text  # after resolving them, OC-42
        await rig.until_sheet(code, _used(1, 2))


async def test_retry_of_a_done_job_is_not_retryable() -> None:
    async with running() as rig:
        code = await _sheet()
        resp = await rig.print(_body(code, 1))
        job_id = resp.json()["pages"][0]["job_id"]
        await rig.until_sheet(code, _used(1))
        await _until_job(job_id, "done")
        jobs = await _job_count()

        refused = await _retry(rig, job_id)

        assert refused.status_code == 409, refused.text
        assert _err(refused)["error_code"] == "job_not_retryable"
        assert await _job_count() == jobs


async def test_retry_of_a_cancelled_job_works() -> None:
    async with running(script=[3]) as rig:
        code = await _sheet()
        resp = await rig.print(_body(code, 2))
        job_id = resp.json()["pages"][0]["job_id"]
        queue = rig.app.state.print_queue
        async with asyncio.timeout(TIMEOUT_S):
            while not queue._page_runner.is_tracking(UUID(job_id)):
                await asyncio.sleep(0.02)
        assert await queue.cancel(job_id)
        await _until_job(job_id, "cancelled")
        await rig.until_sheet(code, lambda s: s["reserved"] == 0 and s["unconfirmed"] == 0)
        rig.fake.job_script = [3, 5, 9]

        retried = await _retry(rig, job_id)

        assert retried.status_code == 201, retried.text
        await rig.until_sheet(code, _used(1, 2))


async def test_retry_on_a_disabled_printer_is_refused_and_reserves_nothing() -> None:
    async with running() as rig:
        code = await _sheet()
        first_id, _ = await _fail_cleanly(rig, _body(code, 2))
        async with _factory()() as s:
            printer = await s.get(Printer, rig.printer_id)
            assert printer is not None
            printer.enabled = False
            await s.commit()
        jobs = await _job_count()

        refused = await _retry(rig, first_id)

        assert refused.status_code == 409, refused.text
        assert _err(refused)["error_code"] == "printer_disabled"
        assert await _cells() == [] and await _job_count() == jobs


async def test_retry_with_a_removed_tray_is_tray_unknown() -> None:
    async with running() as rig:
        code = await _sheet()
        first_id, _ = await _fail_cleanly(rig, _body(code, 2))
        async with _factory()() as s:
            tray = await s.get(PrinterTray, (rig.printer_id, "auto"))
            assert tray is not None
            tray.enabled = False  # a removed tray has no row; both end the same way
            await s.commit()
        jobs = await _job_count()

        refused = await _retry(rig, first_id)

        assert refused.status_code == 422, refused.text
        err = _err(refused)
        assert err["error_code"] == "tray_unknown" and err["error_detail"] == {"trays": []}
        assert await _cells() == [] and await _job_count() == jobs


async def test_retry_of_a_discarded_sheet_is_refused() -> None:
    async with running() as rig:
        code = await _sheet()
        first_id, _ = await _fail_cleanly(rig, _body(code, 2))
        gone = await rig.client.post(f"/api/v1/sheets/{code}/discard", headers=rig.key)
        assert gone.status_code == 200, gone.text

        refused = await _retry(rig, first_id)

        assert refused.status_code == 409, refused.text
        assert _err(refused)["error_code"] == "sheet_discarded"
        assert await _cells() == []


async def test_a_queue_that_refuses_the_retry_frees_the_cells(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with running() as rig:
        code = await _sheet()
        first_id, _ = await _fail_cleanly(rig, _body(code, 2))

        async def unknown(*_a: Any, **_k: Any) -> UUID:
            raise KeyError("printer")

        monkeypatch.setattr(rig.app.state.print_queue, "submit_page_job", unknown)
        jobs = await _job_count()

        refused = await _retry(rig, first_id)

        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"]["type"] == "printer-unavailable"  # ProblemDetail, as before
        assert await _cells() == []  # the reservation was released
        assert await _job_count() == jobs


async def test_retry_needs_the_print_scope_and_the_printer() -> None:
    async with running() as rig:
        code = await _sheet()
        first_id, _ = await _fail_cleanly(rig, _body(code, 1))

        read_only = await _retry(rig, first_id, headers=rig.reader)

        assert read_only.status_code in (401, 403), read_only.text
        assert await _cells() == []


async def test_retry_of_a_sheet_page_without_a_usable_payload_is_422() -> None:
    async with running() as rig:
        async with _factory()() as s:
            row = Job(
                printer_id=rig.printer_id,
                payload={"kind": "sheet_page", "detail": {}},
                state="failed",
                api_key_id=await _key_id(rig),
            )
            s.add(row)
            await s.commit()
            job_id = row.id
        jobs = await _job_count()

        refused = await _retry(rig, str(job_id))

        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"]["type"] == "job-not-retryable"
        assert await _job_count() == jobs


async def test_retry_meta_falls_back_for_a_payload_stored_before_the_record_was_kept() -> None:
    from app.sheets.sheet_page import SheetCellPayload

    old = SheetCellPayload(
        cell=3,
        content_type="qr_two_lines",  # type: ignore[arg-type]
        label_data={"source_app": "grocy", "title": "Flour", "primary_id": "P-1"},
        mapped=False,
    )

    meta = print_service._retry_meta(old)

    assert (meta.source, meta.purpose, meta.ref) == ("grocy", "Flour", None)


# ------------------------------------------------------------------ ID printed since (T9-1)


async def _id_cell_sheet_failed(rig: Rig) -> tuple[str, str]:
    """A ``cell`` sheet whose ID-only job failed cleanly: the ID is not printed, cell 1 is free."""
    rig.fake.print_status = REJECTED
    resp = await rig.client.post(
        "/api/v1/sheets",
        json={"type": "acme-t1", "id_placement": "cell", "printer": "page-1"},
        headers=rig.key,
    )
    assert resp.status_code == 201, resp.text
    job_id, code = resp.json()["job_id"], resp.json()["code"]
    await _until_job(job_id, "failed")
    await rig.until_sheet(code, lambda s: s["reserved"] == 0 and s["unconfirmed"] == 0)
    rig.fake.print_status = 0
    return job_id, code


async def test_retry_of_an_id_only_job_whose_id_was_printed_elsewhere_is_refused() -> None:
    async with running() as rig:
        job_id, code = await _id_cell_sheet_failed(rig)
        again = await rig.print(
            _body(code, 1, placements=[{"sheet": code, "skip": [1]}])
        )  # the ID goes to cell 2, the item to cell 3
        assert again.status_code == 202, again.text
        assert again.json()["pages"][0]["id_cell"] == 2
        await rig.until_sheet(code, lambda s: s["id_printed"] and _used(2, 3)(s))
        jobs = await _job_count()

        refused = await _retry(rig, job_id)

        assert refused.status_code == 409, refused.text
        assert _err(refused)["error_code"] == "job_not_retryable"  # no second ID label
        assert await _job_count() == jobs
        sheet = await rig.sheet(code)
        assert [c["cell"] for c in sheet["cells"]] == [2, 3]  # cell 1 stays free


async def test_retry_drops_the_id_cell_when_the_id_was_printed_elsewhere() -> None:
    async with running() as rig:
        body = {
            "items": [_item(i) for i in range(2)],
            "placements": [{"new_sheet": {"type": "acme-t1", "id_placement": "cell"}}],
        }
        first_id, code = await _fail_cleanly(rig, body)  # ID cell 1, items 2 and 3
        other = await rig.print(_body(code, 1, placements=[{"sheet": code, "skip": [1, 2, 3]}]))
        assert other.status_code == 202, other.text
        assert other.json()["pages"][0]["id_cell"] == 4
        await rig.until_sheet(code, lambda s: s["id_printed"] and _used(4, 5)(s))

        resp = await _retry(rig, first_id)

        detail = await _retried_detail(rig, resp)
        assert detail["id_cell"] is None and _cell_numbers(detail) == [2, 3]
        sheet = await rig.until_sheet(code, _used(2, 3, 4, 5))
        assert 1 not in {c["cell"] for c in sheet["cells"]}


async def test_retry_of_a_calibration_page_on_a_disabled_printer_is_refused() -> None:
    async with running() as rig:
        stored = PagePayload(
            kind="calibration_page",
            media="A4",
            tray="auto",
            render_dpi=600,
            job_name="Calibration page",
            calibration=None,
            detail={},
        ).model_dump(mode="json")
        async with _factory()() as s:
            row = Job(
                printer_id=rig.printer_id,
                payload=stored,
                state="failed",
                api_key_id=await _key_id(rig),
            )
            s.add(row)
            printer = await s.get(Printer, rig.printer_id)
            assert printer is not None
            printer.enabled = False
            await s.commit()
            job_id = row.id
        jobs = await _job_count()

        refused = await _retry(rig, str(job_id))

        assert refused.status_code == 409, refused.text
        assert _err(refused)["error_code"] == "printer_disabled"
        assert await _job_count() == jobs


async def test_retry_meta_cuts_a_long_default_purpose() -> None:
    from app.sheets.sheet_page import SheetCellPayload

    old = SheetCellPayload(
        cell=3,
        content_type="qr_two_lines",  # type: ignore[arg-type]
        label_data={"source_app": "manual", "title": "T" * 200, "primary_id": "P-1"},
        mapped=False,
    )

    meta = print_service._retry_meta(old)

    assert meta.purpose == "T" * 120  # OC-43: cut, never refused


async def test_a_cell_payload_with_unknown_keys_still_loads() -> None:
    from app.sheets.sheet_page import SheetCellPayload

    cell = SheetCellPayload.model_validate(
        {
            "cell": 1,
            "content_type": "qr_two_lines",
            "label_data": {},
            "mapped": False,
            "from_a_later_version": 1,
        }
    )

    assert cell.cell == 1  # a rollback must not strand a stored job


async def _until_pool_idle(timeout_s: float = 2.0) -> bool:
    """Whether the engine's pool is seen with no connection checked out within ``timeout_s``."""
    import app.db.engine as engine_module

    pool = engine_module.engine.pool
    async with asyncio.timeout(timeout_s + 1):
        for _ in range(int(timeout_s / 0.02)):
            if pool.checkedout() == 0:  # type: ignore[attr-defined]
                return True
            await asyncio.sleep(0.02)
    return False


async def test_a_retry_holds_no_connection_while_the_service_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex P2 (same class as R10-1): the route kept the connection that loaded the job and the
    printer while ``retry_sheet_page`` opened its own sessions, so enough concurrent retries
    used up the pool before the nested sessions could get one."""
    from app.sheets import print_service
    from app.sheets.errors import PrinterUnavailableError

    started = 0

    async def slow(*args: Any, **kwargs: Any) -> Any:
        nonlocal started
        started += 1
        await asyncio.sleep(2.5)
        raise PrinterUnavailableError()

    async with running() as rig:
        code = await _sheet(used=4)
        first_id, _ = await _fail_cleanly(rig, _body(code, 3))
        monkeypatch.setattr(print_service, "retry_sheet_page", slow)

        tasks = [asyncio.create_task(_retry(rig, first_id)) for _ in range(8)]
        async with asyncio.timeout(10):
            while started < 8:
                await asyncio.sleep(0.02)
        idle = await _until_pool_idle()
        await asyncio.gather(*tasks)

    assert idle


async def test_no_connection_is_held_while_the_retry_is_submitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #210: the retry kept its service session while the new page job was submitted."""
    from tests.integration.api.test_sheet_print_api import _SubmitProbe

    n = 6
    async with running() as rig:
        failed = []
        for _ in range(n):
            code = await _sheet()
            first_id, _ = await _fail_cleanly(rig, _body(code, 1))
            failed.append(first_id)
        probe = _SubmitProbe(n)
        monkeypatch.setattr(rig.app.state.print_queue, "submit_page_job", probe)
        tasks = [asyncio.create_task(_retry(rig, job_id)) for job_id in failed]
        async with asyncio.timeout(15):
            await probe.everyone_in.wait()
            other = await rig.client.get("/api/v1/sheets", headers=rig.reader)
        responses = await asyncio.gather(*tasks)

    assert probe.checked_out == 0
    assert other.status_code == 200, other.text
    assert {r.status_code for r in responses} == {409}
