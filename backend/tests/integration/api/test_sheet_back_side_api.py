# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""HTTP tests of the sheet code on the back of the liner and the reserved cell (#350).

The full app with its lifespan, like ``test_sheet_id_label``: the real print queue and the fake
IPP printer behind the page printer ``page-1``, the seeded sheet types (3490 resolves to the
back side, 6121 to the margin).
"""

from __future__ import annotations

from datetime import UTC
from typing import Any

import httpx
import pytest
from app.models.job import Job
from app.models.sheet import Sheet, SheetIdCounter
from app.sheets import sheet_service as ss
from app.sheets import type_service as ts
from sqlalchemy import select
from sqlmodel import col

from tests.integration.api.test_page_job_retry import REJECTED, _until_job
from tests.integration.api.test_sheet_print_api import (
    Rig,
    _count,
    _err,
    _factory,
    _printer,
    running,
)
from tests.integration.api.test_sheet_types_api import _insert_key

pytestmark = pytest.mark.asyncio

KEY_3490 = "avery-zweckform-3490"  # seeded: 3 x 8, no usable margin, ultragrip on the back
KEY_6121 = "avery-zweckform-6121"


def _hold(rig: Rig, held: bool = True) -> None:
    rig.app.state.print_queue.set_identity_hold(rig.printer_id, held)


async def _create(rig: Rig, body: dict[str, Any], **kw: Any) -> httpx.Response:
    return await rig.client.post("/api/v1/sheets", json=body, headers=kw.pop("headers", rig.key))


def _back_body(**kw: Any) -> dict[str, Any]:
    return {"type": KEY_3490, "id_placement": "back_side", "printer": "page-1", **kw}


async def _back(rig: Rig, code: str, **kw: Any) -> httpx.Response:
    body = {"printer": kw.pop("printer", "page-1"), **kw}
    return await rig.client.post(f"/api/v1/sheets/{code}/back-side", json=body, headers=rig.key)


async def _confirm(rig: Rig, code: str) -> httpx.Response:
    return await rig.client.post(f"/api/v1/sheets/{code}/back-side/confirm", headers=rig.key)


async def _sheet_row(code: str) -> Sheet:
    async with _factory()() as s:
        return (await s.execute(select(Sheet).where(col(Sheet.code) == code))).scalar_one()


async def _counter(prefix: str) -> int | None:
    async with _factory()() as s:
        row = await s.get(SheetIdCounter, prefix)
        return None if row is None else row.next_value


async def _new_sheet(placement: str, key: str = KEY_3490) -> str:
    async with _factory()() as s:
        sheet = await ss.create_sheet(
            s,
            type_key=key,
            version=None,
            id_placement=placement,  # type: ignore[arg-type]
            used_cells=[],
            note=None,
            actor="t",
        )
        return sheet.code


# ---------------------------------------------------------------------------- create


async def test_create_back_side_sheet_queues_back_job() -> None:
    async with running() as rig:
        resp = await _create(rig, _back_body())

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["id_placement"] == "back_side" and body["id_printed"] is False
        assert body["job_id"] is not None and body["cells"] == []
        payload = await rig.job_payload(body["job_id"])
        assert payload["kind"] == "sheet_back_page" and payload["calibration"] is None
        detail = payload["detail"]
        assert detail["sheet_code"] == body["code"]
        created = (await _sheet_row(body["code"])).created_at
        created = created if created.tzinfo else created.replace(tzinfo=UTC)
        assert detail["date"] == created.astimezone(UTC).date().isoformat()
        assert detail["type_text"] == "3490"
        assert detail["strip"] == {"x": 3350, "y": 2400, "w": 2200, "h": 6200}
        assert detail["rotate_180"] is False


async def test_back_side_without_printer_is_422() -> None:
    async with running() as rig:
        resp = await _create(rig, {"type": KEY_3490, "id_placement": "back_side"})
        assert resp.status_code == 422, resp.text
        assert _err(resp)["error_detail"] == {"errors": ["printer"]}  # body.printer


async def test_back_side_on_tape_printer_is_409() -> None:
    async with running() as rig:
        await _printer("tape-1", backend="mock")
        resp = await _create(rig, _back_body(printer="tape-1"))
        assert resp.status_code == 409, resp.text
        assert _err(resp)["error_code"] == "media_kind_mismatch"
        assert await _count(Sheet) == 0


async def test_back_side_respects_printer_restriction() -> None:
    async with running() as rig:
        other = await _printer("page-2")
        restricted = {"X-Label-Hub-Key": await _insert_key(["print"], [str(other)])}
        before = await _counter("A3490")

        resp = await _create(rig, _back_body(), headers=restricted)

        assert resp.status_code == 403, resp.text
        assert await _count(Sheet) == 0
        assert await _counter("A3490") == before


async def test_back_side_refused_while_identity_held() -> None:
    async with running() as rig:
        _hold(rig)
        resp = await _create(rig, _back_body())
        assert resp.status_code == 409, resp.text
        assert _err(resp)["error_code"] == "printer-identity-mismatch"
        assert await _count(Sheet) == 0 and await _count(Job) == 0


async def test_back_side_submit_failure_keeps_sheet(monkeypatch: pytest.MonkeyPatch) -> None:
    async with running() as rig:
        jobs_before = await _count(Job)

        async def unknown(*_a: Any, **_k: Any) -> Any:
            raise KeyError("printer")

        monkeypatch.setattr(rig.app.state.print_queue, "submit_page_job", unknown)
        resp = await _create(rig, _back_body())

        assert resp.status_code == 409, resp.text
        err = _err(resp)
        assert err["error_code"] == "printer-unavailable"
        code = err["error_detail"]["sheet_code"]
        sheet = await rig.sheet(code)
        assert sheet["id_placement"] == "back_side" and sheet["id_printed"] is False
        assert await _count(Job) == jobs_before


async def test_back_side_db_failure_is_500_without_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with running() as rig:

        def broken(_session: Any) -> Any:
            raise RuntimeError("disk I/O error at /secret/path")

        monkeypatch.setattr(ss, "write_transaction", broken)
        transport = httpx.ASGITransport(app=rig.app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            resp = await client.post("/api/v1/sheets", json=_back_body(), headers=rig.key)
        assert resp.status_code == 500
        assert "/secret/path" not in resp.text
        assert await _count(Sheet) == 0


async def test_back_side_failure_after_commit_names_the_sheet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.sheets import print_service

    async with running() as rig:

        async def broken(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError("disk I/O error at /secret/path")

        monkeypatch.setattr(print_service, "_back_payload", broken)
        resp = await _create(rig, _back_body())
        assert resp.status_code == 500, resp.text
        assert "/secret/path" not in resp.text
        err = _err(resp)
        assert err["error_code"] == "sheet_id_job_failed"
        assert (await rig.sheet(err["error_detail"]["sheet_code"]))["id_printed"] is False


# ---------------------------------------------------------------------------- print again


async def test_print_again_queues_a_second_job() -> None:
    async with running() as rig:
        first = (await _create(rig, _back_body())).json()

        resp = await _back(rig, first["code"])

        assert resp.status_code == 202, resp.text
        job_id = resp.json()["job_id"]
        assert job_id != first["job_id"]
        again = await rig.job_payload(job_id)
        assert again["detail"] == (await rig.job_payload(first["job_id"]))["detail"]


async def test_back_side_route_on_margin_sheet() -> None:
    """An unprinted ``cell`` sheet is refused: its ID cell is still due. A printed sheet gets an
    extra code on the back instead (``test_printed_margin_sheet_does_not_switch``)."""
    async with running() as rig:
        code = await _new_sheet("margin", KEY_6121)
        async with _factory()() as s:
            row = (await s.execute(select(Sheet).where(col(Sheet.code) == code))).scalar_one()
            row.id_placement = "cell"
            await s.commit()
        resp = await _back(rig, code)
        assert resp.status_code == 409, resp.text
        assert _err(resp)["error_code"] == "id_placement_mismatch"


async def test_back_side_on_discarded_sheet() -> None:
    async with running() as rig:
        code = await _new_sheet("back_side")
        async with _factory()() as s:
            await ss.discard_sheet(s, code, actor="t")
        resp = await _back(rig, code)
        assert resp.status_code == 409, resp.text
        assert _err(resp)["error_code"] == "sheet_discarded"


async def test_reprint_refused_while_identity_held() -> None:
    async with running() as rig:
        code = await _new_sheet("back_side")
        jobs_before = await _count(Job)
        _hold(rig)
        resp = await _back(rig, code)
        assert resp.status_code == 409, resp.text
        assert _err(resp)["error_code"] == "printer-identity-mismatch"
        assert await _count(Job) == jobs_before


async def test_unprinted_margin_sheet_switches_to_back_side() -> None:
    async with running() as rig:
        code = await _new_sheet("margin")
        events: list[Any] = []
        bus = rig.app.state.event_bus
        original = bus.publish

        def spy(channel: str, event: Any) -> None:
            events.append(event)
            original(channel, event)

        bus.publish = spy
        try:
            resp = await _back(rig, code)
        finally:
            bus.publish = original

        assert resp.status_code == 202, resp.text
        assert (await rig.sheet(code))["id_placement"] == "back_side"
        assert any(getattr(e, "data", {}).get("code") == code for e in events), events
        # Who switched it stays on the sheet (review M5), like created_by and discarded_by.
        async with _factory()() as s:
            row = (await s.execute(select(Sheet).where(col(Sheet.code) == code))).scalar_one()
            assert row.placement_changed_by is not None and row.placement_changed_by.startswith(
                "key:"
            )
            assert row.placement_changed_at is not None


async def test_back_side_sheet_print_records_no_switch() -> None:
    async with running() as rig:
        code = await _new_sheet("back_side")
        assert (await _back(rig, code)).status_code == 202
        async with _factory()() as s:
            row = (await s.execute(select(Sheet).where(col(Sheet.code) == code))).scalar_one()
            assert row.placement_changed_by is None and row.placement_changed_at is None


async def test_printed_margin_sheet_does_not_switch() -> None:
    """A printed margin sheet gets an extra code on the back and keeps its placement (1.7.0
    acceptance; ``test_sheet_code_panel_api`` covers the extra code)."""
    async with running() as rig:
        code = await _new_sheet("margin")
        async with _factory()() as s:
            row = (await s.execute(select(Sheet).where(col(Sheet.code) == code))).scalar_one()
            row.id_printed = True
            await s.commit()
        resp = await _back(rig, code)
        assert resp.status_code == 202, resp.text
        sheet = await rig.sheet(code)
        assert sheet["id_placement"] == "margin" and sheet["back_side_state"] == "pending"


async def test_back_side_queue_unavailable_is_409() -> None:
    async with running() as rig:
        await _printer("page-late")  # added after the start: the queue does not know it
        code = await _new_sheet("back_side")
        resp = await _back(rig, code, printer="page-late")
        assert resp.status_code == 409, resp.text
        assert _err(resp)["error_code"] == "printer-unavailable"


# ---------------------------------------------------------------------------- confirm, retry


async def test_back_job_done_does_not_set_id_printed() -> None:
    async with running() as rig:
        created = (await _create(rig, _back_body())).json()
        await _until_job(created["job_id"], "done")
        assert (await rig.sheet(created["code"]))["id_printed"] is False
        printed = [r for r in rig.fake.received if r.operation == "Print-Job"]
        assert printed and printed[-1].document.startswith(b"%PDF")


async def test_confirm_sets_id_printed() -> None:
    async with running() as rig:
        code = await _new_sheet("back_side")
        events: list[Any] = []
        bus = rig.app.state.event_bus
        original = bus.publish
        bus.publish = lambda channel, event: (events.append(event), original(channel, event))
        try:
            first = await _confirm(rig, code)
            second = await _confirm(rig, code)
        finally:
            bus.publish = original
        assert first.status_code == 200, first.text
        assert first.json()["id_printed"] is True
        assert second.status_code == 200 and second.json()["id_printed"] is True
        assert len([e for e in events if getattr(e, "data", {}).get("code") == code]) == 1


async def test_confirm_on_margin_sheet_is_409() -> None:
    async with running() as rig:
        code = await _new_sheet("margin")
        resp = await _confirm(rig, code)
        assert resp.status_code == 409, resp.text
        assert _err(resp)["error_code"] == "id_placement_mismatch"


async def test_back_job_retry_route_accepts_kind() -> None:
    async with running() as rig:
        rig.fake.print_status = REJECTED
        created = (await _create(rig, _back_body())).json()
        await _until_job(created["job_id"], "failed")
        rig.fake.print_status = 0

        resp = await rig.client.post(f"/api/v1/jobs/{created['job_id']}/retry", headers=rig.key)

        assert resp.status_code == 201, resp.text
        payload = await rig.job_payload(resp.json()["id"])
        assert payload["retry_of"] == created["job_id"]
        assert payload["kind"] == "sheet_back_page"


async def test_retry_of_extra_back_page_on_margin_sheet() -> None:
    """An extra code on the back of a printed margin sheet keeps the margin placement; its failed
    job must still be retryable (Codex review on #399)."""
    async with running() as rig:
        code = await _new_sheet("margin")
        async with _factory()() as s:
            row = (await s.execute(select(Sheet).where(col(Sheet.code) == code))).scalar_one()
            row.id_printed = True
            await s.commit()
        rig.fake.print_status = REJECTED
        resp = await _back(rig, code)
        assert resp.status_code == 202, resp.text
        job_id = resp.json()["job_id"]
        await _until_job(job_id, "failed")
        rig.fake.print_status = 0

        retry = await rig.client.post(f"/api/v1/jobs/{job_id}/retry", headers=rig.key)

        assert retry.status_code == 201, retry.text
        payload = await rig.job_payload(retry.json()["id"])
        assert payload["kind"] == "sheet_back_page" and payload["retry_of"] == job_id


async def test_retry_of_back_page_on_discarded_sheet() -> None:
    async with running() as rig:
        rig.fake.print_status = REJECTED
        created = (await _create(rig, _back_body())).json()
        await _until_job(created["job_id"], "failed")
        async with _factory()() as s:
            await ss.discard_sheet(s, created["code"], actor="t")
        jobs_before = await _count(Job)

        resp = await rig.client.post(f"/api/v1/jobs/{created['job_id']}/retry", headers=rig.key)

        assert resp.status_code == 409, resp.text
        assert _err(resp)["error_code"] == "sheet_discarded"
        assert await _count(Job) == jobs_before


# ---------------------------------------------------------------------------- margin check


async def test_margin_check_names_default_placement() -> None:
    async with running() as rig:
        params = {"type": KEY_3490, "printer": "page-1"}
        resp = await rig.client.get(
            "/api/v1/sheets/margin-check", params=params, headers=rig.reader
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["default_placement"] == "back_side"
        async with _factory()() as s:
            await ts.patch_type(s, KEY_3490, {"id_placement": "cell"}, actor="t")
        cell = await rig.client.get(
            "/api/v1/sheets/margin-check", params=params, headers=rig.reader
        )
        assert cell.json()["default_placement"] == "cell"


async def test_planner_prints_no_margin_id_on_back_side_sheet() -> None:
    async with running() as rig:
        code = await _new_sheet("back_side")
        items = [{"content_type": "text_two_lines", "data": {"title": "T", "primary_id": "1"}}]
        body = {"items": items, "placements": [{"sheet": code}]}
        preview = await rig.client.post(
            "/api/v1/print/page-1/sheet/preview", json=body, headers=rig.key
        )
        assert preview.status_code == 200, preview.text
        (page,) = preview.json()["pages"]
        assert page["id_not_printed"] is False
        resp = await rig.print(body)
        assert resp.status_code == 202, resp.text
        (printed,) = resp.json()["pages"]
        detail = (await rig.job_payload(printed["job_id"]))["detail"]
        assert detail["margin_id"] is None and detail["id_cell"] is None


# ---------------------------------------------------------------------------- reserved cell


async def test_preferred_id_cell_is_used() -> None:
    async with running() as rig:
        body = {"type": KEY_3490, "id_placement": "cell", "printer": "page-1", "id_cell": 5}
        resp = await _create(rig, body)
        assert resp.status_code == 201, resp.text
        id_cells = [c["cell"] for c in resp.json()["cells"] if c["is_id_cell"]]
        assert id_cells == [5]
        detail = (await rig.job_payload(resp.json()["job_id"]))["detail"]
        assert detail["id_cell"]["cell"] == 5


async def test_preferred_id_cell_taken_falls_back_to_first_free() -> None:
    async with running() as rig:
        body = {
            "type": KEY_3490,
            "id_placement": "cell",
            "printer": "page-1",
            "id_cell": 5,
            "used_cells": [{"cell": 5}],
        }
        resp = await _create(rig, body)
        assert resp.status_code == 201, resp.text
        cells = {c["cell"]: c for c in resp.json()["cells"]}
        assert [n for n, c in cells.items() if c["is_id_cell"]] == [1]
        assert cells[5]["state"] == "used" and cells[5]["marked_by_hand"] is True


async def test_preferred_id_cell_beyond_geometry_falls_back() -> None:
    async with running() as rig:
        body = {"type": KEY_3490, "id_placement": "cell", "printer": "page-1", "id_cell": 99}
        resp = await _create(rig, body)
        assert resp.status_code == 201, resp.text
        assert [c["cell"] for c in resp.json()["cells"] if c["is_id_cell"]] == [1]


async def test_cell_sheet_takes_the_type_id_cell() -> None:
    async with running() as rig:
        async with _factory()() as s:
            await ts.patch_type(s, KEY_3490, {"id_cell": 7}, actor="t")
        body = {"type": KEY_3490, "id_placement": "cell", "printer": "page-1"}
        resp = await _create(rig, body)
        assert resp.status_code == 201, resp.text
        assert [c["cell"] for c in resp.json()["cells"] if c["is_id_cell"]] == [7]


# ------------------------------------------------------------- the list marks a missing back side


async def test_list_marks_a_sheet_whose_back_side_is_missing() -> None:
    """``back_side_missing``: placement back_side and the code not confirmed (follow-up of #350)."""
    async with running() as rig:
        pending = await _new_sheet("back_side")
        confirmed = await _new_sheet("back_side")
        margin = await _new_sheet("margin")
        assert (await _confirm(rig, confirmed)).status_code == 200
        resp = await rig.client.get("/api/v1/sheets", params={"type": KEY_3490}, headers=rig.reader)
        assert resp.status_code == 200, resp.text
        flags = {s["code"]: s["back_side_missing"] for s in resp.json()}
        assert flags[pending] is True
        assert flags[confirmed] is False
        assert flags[margin] is False
        # The detail carries the same flag.
        assert (await rig.sheet(pending))["back_side_missing"] is True
        assert (await rig.sheet(confirmed))["back_side_missing"] is False
