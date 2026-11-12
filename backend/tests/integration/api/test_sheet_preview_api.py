"""HTTP tests of POST /api/v1/print/{printer}/sheet/preview: scopes, errors, no echo, no writes."""

from __future__ import annotations

import base64
import io
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import app.models  # noqa: F401
import httpx
import pytest
from app.models.printer import Printer
from app.models.printer_status_cache import PrinterStatusCache
from app.models.printer_tray import PrinterTray
from app.models.sheet import Sheet, SheetCell
from app.printer_backends.ipp.attributes import IppStatusRecord
from app.services.producers.ipp_status_producer import _empty_summary
from app.sheets import sheet_service as ss
from app.sheets import type_service as ts
from app.sheets.geometry import Geometry
from app.sheets.sheet_service import MarkedCell
from PIL import Image
from sqlalchemy import func, select

from tests.integration.api.test_sheet_types_api import _factory, _insert_key

pytestmark = pytest.mark.asyncio

G48 = Geometry("A4", 21000, 29700, 4570, 2120, 4, 12, 4850, 2120, 2150, 840, None, "rectangle")
SENTINEL = "ZQX-private-label-text"


def _record() -> IppStatusRecord:
    summary = _empty_summary().model_copy(
        update={"resolutions_dpi": [600], "pdf_supported": True, "state": "idle"}
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


async def _printer(
    *, backend: str = "ipp", enabled: bool = True, slug: str | None = None, model: str = "m"
) -> tuple[str, str]:
    async with _factory()() as s:
        p = Printer(
            id=uuid4(),
            name=f"P {uuid4().hex[:6]}",
            slug=slug or f"p-{uuid4().hex[:6]}",
            model=model,
            backend=backend,
            connection={"uri": "ipp://printer.example.invalid/ipp"},
            enabled=enabled,
        )
        s.add(p)
        s.add(PrinterTray(printer_id=p.id, tray_key="auto", label="Auto", is_default=True))
        s.add(PrinterTray(printer_id=p.id, tray_key="off", label="Off", enabled=False))
        s.add(
            PrinterStatusCache(
                printer_id=p.id,
                parsed=_record().model_dump(mode="json"),
                captured_at=datetime.now(UTC),
            )
        )
        await s.commit()
        return str(p.id), p.slug


async def _sheet(used: int = 0) -> str:
    async with _factory()() as s:
        try:
            await ts.create_type(
                s, ts.TypeFields("acme-t1", "AT1", "Acme", ["T-1"], None, None), G48, actor="t"
            )
        except Exception:
            await s.rollback()
        sheet = await ss.create_sheet(
            s,
            type_key="acme-t1",
            version=None,
            id_placement="manual",
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


def _url(printer: str) -> str:
    return f"/api/v1/print/{printer}/sheet/preview"


def _err(resp: httpx.Response) -> dict[str, Any]:
    detail = resp.json()["detail"]
    assert set(detail) == {"error_code", "error_message", "error_detail"}, detail
    return detail


@pytest.fixture
async def reader() -> dict[str, str]:
    return {"X-Label-Hub-Key": await _insert_key(["read"])}


async def test_read_scope_gets_the_preview_by_id_and_by_slug(
    api_client_with_seed: httpx.AsyncClient, reader: dict[str, str]
) -> None:
    pid, slug = await _printer()
    code = await _sheet(used=4)

    for key in (pid, slug):
        resp = await api_client_with_seed.post(_url(key), json=_body(code), headers=reader)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        (page,) = body["pages"]
        assert page["sheet_code"] == code and page["feed_mark"] is True
        assert [c["cell"] for c in page["cells"] if c["state"] == "new"] == [5, 6, 7]
        assert body["free_after"] == [41]
        assert body["expected_cells"] == [{"sheet": code, "cells": [5, 6, 7], "id_cell": None}]
        png = Image.open(io.BytesIO(base64.b64decode(page["png_base64"])))
        assert (png.size, png.mode) == ((1240, 1754), "1")
        assert page["geometry"]["cols"] == 4


async def test_preview_leaves_the_sheet_untouched(
    api_client_with_seed: httpx.AsyncClient, reader: dict[str, str]
) -> None:
    pid, _ = await _printer()
    code = await _sheet(used=2)

    # #277: one sheet per run: the existing and the new sheet are two previews.
    hints: list[str | None] = []
    for placement in ({"sheet": code}, {"new_sheet": {"type": "acme-t1"}}):
        resp = await api_client_with_seed.post(
            _url(pid),
            json={"items": [_item(i) for i in range(2)], "placements": [placement]},
            headers=reader,
        )
        assert resp.status_code == 200, resp.text
        hints.extend(p["new_code_hint"] for p in resp.json()["pages"])

    assert hints == [None, "AT1-0002"]
    async with _factory()() as s:
        assert (await s.execute(select(func.count()).select_from(Sheet))).scalar() == 1
        assert (await s.execute(select(func.count()).select_from(SheetCell))).scalar() == 2


async def test_a_key_for_another_printer_is_refused(
    api_client_with_seed: httpx.AsyncClient,
) -> None:
    pid, _ = await _printer()
    other, _ = await _printer()
    code = await _sheet()
    key = {"X-Label-Hub-Key": await _insert_key(["read"], [other])}

    resp = await api_client_with_seed.post(_url(pid), json=_body(code), headers=key)

    assert resp.status_code == 403
    assert resp.json()["detail"]["error_code"] == "printer_not_allowed"


async def test_no_key_is_refused(api_client_with_seed: httpx.AsyncClient) -> None:
    pid, _ = await _printer()

    resp = await api_client_with_seed.post(_url(pid), json=_body("AT1-0001"))

    assert resp.status_code in (401, 403)


async def test_unknown_printer_is_404(
    api_client_with_seed: httpx.AsyncClient, reader: dict[str, str]
) -> None:
    resp = await api_client_with_seed.post(
        _url(str(uuid4())), json=_body("AT1-0001"), headers=reader
    )

    assert resp.status_code == 404
    assert _err(resp)["error_code"] == "printer_not_found"


async def test_a_tape_printer_is_a_media_kind_mismatch(
    api_client_with_seed: httpx.AsyncClient, reader: dict[str, str]
) -> None:
    pid, _ = await _printer(backend="mock", model="PT-P750W")
    code = await _sheet()

    resp = await api_client_with_seed.post(_url(pid), json=_body(code), headers=reader)

    assert resp.status_code == 409
    assert _err(resp)["error_code"] == "media_kind_mismatch"


async def test_a_disabled_printer_is_refused_at_the_route(
    api_client_with_seed: httpx.AsyncClient, reader: dict[str, str]
) -> None:
    pid, _ = await _printer(enabled=False)
    code = await _sheet()

    resp = await api_client_with_seed.post(_url(pid), json=_body(code), headers=reader)

    assert resp.status_code == 409
    assert _err(resp)["error_code"] == "printer_disabled"


@pytest.mark.parametrize("tray", ["nope", "off"])
async def test_an_unknown_or_disabled_tray_is_422(
    api_client_with_seed: httpx.AsyncClient, reader: dict[str, str], tray: str
) -> None:
    pid, _ = await _printer()
    code = await _sheet()

    resp = await api_client_with_seed.post(_url(pid), json=_body(code, tray=tray), headers=reader)

    assert resp.status_code == 422
    detail = _err(resp)
    assert detail["error_code"] == "tray_unknown" and detail["error_detail"] == {"trays": []}
    assert tray not in resp.text.replace("tray_unknown", "")  # C19: no echo of the key


async def test_501_items_are_refused_without_echoing_the_input(
    api_client_with_seed: httpx.AsyncClient, reader: dict[str, str]
) -> None:
    pid, _ = await _printer()
    code = await _sheet()
    body = {
        "items": [
            {"content_type": "text_one_line", "data": {"primary_id": SENTINEL}} for _ in range(501)
        ],
        "placements": [{"sheet": code}],
    }

    resp = await api_client_with_seed.post(_url(pid), json=body, headers=reader)

    assert resp.status_code == 422
    detail = _err(resp)
    assert detail["error_code"] == "invalid_request"
    assert detail["error_detail"] == {"errors": ["items"]}
    assert SENTINEL not in resp.text


async def test_a_130_character_purpose_is_refused_without_echoing_it(
    api_client_with_seed: httpx.AsyncClient, reader: dict[str, str]
) -> None:
    pid, _ = await _printer()
    code = await _sheet()
    body = _body(code)
    body["items"][1]["purpose"] = SENTINEL + "x" * 130

    resp = await api_client_with_seed.post(_url(pid), json=body, headers=reader)

    assert resp.status_code == 422
    assert _err(resp)["error_detail"] == {"errors": ["items.1.purpose"]}
    assert SENTINEL not in resp.text


async def test_unknown_fields_and_options_are_refused_by_path_only(
    api_client_with_seed: httpx.AsyncClient, reader: dict[str, str]
) -> None:
    pid, _ = await _printer()
    code = await _sheet()
    body = _body(code)
    body["items"][0]["options"] = {"copies": 3, SENTINEL: 1}

    resp = await api_client_with_seed.post(_url(pid), json=body, headers=reader)

    assert resp.status_code == 422
    assert _err(resp)["error_detail"] == {"errors": ["items.0.<unknown field>"]}
    assert SENTINEL not in resp.text


async def test_placement_needs_exactly_one_target(
    api_client_with_seed: httpx.AsyncClient, reader: dict[str, str]
) -> None:
    pid, _ = await _printer()
    code = await _sheet()
    body = _body(code)
    body["placements"] = [{"sheet": code, "new_sheet": {"type": "acme-t1"}}]

    resp = await api_client_with_seed.post(_url(pid), json=body, headers=reader)

    assert resp.status_code == 422
    assert _err(resp)["error_code"] == "invalid_request"


@pytest.mark.parametrize("version", [2**63, 2**70, 1_000_001])
async def test_an_oversized_sheet_version_is_a_422_not_a_500(
    api_client_with_seed: httpx.AsyncClient, reader: dict[str, str], version: int
) -> None:
    """R10-7: a version of 2**63 or more reached SQLite as an OverflowError (a bare 500)."""
    pid, _ = await _printer()
    await _sheet()  # creates the type
    body = {
        "items": [_item(0)],
        "placements": [{"new_sheet": {"type": "acme-t1", "version": version}}],
    }

    resp = await api_client_with_seed.post(_url(pid), json=body, headers=reader)

    assert resp.status_code == 422, resp.text
    detail = _err(resp)
    assert detail["error_code"] == "invalid_request"
    assert detail["error_detail"] == {"errors": ["placements.0.new_sheet.version"]}
    assert str(version) not in resp.text  # C19: no echo


async def test_lookup_failure_names_the_item(
    api_client_with_seed: httpx.AsyncClient, reader: dict[str, str]
) -> None:
    pid, _ = await _printer()
    code = await _sheet()
    body = _body(code, 2)
    body["items"].append(
        {"content_type": "qr_two_lines", "lookup": {"app": "no-such-app", "identifier": "7"}}
    )

    resp = await api_client_with_seed.post(_url(pid), json=body, headers=reader)

    assert resp.status_code == 422
    detail = _err(resp)
    assert detail["error_code"] == "integration_unknown_app"
    assert detail["error_detail"] == {"item_index": 2}


async def test_the_route_passes_the_hubs_language_setting(
    api_client_with_seed: httpx.AsyncClient,
    reader: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.sheets import print_service

    await api_client_with_seed.get("/healthz")  # the lifespan starts on the first request
    store = api_client_with_seed._transport.app._app.state.settings_store  # type: ignore[attr-defined]
    original_get = store.get
    monkeypatch.setattr(
        store, "get", lambda key: "de" if key == "general.language" else original_get(key)
    )
    seen: list[str | None] = []
    original = print_service.preview

    async def spy(*args: Any, **kw: Any) -> Any:
        seen.append(kw["language"])
        return await original(*args, **kw)

    monkeypatch.setattr(print_service, "preview", spy)
    pid, _ = await _printer()
    code = await _sheet()

    resp = await api_client_with_seed.post(_url(pid), json=_body(code), headers=reader)

    assert resp.status_code == 200, resp.text
    assert seen == ["de"]


async def test_openapi_documents_the_route_and_its_error_envelope(
    api_client_with_seed: httpx.AsyncClient,
) -> None:
    schema = (await api_client_with_seed.get("/openapi.json")).json()

    op = schema["paths"]["/api/v1/print/{printer_key}/sheet/preview"]["post"]
    assert op["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/SheetPreview"
    )
    assert op["responses"]["422"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/SheetApiErrorResponse"
    )
    assert op["summary"] and op["description"]
    # the tape batch route keeps FastAPI's own validation error
    batch = schema["paths"]["/api/v1/print/{printer_key}/batch"]["post"]
    assert not batch["responses"]["422"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/SheetApiErrorResponse"
    )


async def test_a_513_character_qr_payload_is_refused_by_path_only(
    api_client_with_seed: httpx.AsyncClient, reader: dict[str, str]
) -> None:
    pid, _ = await _printer()
    code = await _sheet()
    body = _body(code)
    body["items"][2]["data"]["qr_payload"] = SENTINEL + "x" * 600

    resp = await api_client_with_seed.post(_url(pid), json=body, headers=reader)

    assert resp.status_code == 422
    assert _err(resp)["error_code"] == "invalid_request"
    assert _err(resp)["error_detail"] == {"errors": ["items.2.data.qr_payload"]}
    assert SENTINEL not in resp.text


class _SlowLookup:
    """An integration that answers after ``delay`` seconds."""

    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.started = 0

    async def lookup(self, source_app: str, identifier: str) -> Any:
        import asyncio

        from app.schemas.label_data import LabelData

        self.started += 1
        await asyncio.sleep(self.delay)
        return LabelData(
            source_app=source_app,
            title=f"T {identifier}",
            primary_id=f"P-{identifier}",
            qr_payload=f"https://x.example.invalid/{identifier}",
        )


@pytest.mark.parametrize("route", ["preview", "print"])
async def test_no_db_connection_is_held_while_the_lookups_run(
    api_client_with_seed: httpx.AsyncClient, route: str
) -> None:
    """R10-1: a request kept its pooled connection through up to 500 slow lookups (and, for the
    preview, through the rendering queue), so about 15 concurrent requests from one key used up
    the pool and every other request timed out. While the lookups run, nothing is checked out."""
    import asyncio

    import app.db.engine as engine_module
    from app.api.routes.sheet_print import get_lookup_service

    # One key per request: a key previews one sheet at a time (266-07).
    keys = {
        "preview": [{"X-Label-Hub-Key": await _insert_key(["read"])} for _ in range(8)],
        "print": [{"X-Label-Hub-Key": await _insert_key(["print"])}] * 8,
    }
    pid, _ = await _printer()
    code = await _sheet()
    await api_client_with_seed.get("/healthz")  # the lifespan starts on the first request
    transport_app = api_client_with_seed._transport.app  # type: ignore[attr-defined]
    fastapi_app = getattr(transport_app, "_app", transport_app)
    slow = _SlowLookup(2.0)
    fastapi_app.dependency_overrides[get_lookup_service] = lambda: slow
    body = {
        "items": [
            {"content_type": "qr_two_lines", "lookup": {"app": "grocy", "identifier": str(i)}}
            for i in range(6)
        ],
        "placements": [{"sheet": code}],
    }
    url = _url(pid) if route == "preview" else f"/api/v1/print/{pid}/sheet"
    pool = engine_module.engine.pool
    baseline = pool.checkedout()  # type: ignore[attr-defined]  # before the requests (266-15)

    try:
        tasks = [
            asyncio.create_task(api_client_with_seed.post(url, json=body, headers=headers))
            for headers in keys[route]
        ]
        for _ in range(100):  # until every request is inside its lookups: 8 x 6 started
            if slow.started >= 48:
                break
            await asyncio.sleep(0.05)
        assert slow.started == 48
        held = pool.checkedout()  # type: ignore[attr-defined]
        await asyncio.gather(*tasks)
    finally:
        fastapi_app.dependency_overrides.pop(get_lookup_service, None)

    assert held <= baseline


class _GatedLookup:
    """An integration that answers once ``gate`` is set; ``entered`` is set by the first call."""

    def __init__(self) -> None:
        import asyncio

        self.gate = asyncio.Event()
        self.entered = asyncio.Event()

    async def lookup(self, source_app: str, identifier: str) -> Any:
        from app.schemas.label_data import LabelData

        self.entered.set()
        await self.gate.wait()
        return LabelData(
            source_app=source_app,
            title=f"T {identifier}",
            primary_id=f"P-{identifier}",
            qr_payload=f"https://x.example.invalid/{identifier}",
        )


async def test_preview_cap_per_key(api_client_with_seed: httpx.AsyncClient) -> None:
    """266-07: one preview per key at a time; the second answers 429 in the rate limit's shape.
    Another key is not affected, and the key may preview again once the first one ended."""
    import asyncio

    from app.api.routes.sheet_print import get_lookup_service

    mine = {"X-Label-Hub-Key": await _insert_key(["read"])}
    other = {"X-Label-Hub-Key": await _insert_key(["read"])}
    pid, _ = await _printer()
    code = await _sheet()
    await api_client_with_seed.get("/healthz")  # the lifespan starts on the first request
    transport_app = api_client_with_seed._transport.app  # type: ignore[attr-defined]
    fastapi_app = getattr(transport_app, "_app", transport_app)
    gated = _GatedLookup()
    fastapi_app.dependency_overrides[get_lookup_service] = lambda: gated
    body = {
        "items": [{"content_type": "qr_two_lines", "lookup": {"app": "grocy", "identifier": "1"}}],
        "placements": [{"sheet": code}],
    }
    try:
        first = asyncio.create_task(api_client_with_seed.post(_url(pid), json=body, headers=mine))
        async with asyncio.timeout(5):
            await gated.entered.wait()  # the first preview is inside its lookup

        second = await api_client_with_seed.post(_url(pid), json=_body(code), headers=mine)
        assert second.status_code == 429, second.text
        detail = second.json()["detail"]
        assert set(detail) == {"error_code", "error_message", "retry_after_seconds"}
        assert detail["error_code"] == "too-many-previews"
        assert second.headers["Retry-After"] == str(detail["retry_after_seconds"])

        third = await api_client_with_seed.post(_url(pid), json=_body(code), headers=other)
        assert third.status_code == 200, third.text

        gated.gate.set()
        assert (await first).status_code == 200
    finally:
        gated.gate.set()
        fastapi_app.dependency_overrides.pop(get_lookup_service, None)

    # Release path: the slot is free after a success and after a failure.
    again = await api_client_with_seed.post(_url(pid), json=_body(code), headers=mine)
    assert again.status_code == 200, again.text
    bad = _body(code, 2)
    bad["items"].append(
        {"content_type": "qr_two_lines", "lookup": {"app": "no-such-app", "identifier": "7"}}
    )
    assert (await api_client_with_seed.post(_url(pid), json=bad, headers=mine)).status_code == 422
    after = await api_client_with_seed.post(_url(pid), json=_body(code), headers=mine)
    assert after.status_code == 200, after.text


async def test_a_preview_past_the_render_limit_is_504_and_the_hub_shows_it_stuck(
    api_client_with_seed: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#293: a hung page render answers 504 ``render-timeout`` in the route's error shape. The
    key keeps its preview slot until the thread ends (429), another key previews meanwhile, and
    readiness counts the stuck render until it ends."""
    import asyncio
    import threading

    from app.services import render_slots
    from app.sheets import print_service

    headers = {"X-Label-Hub-Key": await _insert_key(["read"])}
    pid, _ = await _printer()
    code = await _sheet()
    real_draw = print_service._draw_page
    release = threading.Event()

    def hung(*args: Any) -> Any:
        release.wait(10.0)
        return real_draw(*args)

    monkeypatch.setattr(render_slots, "default_timeout_s", lambda: 0.05)
    monkeypatch.setattr(print_service, "_draw_page", hung)
    try:
        resp = await api_client_with_seed.post(_url(pid), json=_body(code), headers=headers)
        assert resp.status_code == 504, resp.text
        detail = resp.json()["detail"]
        assert set(detail) == {"error_code", "error_message", "error_detail"}
        assert detail["error_code"] == "render-timeout"
        assert SENTINEL not in resp.text

        ready = await api_client_with_seed.get("/readiness", headers=headers)
        assert ready.status_code == 200, ready.text
        check = ready.json()["checks"]["render_slots"]
        assert check["metric"] == {"stuck": 1, "slots": render_slots.MAX_CONCURRENT_RENDERS}

        monkeypatch.setattr(print_service, "_draw_page", real_draw)
        monkeypatch.setattr(render_slots, "default_timeout_s", lambda: 30.0)
        # The key's render still draws: its next preview is refused, another key's runs.
        again = await api_client_with_seed.post(_url(pid), json=_body(code), headers=headers)
        assert again.status_code == 429, again.text
        assert again.json()["detail"]["error_code"] == "too-many-previews"
        other = {"X-Label-Hub-Key": await _insert_key(["read"])}
        theirs = await api_client_with_seed.post(_url(pid), json=_body(code), headers=other)
        assert theirs.status_code == 200, theirs.text
    finally:
        release.set()
    async with asyncio.timeout(10):
        while render_slots.stuck_renders():
            await asyncio.sleep(0.01)
    after = await api_client_with_seed.post(_url(pid), json=_body(code), headers=headers)
    assert after.status_code == 200, after.text


async def test_a_real_preview_draws_with_a_single_render_slot(
    api_client_with_seed: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deadlock guard (#293): the preview takes one render slot per page and none inside it;
    with only one slot it still answers."""
    import asyncio

    from app.services import render_slots

    headers = {"X-Label-Hub-Key": await _insert_key(["read"])}
    pid, _ = await _printer()
    code = await _sheet()
    await api_client_with_seed.get("/healthz")
    slots = render_slots._current()
    monkeypatch.setattr(slots, "gate", asyncio.Semaphore(1))
    async with asyncio.timeout(20):
        resp = await api_client_with_seed.post(_url(pid), json=_body(code), headers=headers)
    assert resp.status_code == 200, resp.text
    assert render_slots.free_slots() == render_slots.MAX_CONCURRENT_RENDERS


async def test_a_preview_without_a_free_render_slot_is_503_at_once(
    api_client_with_seed: httpx.AsyncClient,
) -> None:
    """F2 (#293): with every slot stuck the preview answers 503 ``render-unavailable`` in the
    route's error shape at once, instead of hanging until the client gives up."""
    import asyncio
    import threading

    from app.services import render_slots

    headers = {"X-Label-Hub-Key": await _insert_key(["read"])}
    pid, _ = await _printer()
    code = await _sheet()
    await api_client_with_seed.get("/healthz")
    release = threading.Event()
    try:
        for _ in range(render_slots.MAX_CONCURRENT_RENDERS):
            with pytest.raises(render_slots.RenderTimeoutError):
                await render_slots.render_bounded(
                    lambda: release.wait(10.0), label="t", timeout_s=0.05
                )
        async with asyncio.timeout(5):
            resp = await api_client_with_seed.post(_url(pid), json=_body(code), headers=headers)
        assert resp.status_code == 503, resp.text
        detail = resp.json()["detail"]
        assert set(detail) == {"error_code", "error_message", "error_detail"}
        assert detail["error_code"] == "render-unavailable"
    finally:
        release.set()
    async with asyncio.timeout(10):
        while render_slots.stuck_renders():
            await asyncio.sleep(0.01)


async def test_a_key_with_a_stuck_page_job_render_gets_429_for_its_preview(
    api_client_with_seed: httpx.AsyncClient,
) -> None:
    """F1 (#293): stuck renders count per key across previews and page jobs."""
    import asyncio
    import threading
    from uuid import UUID

    from app.services import render_slots

    key = await _insert_key(["read"])
    pid, _ = await _printer()
    code = await _sheet()
    await api_client_with_seed.get("/healthz")
    async with _factory()() as s:
        from app.models.api_key import ApiKey

        key_id = (
            await s.execute(select(ApiKey.id).where(ApiKey.key_prefix == key[:16]))
        ).scalar_one()
    release = threading.Event()
    try:
        with pytest.raises(render_slots.RenderTimeoutError):
            await render_slots.render_bounded(
                lambda: release.wait(10.0),
                label="page job",
                owner=render_slots.owner_of(UUID(str(key_id))),
                timeout_s=0.05,
            )
        resp = await api_client_with_seed.post(
            _url(pid), json=_body(code), headers={"X-Label-Hub-Key": key}
        )
        assert resp.status_code == 429, resp.text
        assert resp.json()["detail"]["error_code"] == "too-many-previews"
        other = {"X-Label-Hub-Key": await _insert_key(["read"])}
        theirs = await api_client_with_seed.post(_url(pid), json=_body(code), headers=other)
        assert theirs.status_code == 200, theirs.text
    finally:
        release.set()
    async with asyncio.timeout(10):
        while render_slots.stuck_renders():
            await asyncio.sleep(0.01)
