# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""#358: the calibration page runs under the render slots and refuses oversized grids.

The download draws in a worker thread under the process-wide render slots (``render_slots``),
like the sheet preview; the grid cap is checked in ``build_payload`` so the print route and the
download both refuse before anything is drawn.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any
from uuid import UUID

import httpx
import pytest
from app.api.routes import calibration as calibration_routes
from app.calibration import page as page_module
from app.calibration.page import MAX_CALIBRATION_CELLS
from app.models.sheet import SheetType, SheetTypeVersion
from app.services import render_slots
from app.sheets.geometry import Geometry
from sqlalchemy import select, update

from tests.integration.api.test_calibration_page_api import _factory, _key, _printer, _type

pytestmark = pytest.mark.asyncio

# 210 x 297 mm, no margin: 420 x 594 (1/100 mm) pitch, so the cell count is cols * rows.
# The type service refuses more than 400 cells (``geometry.MAX_CELLS``); the calibration cap is a
# second line for rows that did not come through it, so these grids are written to the database
# directly (``_grid_type``).
G50 = Geometry("A4", 21000, 29700, 400, 580, 50, 50, 420, 594, 0, 0, None, "rectangle")
G60 = Geometry("A4", 21000, 29700, 330, 480, 60, 60, 350, 495, 0, 0, None, "rectangle")


def _err(resp: Any) -> dict[str, Any]:
    return resp.json()["detail"]


def _pdf_url(pid: UUID, type_key: str) -> str:
    return f"/api/v1/printers/{pid}/calibration/auto/page/pdf?type={type_key}"


async def _grid_type(key: str, g: Geometry) -> None:
    """A type whose stored version has the grid ``g``, written past the type service's checks."""
    await _type(_factory(), key)
    async with _factory()() as s:
        type_id = (await s.execute(select(SheetType.id).where(SheetType.key == key))).scalar_one()
        await s.execute(
            update(SheetTypeVersion)
            .where(SheetTypeVersion.type_id == type_id)
            .values(
                cols=g.cols,
                rows=g.rows,
                label_w=g.label_w,
                label_h=g.label_h,
                pitch_x=g.pitch_x,
                pitch_y=g.pitch_y,
                margin_top=g.margin_top,
                margin_left=g.margin_left,
            )
        )
        await s.commit()


async def _drain() -> None:
    async with asyncio.timeout(10):
        while render_slots.stuck_renders() or render_slots.free_slots() < 2:
            await asyncio.sleep(0.01)


async def test_grid_over_the_cap_is_422_for_download(
    api_client_with_seed: httpx.AsyncClient,
) -> None:
    await _grid_type("cap-dl", G60)
    pid = await _printer(_factory())
    r = await api_client_with_seed.get(_pdf_url(pid, "cap-dl"), headers=await _key(["read"]))
    assert r.status_code == 422, r.text
    detail = _err(r)
    assert detail["error_code"] == "calibration_grid_too_large"
    assert detail["error_detail"] == {"cells": 3600, "max_cells": MAX_CALIBRATION_CELLS}


async def test_grid_over_the_cap_is_422_for_print(
    api_client_with_seed: httpx.AsyncClient,
) -> None:
    await _grid_type("cap-pr", G60)
    pid = await _printer(_factory())
    r = await api_client_with_seed.post(
        f"/api/v1/printers/{pid}/calibration/auto/page",
        json={"type": "cap-pr"},
        headers=await _key(["print"]),
    )
    assert r.status_code == 422, r.text
    assert _err(r)["error_code"] == "calibration_grid_too_large"
    assert _err(r)["error_detail"] == {"cells": 3600, "max_cells": MAX_CALIBRATION_CELLS}


async def test_grid_at_the_cap_renders(api_client_with_seed: httpx.AsyncClient) -> None:
    assert G50.cols * G50.rows == MAX_CALIBRATION_CELLS
    await _grid_type("cap-ok", G50)
    pid = await _printer(_factory())
    r = await api_client_with_seed.get(_pdf_url(pid, "cap-ok"), headers=await _key(["read"]))
    assert r.status_code == 200, r.text
    assert r.content.startswith(b"%PDF")


