# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""HTTP tests of the sheet code panel's writes (1.7.0 acceptance of rc.7).

An extra back side on a sheet whose code is printed elsewhere (``back_side_state``), when
"Back side missing" applies, and reprinting the margin code of a ``margin`` sheet. The full app
with its lifespan, like ``test_sheet_back_side_api``.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from app.models.job import Job
from app.models.sheet import Sheet, SheetCell
from app.sheets import print_service
from app.sheets import sheet_service as ss
from sqlalchemy import func, select
from sqlmodel import col

from tests.integration.api.test_sheet_back_side_api import (
    KEY_3490,
    KEY_6121,
    _back,
    _confirm,
    _hold,
    _new_sheet,
)
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


async def _printed(placement: str, key: str = KEY_6121) -> str:
    """A sheet whose code counts as printed (``id_printed``), like L4736-0001 in the report."""
    code = await _new_sheet("margin" if placement == "cell" else placement, key)
    async with _factory()() as s:
        row = (await s.execute(select(Sheet).where(col(Sheet.code) == code))).scalar_one()
        row.id_placement = placement  # a cell sheet is created through its ID-only job
        row.id_printed = True
        await s.commit()
    return code


async def _margin(rig: Rig, code: str, **kw: Any) -> httpx.Response:
    headers = kw.pop("headers", rig.key)
    body = {"printer": kw.pop("printer", "page-1"), **kw}
    return await rig.client.post(f"/api/v1/sheets/{code}/margin-id", json=body, headers=headers)


async def _cells_of(code: str) -> int:
    async with _factory()() as s:
        sheet = (await s.execute(select(Sheet).where(col(Sheet.code) == code))).scalar_one()
        stmt = (
            select(func.count()).select_from(SheetCell).where(col(SheetCell.sheet_id) == sheet.id)
        )
        return int((await s.execute(stmt)).scalar_one())


async def _sheet_id(code: str) -> Any:
    async with _factory()() as s:
        return (await s.execute(select(Sheet).where(col(Sheet.code) == code))).scalar_one().id


async def _missing_in_list(rig: Rig, code: str, key: str = KEY_6121) -> bool:
    resp = await rig.client.get("/api/v1/sheets", params={"type": key}, headers=rig.reader)
    assert resp.status_code == 200, resp.text
    flags: dict[str, bool] = {s["code"]: s["back_side_missing"] for s in resp.json()}
    return flags[code]


# ---------------------------------------------------------------------------- extra back side


async def test_margin_sheet_without_back_side_is_not_missing() -> None:
    async with running() as rig:
        code = await _printed("margin")
        sheet = await rig.sheet(code)
        assert sheet["back_side_state"] is None
        assert sheet["back_side_missing"] is False
        assert await _missing_in_list(rig, code) is False


@pytest.mark.parametrize("placement", ["margin", "manual", "cell"])
async def test_extra_back_side_on_printed_sheet(placement: str) -> None:
    async with running() as rig:
        code = await _printed(placement)

        resp = await _back(rig, code)

        assert resp.status_code == 202, resp.text
        payload = await rig.job_payload(resp.json()["job_id"])
        assert payload["kind"] == "sheet_back_page"
        sheet = await rig.sheet(code)
        assert sheet["id_placement"] == placement  # the placement stays
        assert sheet["id_printed"] is True
        assert sheet["back_side_state"] == "pending"
        assert sheet["back_side_missing"] is True
        assert await _missing_in_list(rig, code) is True
        async with _factory()() as s:
            row = (await s.execute(select(Sheet).where(col(Sheet.code) == code))).scalar_one()
            assert row.placement_changed_at is None  # no switch was recorded

        confirmed = await _confirm(rig, code)
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["back_side_state"] == "confirmed"
        assert confirmed.json()["back_side_missing"] is False
        assert await _missing_in_list(rig, code) is False
        again = await _confirm(rig, code)  # idempotent
        assert again.status_code == 200 and again.json()["back_side_state"] == "confirmed"


async def test_extra_back_side_again_is_pending_again() -> None:
    async with running() as rig:
        code = await _printed("margin")
        assert (await _back(rig, code)).status_code == 202
        assert (await _confirm(rig, code)).status_code == 200
        assert (await _back(rig, code)).status_code == 202
        assert (await rig.sheet(code))["back_side_state"] == "pending"


async def test_extra_back_side_respects_printer_restriction() -> None:
    async with running() as rig:
        code = await _printed("margin")
        other = await _printer("page-2")
        restricted = {"X-Label-Hub-Key": await _insert_key(["print"], [str(other)])}
        jobs_before = await _count(Job)
        resp = await rig.client.post(
            f"/api/v1/sheets/{code}/back-side", json={"printer": "page-1"}, headers=restricted
        )
        assert resp.status_code == 403, resp.text
        assert await _count(Job) == jobs_before
        assert (await rig.sheet(code))["back_side_state"] is None


async def test_extra_back_side_on_discarded_sheet() -> None:
    async with running() as rig:
        code = await _printed("margin")
        async with _factory()() as s:
            await ss.discard_sheet(s, code, actor="t")
        resp = await _back(rig, code)
        assert resp.status_code == 409, resp.text
        assert _err(resp)["error_code"] == "sheet_discarded"


async def test_failed_submit_leaves_no_pending_back_side(monkeypatch: pytest.MonkeyPatch) -> None:
    async with running() as rig:
        code = await _printed("margin")

        async def unknown(*_a: Any, **_k: Any) -> Any:
            raise KeyError("printer")

        monkeypatch.setattr(rig.app.state.print_queue, "submit_page_job", unknown)
        resp = await _back(rig, code)
        assert resp.status_code == 409, resp.text
        assert _err(resp)["error_code"] == "printer-unavailable"
        assert (await rig.sheet(code))["back_side_state"] is None


