# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""How a tray takes paper: the answer and the guided test page (#350, R-350-5, R-350-10)."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from app.models.job import Job
from app.models.printer_tray_loading import PrinterTrayLoading
from app.schemas.printer_admin import TrayIn
from app.services.printer_admin_service import PrinterAdminService
from sqlalchemy import select
from sqlmodel import col

from tests.integration.api.test_identity_resolve import _flag_swap, _resolve
from tests.integration.api.test_sheet_print_api import Rig, _count, _err, _factory, running
from tests.integration.api.test_sheet_types_api import _insert_key

pytestmark = pytest.mark.asyncio

UP_TOP = {"print_side": "up", "leading_edge": "top"}
DOWN_BOTTOM = {"print_side": "down", "leading_edge": "bottom"}


def _url(rig: Rig, tray: str = "auto") -> str:
    return f"/api/v1/printers/{rig.printer_id}/trays/{tray}/loading"


async def _put(rig: Rig, body: dict[str, str], headers: dict[str, str], tray: str = "auto") -> Any:
    return await rig.client.put(_url(rig, tray), json=body, headers=headers)


async def _admin() -> dict[str, str]:
    return {"X-Label-Hub-Key": await _insert_key(["admin"])}


async def _rows(rig: Rig) -> dict[str, tuple[str, str]]:
    async with _factory()() as s:
        rows = (
            await s.execute(
                select(PrinterTrayLoading).where(
                    col(PrinterTrayLoading.printer_id) == rig.printer_id
                )
            )
        ).scalars()
        return {r.tray_key: (r.print_side, r.leading_edge) for r in rows}


async def _capabilities(rig: Rig) -> dict[str, Any]:
    resp = await rig.client.get(
        f"/api/v1/printers/{rig.printer_id}/capabilities", headers=rig.reader
    )
    assert resp.status_code == 200, resp.text
    return {t["key"]: t for t in resp.json()["trays"]}


async def test_print_scope_sets_unset_loading() -> None:
    async with running() as rig:
        assert (await _capabilities(rig))["auto"]["loading"] is None
        resp = await _put(rig, DOWN_BOTTOM, rig.key)
        assert resp.status_code == 200, resp.text
        assert resp.json() == DOWN_BOTTOM
        assert (await _capabilities(rig))["auto"]["loading"] == DOWN_BOTTOM


async def test_print_scope_cannot_overwrite_loading() -> None:
    async with running() as rig:
        assert (await _put(rig, UP_TOP, await _admin())).status_code == 200
        resp = await _put(rig, DOWN_BOTTOM, rig.key)
        assert resp.status_code == 409, resp.text
        assert _err(resp)["error_code"] == "tray_loading_already_set"
        assert await _rows(rig) == {"auto": ("up", "top")}


async def test_admin_overwrites_loading() -> None:
    async with running() as rig:
        admin = await _admin()
        assert (await _put(rig, UP_TOP, rig.key)).status_code == 200
        resp = await _put(rig, DOWN_BOTTOM, admin)
        assert resp.status_code == 200, resp.text
        assert await _rows(rig) == {"auto": ("down", "bottom")}


async def test_two_print_scope_puts_one_wins_other_409() -> None:
    async with running() as rig:
        other = {"X-Label-Hub-Key": await _insert_key(["print"])}
        first, second = await asyncio.gather(
            _put(rig, UP_TOP, rig.key), _put(rig, DOWN_BOTTOM, other)
        )
        codes = sorted([first.status_code, second.status_code])
        assert codes == [200, 409], (first.text, second.text)
        winner = first if first.status_code == 200 else second
        stored = await _rows(rig)
        assert stored == {"auto": (winner.json()["print_side"], winner.json()["leading_edge"])}


async def test_loading_removed_with_its_tray() -> None:
    async with running() as rig:
        assert (await _put(rig, UP_TOP, rig.key)).status_code == 200
        async with _factory()() as s:
            await PrinterAdminService(s, audit_user="t")._replace_trays(
                rig.printer_id, [TrayIn(key="off", label="Off", enabled=False)]
            )
            await s.commit()
        assert await _rows(rig) == {}