async def test_download_waits_for_a_render_slot(
    api_client_with_seed: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both slots held by other renders: a third request waits for a slot and gives up with 503
    ``render-unavailable`` within the (shortened) time limit, instead of drawing beside them."""
    await _type(_factory(), "wait-slot")
    pid = await _printer(_factory())
    headers = await _key(["read"])
    await api_client_with_seed.get("/healthz")
    release = threading.Event()
    holders = [
        asyncio.ensure_future(
            render_slots.render_bounded(
                lambda: release.wait(10.0), label="holder", owner=None, timeout_s=30
            )
        )
        for _ in range(render_slots.MAX_CONCURRENT_RENDERS)
    ]
    try:
        async with asyncio.timeout(5):
            while render_slots.free_slots():
                await asyncio.sleep(0.01)
        monkeypatch.setattr(render_slots, "default_timeout_s", lambda: 0.2)
        async with asyncio.timeout(5):
            r = await api_client_with_seed.get(_pdf_url(pid, "wait-slot"), headers=headers)
        assert r.status_code == 503, r.text
        assert _err(r)["error_code"] == "render-unavailable"
        assert set(_err(r)) == {"error_code", "error_message", "error_detail"}
    finally:
        release.set()
        await asyncio.gather(*holders)
    await _drain()


async def test_one_key_cannot_hold_both_slots(
    api_client_with_seed: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A key whose download is drawing holds one slot at most: its second download waits (503),
    while another key still gets the free slot."""
    await _type(_factory(), "own-slot")
    pid = await _printer(_factory())
    first, other = await _key(["read"]), await _key(["read"])
    await api_client_with_seed.get("/healthz")
    release = threading.Event()
    calls: list[int] = []

    def render(payload: Any) -> bytes:
        calls.append(1)
        if len(calls) == 1:
            release.wait(10.0)
        return b"%PDF-fake"

    monkeypatch.setattr(page_module, "render_calibration_page", render)
    url = _pdf_url(pid, "own-slot")
    drawing = asyncio.ensure_future(api_client_with_seed.get(url, headers=first))
    try:
        async with asyncio.timeout(5):
            while render_slots.free_slots() == render_slots.MAX_CONCURRENT_RENDERS:
                await asyncio.sleep(0.01)
        monkeypatch.setattr(render_slots, "default_timeout_s", lambda: 0.2)
        # The same key's second download (same owner) cannot take the second slot.
        again = await api_client_with_seed.get(url, headers=first)
        assert again.status_code == 503, again.text
        assert _err(again)["error_code"] == "render-unavailable"
        assert len(calls) == 1
        # Another key takes the free slot.
        theirs = await api_client_with_seed.get(url, headers=other)
        assert theirs.status_code == 200, theirs.text
    finally:
        release.set()
    assert (await drawing).status_code == 200
    await _drain()


async def test_a_download_past_the_render_limit_is_504_then_429_for_the_key(
    api_client_with_seed: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _type(_factory(), "stuck-dl")
    pid = await _printer(_factory())
    headers = await _key(["read"])
    release = threading.Event()

    def hung(payload: Any) -> bytes:
        release.wait(10.0)
        return b"%PDF-fake"

    monkeypatch.setattr(page_module, "render_calibration_page", hung)
    monkeypatch.setattr(render_slots, "default_timeout_s", lambda: 0.05)
    url = _pdf_url(pid, "stuck-dl")
    try:
        r = await api_client_with_seed.get(url, headers=headers)
        assert r.status_code == 504, r.text
        assert _err(r)["error_code"] == "render-timeout"
        assert set(_err(r)) == {"error_code", "error_message", "error_detail"}
        monkeypatch.setattr(render_slots, "default_timeout_s", lambda: 30.0)
        again = await api_client_with_seed.get(url, headers=headers)
        assert again.status_code == 429, again.text
        assert again.json()["detail"]["error_code"] == "too-many-previews"
        assert again.headers["retry-after"] == "1"
    finally:
        release.set()
    await _drain()


async def test_error_texts_are_fixed_strings(
    api_client_with_seed: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No printer name or upstream text reaches the answer of a refused download."""
    await _type(_factory(), "fixed-txt")
    pid = await _printer(_factory())
    headers = await _key(["read"])

    def boom(*a: Any, **k: Any) -> Any:
        raise render_slots.RenderUnavailableError("printer 10.9.8.7 said no")

    monkeypatch.setattr(calibration_routes.render_slots, "render_bounded", boom)
    r = await api_client_with_seed.get(_pdf_url(pid, "fixed-txt"), headers=headers)
    assert r.status_code == 503, r.text
    assert "10.9.8.7" not in r.text