async def test_confirm_without_pending_back_side_is_409() -> None:
    async with running() as rig:
        code = await _printed("margin")
        resp = await _confirm(rig, code)
        assert resp.status_code == 409, resp.text
        assert _err(resp)["error_code"] == "id_placement_mismatch"


async def test_unprinted_cell_sheet_stays_refused() -> None:
    async with running() as rig:
        code = await _printed("cell", KEY_3490)
        async with _factory()() as s:
            row = (await s.execute(select(Sheet).where(col(Sheet.code) == code))).scalar_one()
            row.id_printed = False
            await s.commit()
        resp = await _back(rig, code)
        assert resp.status_code == 409, resp.text
        assert _err(resp)["error_code"] == "id_placement_mismatch"


# ---------------------------------------------------------------------------- margin reprint


async def test_margin_reprint_queues_one_margin_only_page() -> None:
    async with running() as rig:
        code = await _printed("margin")
        jobs_before = await _count(Job)

        resp = await _margin(rig, code)

        assert resp.status_code == 202, resp.text
        assert await _count(Job) == jobs_before + 1
        payload = await rig.job_payload(resp.json()["job_id"])
        assert payload["kind"] == "sheet_page"
        detail = payload["detail"]
        assert detail["sheet_code"] == code
        assert detail["cells"] == [] and detail["id_cell"] is None
        assert detail["margin_id"] is not None and code in detail["margin_id"]["text"]
        assert detail["feed_mark"] is None
        assert await _cells_of(code) == 0  # nothing is reserved
        sheet = await rig.sheet(code)
        assert sheet["id_printed"] is True and sheet["cells"] == []


async def test_margin_reprint_refused_while_margin_id_in_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with running() as rig:
        code = await _printed("margin")

        async def busy(*_a: Any, **_k: Any) -> bool:
            return True

        monkeypatch.setattr(print_service, "margin_id_in_flight", busy)
        jobs_before = await _count(Job)
        resp = await _margin(rig, code)
        assert resp.status_code == 409, resp.text
        assert _err(resp)["error_code"] == "id_placement_mismatch"
        assert await _count(Job) == jobs_before


async def test_queued_margin_reprint_counts_as_in_flight() -> None:
    """The stored page carries ``margin_id``: the shared in-flight rule sees it while it is queued,
    so a second press cannot print the margin code twice."""
    from app.sheets.reservation import _active_sheet_page_carries

    async with running() as rig:
        code = await _printed("margin")
        resp = await _margin(rig, code)
        assert resp.status_code == 202, resp.text
        payload = await rig.job_payload(resp.json()["job_id"])
        sheet_id = await _sheet_id(code)
        assert _active_sheet_page_carries([payload], sheet_id, "margin_id") is True


@pytest.mark.parametrize("placement", ["cell", "manual", "back_side"])
async def test_margin_reprint_on_other_placement_is_409(placement: str) -> None:
    async with running() as rig:
        code = await _printed(placement, KEY_3490)
        resp = await _margin(rig, code)
        assert resp.status_code == 409, resp.text
        assert _err(resp)["error_code"] == "id_placement_mismatch"


async def test_margin_reprint_of_unprinted_margin_sheet_is_409() -> None:
    async with running() as rig:
        code = await _new_sheet("margin", KEY_6121)
        resp = await _margin(rig, code)
        assert resp.status_code == 409, resp.text
        assert _err(resp)["error_code"] == "id_placement_mismatch"


async def test_margin_reprint_on_discarded_sheet() -> None:
    async with running() as rig:
        code = await _printed("margin")
        async with _factory()() as s:
            await ss.discard_sheet(s, code, actor="t")
        resp = await _margin(rig, code)
        assert resp.status_code == 409, resp.text
        assert _err(resp)["error_code"] == "sheet_discarded"


async def test_margin_reprint_respects_printer_restriction() -> None:
    async with running() as rig:
        code = await _printed("margin")
        other = await _printer("page-2")
        restricted = {"X-Label-Hub-Key": await _insert_key(["print"], [str(other)])}
        jobs_before = await _count(Job)
        resp = await _margin(rig, code, headers=restricted)
        assert resp.status_code == 403, resp.text
        assert await _count(Job) == jobs_before


async def test_margin_reprint_needs_print_scope() -> None:
    async with running() as rig:
        code = await _printed("margin")
        resp = await _margin(rig, code, headers=rig.reader)
        assert resp.status_code == 403, resp.text


async def test_margin_reprint_on_tape_printer_is_409() -> None:
    async with running() as rig:
        code = await _printed("margin")
        await _printer("tape-1", backend="mock")
        resp = await _margin(rig, code, printer="tape-1")
        assert resp.status_code == 409, resp.text
        assert _err(resp)["error_code"] == "media_kind_mismatch"


async def test_margin_reprint_refused_while_identity_held() -> None:
    async with running() as rig:
        code = await _printed("margin")
        _hold(rig)
        resp = await _margin(rig, code)
        assert resp.status_code == 409, resp.text
        assert _err(resp)["error_code"] == "printer-identity-mismatch"


async def test_margin_reprint_job_done_leaves_the_sheet_alone() -> None:
    from tests.integration.api.test_page_job_retry import _until_job

    async with running() as rig:
        code = await _printed("margin")
        resp = await _margin(rig, code)
        assert resp.status_code == 202, resp.text
        await _until_job(resp.json()["job_id"], "done")
        sheet = await rig.sheet(code)
        assert sheet["id_printed"] is True and sheet["cells"] == []
        printed = [r for r in rig.fake.received if r.operation == "Print-Job"]
        assert printed and printed[-1].document.startswith(b"%PDF")