async def test_loading_survives_tray_replace() -> None:
    async with running() as rig:
        assert (await _put(rig, UP_TOP, rig.key)).status_code == 200
        async with _factory()() as s:
            await PrinterAdminService(s, audit_user="t")._replace_trays(
                rig.printer_id,
                [
                    TrayIn(key="auto", label="Auto renamed", is_default=True),
                    TrayIn(key="off", label="Off", enabled=False),
                ],
            )
            await s.commit()
        assert await _rows(rig) == {"auto": ("up", "top")}


async def test_loading_cleared_when_device_replaced() -> None:
    async with running() as rig:
        assert (await _put(rig, UP_TOP, rig.key)).status_code == 200
        await _flag_swap(rig)
        resp = await _resolve(rig, "replaced")
        assert resp.status_code == 200, resp.text
        assert await _rows(rig) == {}


async def test_loading_needs_printer_access() -> None:
    async with running() as rig:
        restricted = {"X-Label-Hub-Key": await _insert_key(["print"], ["not-this-printer"])}
        resp = await _put(rig, UP_TOP, restricted)
        assert resp.status_code == 403, resp.text
        page = await rig.client.post(f"{_url(rig)}/test-page", headers=restricted)
        assert page.status_code == 403, page.text
        assert await _rows(rig) == {}


async def test_loading_unknown_tray_is_422() -> None:
    async with running() as rig:
        resp = await _put(rig, UP_TOP, rig.key, tray="nope")
        assert resp.status_code == 422, resp.text
        assert _err(resp)["error_code"] == "tray_unknown"
        assert await _rows(rig) == {}


async def test_loading_db_failure_is_500_without_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import tray_loading_service

    async with running() as rig:

        def broken(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError("disk I/O error at /secret/path")

        monkeypatch.setattr(tray_loading_service, "insert", broken)
        transport = httpx.ASGITransport(app=rig.app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            resp = await client.put(_url(rig), json=UP_TOP, headers=rig.key)
        assert resp.status_code == 500
        assert "/secret/path" not in resp.text


# ---------------------------------------------------------------------------- the test page


async def test_loading_test_page_queues_job() -> None:
    async with running() as rig:
        resp = await rig.client.post(f"{_url(rig)}/test-page", headers=rig.key)
        assert resp.status_code == 202, resp.text
        payload = await rig.job_payload(resp.json()["job_id"])
        assert payload["kind"] == "tray_loading_page" and payload["tray"] == "auto"
        assert payload["detail"]["top_text"] == "TOP ↑"
        assert "sheet_id" not in payload["detail"]


async def test_loading_test_page_not_held() -> None:
    async with running() as rig:
        rig.app.state.print_queue.set_identity_hold(rig.printer_id, True)
        resp = await rig.client.post(f"{_url(rig)}/test-page", headers=rig.key)
        assert resp.status_code == 202, resp.text


async def test_loading_test_page_queue_unavailable_is_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with running() as rig:
        jobs_before = await _count(Job)

        async def unknown(*_a: Any, **_k: Any) -> Any:
            raise KeyError("printer")

        monkeypatch.setattr(rig.app.state.print_queue, "submit_page_job", unknown)
        resp = await rig.client.post(f"{_url(rig)}/test-page", headers=rig.key)
        assert resp.status_code == 409, resp.text
        assert _err(resp)["error_code"] == "printer-unavailable"
        assert await _count(Job) == jobs_before


async def test_loading_page_retry_is_accepted() -> None:
    from tests.integration.api.test_page_job_retry import REJECTED, _until_job

    async with running() as rig:
        rig.fake.print_status = REJECTED
        job_id = (await rig.client.post(f"{_url(rig)}/test-page", headers=rig.key)).json()["job_id"]
        await _until_job(job_id, "failed")
        rig.fake.print_status = 0
        resp = await rig.client.post(f"/api/v1/jobs/{job_id}/retry", headers=rig.key)
        assert resp.status_code == 201, resp.text
        assert (await rig.job_payload(resp.json()["id"]))["retry_of"] == job_id
