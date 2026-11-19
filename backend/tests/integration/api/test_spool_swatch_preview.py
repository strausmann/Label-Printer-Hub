# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The swatch label through the API: lookup, preview, raw print, print job (#346, R-346-11).

The real app and lifespan run against a temp database with one QL printer whose backend is a
recording ``MockPrinterBackend`` loaded with 62 mm. Spoolman is stubbed with ``respx``; the spool
is fictitious.
"""

from __future__ import annotations

import asyncio
import io
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import app.models  # noqa: F401
import httpx
import pytest
import respx
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_admin, require_print, require_read
from app.config import get_settings
from app.models.job import Job as DbJob
from app.models.printer import Printer
from app.printer_backends.mock_backend import MockPrinterBackend
from app.schemas.label_data import LabelData
from app.schemas.spool_swatch import SpoolSwatch
from app.services.backend_router import BackendRouter
from app.services.rate_limiter import _rate_limiter
from app.services.spool_swatch import (
    SHEET_METRICS,
    SWATCH_TAPES,
    layout_for_box,
    place_swatch,
    render_tape_swatch,
)
from httpx import ASGITransport, AsyncClient
from PIL import Image

from tests.helpers.spool_swatch import L4737REV, seed_box

pytestmark = pytest.mark.asyncio

SPOOLMAN_URL = "https://spoolman.example.invalid"
WEBHOOK_KEY = "webhook-secret-key-at-least-32chars!"
SPOOL = {
    "id": 12,
    "filament": {
        "vendor": {"name": "TecBears"},
        "name": "Orange",
        "material": "PETG",
        "color_hex": "FF5F00",
        "settings_extruder_temp": 230,
        "settings_bed_temp": 80,
        "spool_weight": 124,
        "weight": 1000,
        "diameter": 1.75,
        "density": 1.27,
        "extra": {"flowdynamics": "0.029"},
    },
    "location": "Shelf A2",
    "remaining_weight": 640,
}
URL = f"{SPOOLMAN_URL}/spool/show/12"


@dataclass
class Hub:
    backend: MockPrinterBackend
    printer_id: UUID

    @asynccontextmanager
    async def running(self) -> AsyncIterator[tuple[AsyncClient, Any]]:
        from app.main import create_app

        app = create_app()
        inner = app._app
        auth = AuthContext(source="api-key", scope="admin", api_key_id=uuid4(), ip="127.0.0.1")
        for dep in (require_read, require_print, require_admin):
            inner.dependency_overrides[dep] = lambda _c=auth: _c
        with respx.mock(assert_all_called=False) as router:
            router.get(f"{SPOOLMAN_URL}/api/v1/spool/12").mock(
                return_value=httpx.Response(200, json=SPOOL)
            )
            async with (
                inner.router.lifespan_context(inner),
                AsyncClient(transport=ASGITransport(app=inner), base_url="http://t") as client,
            ):
                yield client, inner


@pytest.fixture
async def hub(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Hub]:
    import app.db.engine as eng
    from app.integrations import (  # type: ignore[attr-defined]
        IntegrationRegistry,
        _discover_plugins,
    )

    if not IntegrationRegistry.names():
        _discover_plugins()
    monkeypatch.setenv("LABELYARD_SPOOLMAN_URL", SPOOLMAN_URL)
    monkeypatch.setenv("LABELYARD_WEBHOOK_API_KEY", WEBHOOK_KEY)
    get_settings.cache_clear()
    _rate_limiter.clear()
    backend = MockPrinterBackend(loaded_tape_mm=62)
    monkeypatch.setattr(BackendRouter, "_build_one", staticmethod(lambda _cfg: backend))
    monkeypatch.setattr(
        "app.services.printer_runtime._resolve_model_id_from_config",
        AsyncMock(return_value="QL-820NWB"),
    )
    async with eng.async_session() as s:
        printer = Printer(
            name="Label QL",
            slug="ql-1",
            model="QL-820NWB",
            backend="brother_ql",
            connection={"host": "198.51.100.11", "port": 9100},
            enabled=True,
        )
        s.add(printer)
        await s.commit()
        printer_id = printer.id
    yield Hub(backend=backend, printer_id=printer_id)
    _rate_limiter.clear()
    get_settings.cache_clear()


async def _row(job_id: str) -> DbJob:
    import app.db.engine as eng

    async with eng.async_session() as s:
        row = await s.get(DbJob, UUID(job_id))
        assert row is not None
        return row


async def _done(job_id: str) -> DbJob:
    async with asyncio.timeout(5.0):
        while (row := await _row(job_id)).state != "done":
            await asyncio.sleep(0.02)
    return row


async def _lookup(client: AsyncClient) -> dict[str, Any]:
    r = await client.get("/api/v1/lookup/spoolman/12")
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


async def _preview_png(
    client: AsyncClient, swatch: Any, url: str, tape_mm: int = 62
) -> Image.Image:
    r = await client.post(
        "/api/v1/render/preview",
        json={
            "content_type": "spool_swatch",
            "tape_mm": tape_mm,
            "data": {"qr_payload": url, "swatch": swatch},
        },
    )
    assert r.status_code == 200, r.text
    return Image.open(io.BytesIO(r.content))


async def test_lookup_returns_extra_swatch(hub: Hub) -> None:
    async with hub.running() as (client, _):
        body = await _lookup(client)
    swatch = body["extra"]["swatch"]
    assert swatch["spool_id"] == 12
    assert (swatch["vendor"], swatch["title"], swatch["color_name"]) == (
        "TecBears",
        "PETG",
        "Orange",
    )
    assert body["extra"]["secondary"] == ["640g remaining"]
    assert body["url"] == URL


async def test_preview_with_raw_swatch_renders_png(hub: Hub) -> None:
    async with hub.running() as (client, _):
        body = await _lookup(client)
        image = await _preview_png(client, body["extra"]["swatch"], body["url"])
    assert image.size == (696, 425)


async def test_preview_on_the_other_dk_widths(hub: Hub) -> None:
    """29/54 mm across (the tape's dots wide), 38/50 mm along (an upright band the tape's dots
    high), each exactly the image the job prints (#346)."""
    async with hub.running() as (client, _):
        body = await _lookup(client)
        for tape_mm, side in ((29, "w"), (38, "h"), (50, "h"), (54, "w")):
            image = await _preview_png(client, body["extra"]["swatch"], body["url"], tape_mm)
            dots = SWATCH_TAPES[tape_mm].dots
            assert (image.width if side == "w" else image.height) == dots, tape_mm
            swatch = SpoolSwatch.model_validate(body["extra"]["swatch"])
            expected = render_tape_swatch(swatch, body["url"], tape_mm)
            assert image.convert("1").tobytes() == expected.tobytes(), tape_mm


async def test_preview_refuses_an_unbounded_swatch(hub: Hub) -> None:
    async with hub.running() as (client, _):
        r = await client.post(
            "/api/v1/render/preview",
            json={
                "content_type": "spool_swatch",
                "tape_mm": 62,
                "data": {"qr_payload": URL, "swatch": {"spool_id": 12, "location": "x" * 65}},
            },
        )
    assert r.status_code == 422


async def test_raw_print_with_swatch_renders(hub: Hub) -> None:
    async with hub.running() as (client, _):
        body = await _lookup(client)
        r = await client.post(
            "/api/v1/print",
            json={
                "content_type": "spool_swatch",
                "data": {"qr_payload": body["url"], "swatch": body["extra"]["swatch"]},
            },
        )
        assert r.status_code == 202, r.text
        await _done(r.json()["job_id"])
    label = LabelData(source_app="manual", qr_payload=body["url"], swatch=body["extra"]["swatch"])
    assert label.swatch is not None
    expected = render_tape_swatch(label.swatch, URL)
    assert hub.backend.printed_images[-1].tobytes() == expected.tobytes()


async def test_raw_print_with_unbounded_swatch_is_422(hub: Hub) -> None:
    async with hub.running() as (client, _):
        r = await client.post(
            "/api/v1/print",
            json={
                "content_type": "spool_swatch",
                "data": {"qr_payload": URL, "swatch": {"spool_id": 12, "vendor": "v" * 65}},
            },
        )
    assert r.status_code == 422


async def _lookup_job(client: AsyncClient) -> DbJob:
    r = await client.post(
        "/api/v1/print",
        json={"content_type": "spool_swatch", "lookup": {"app": "spoolman", "identifier": "12"}},
    )
    assert r.status_code == 202, r.text
    return await _done(r.json()["job_id"])


async def test_preview_equals_the_print_job_image(hub: Hub) -> None:
    async with hub.running() as (client, _):
        body = await _lookup(client)
        preview = await _preview_png(client, body["extra"]["swatch"], body["url"])
        row = await _lookup_job(client)
    assert row.payload["options"]["orientation"] == "across"
    printed = hub.backend.printed_images[-1]
    assert printed.size == preview.size == (696, 425)
    assert printed.convert("L").tobytes() == preview.convert("L").tobytes()


async def test_stored_job_rerenders_identically(hub: Hub) -> None:
    async with hub.running() as (client, inner):
        row = await _lookup_job(client)
        again = inner.state.print_queue._rerender_from_db_payload(row.payload)
    assert again.tobytes() == hub.backend.printed_images[-1].tobytes()


async def test_sheet_preview_and_job_cell_draw_the_same_swatch(hub: Hub) -> None:
    async with hub.running() as (client, _):
        body = await _lookup(client)
    preview_label = LabelData(source_app="spoolman", qr_payload=URL, swatch=body["extra"]["swatch"])
    stored = LabelData(**preview_label.model_dump(mode="json"))  # what a sheet job keeps
    layout = layout_for_box(*seed_box(L4737REV), SHEET_METRICS)
    assert preview_label.swatch is not None and stored.swatch is not None
    a = place_swatch(preview_label.swatch, layout, SHEET_METRICS)
    b = place_swatch(stored.swatch, layout, SHEET_METRICS)
    assert a.layout.tier is b.layout.tier
    assert a.layout.qr_box == b.layout.qr_box
    assert [c.tab for c in a.columns] == [c.tab for c in b.columns]
    assert a.runs == b.runs


async def test_webhook_spoolman_label_is_unchanged(hub: Hub) -> None:
    async with hub.running() as (client, _):
        r = await client.post(
            "/api/v1/webhook/spoolman",
            json={"spool_id": "12", "type": "updated"},
            headers={"X-API-Key": WEBHOOK_KEY},
        )
        assert r.status_code == 202, r.text
        row = await _done(r.json()["job_id"])
    assert row.payload["content_type"] == "qr_two_lines"
    assert row.payload["label_data"]["title"] == "TecBears Orange"


async def test_mixed_batch_on_38mm_names_the_layouts_that_cannot_print(hub: Hub) -> None:
    """#346: on a DK width only the spool label has, a cart with other labels is refused with a
    message that says so, naming the other layouts; nothing is queued."""
    hub.backend._loaded_tape_mm = 38
    items = [
        {"content_type": "spool_swatch", "lookup": {"app": "spoolman", "identifier": "12"}},
        {"content_type": "qr_two_lines", "lookup": {"app": "spoolman", "identifier": "12"}},
    ]
    async with hub.running() as (client, _):
        r = await client.post("/api/v1/print/ql-1/batch", json={"items": items})
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["error_code"] == "unsupported_tape"
    assert detail["error_message"] == (
        "Only the spool label prints on 38 mm tape. Remove the other labels from the cart or "
        "load 62 mm tape."
    )
    assert detail["error_detail"] == {"tape_mm": 38, "content_types": ["qr_two_lines"]}
    assert hub.backend.printed_images == []


async def test_render_check_on_38mm_flags_only_the_other_labels(hub: Hub) -> None:
    items = [
        {"content_type": "spool_swatch", "lookup": {"app": "spoolman", "identifier": "12"}},
        {"content_type": "qr_two_lines", "lookup": {"app": "spoolman", "identifier": "12"}},
    ]
    async with hub.running() as (client, _):
        r = await client.post("/api/v1/render/check", json={"tape_mm": 38, "items": items})
    assert r.status_code == 200, r.text
    first, second = r.json()["results"]
    assert (first["ok"], first["error_code"]) == (True, None)
    assert (second["ok"], second["error_code"]) == (False, "unsupported_tape")
    assert second["error_message"] == (
        "Only the spool label prints on 38 mm tape; this layout needs 62 mm tape."
    )
    assert second["error_detail"] == {"tape_mm": 38, "spool_label_only": True}
