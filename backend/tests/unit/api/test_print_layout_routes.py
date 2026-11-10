"""Layout options on POST /api/v1/print and POST /api/v1/render/preview (#258)."""

from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.api.routes.print import render_router, router
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_print, require_read
from app.printer_backends.exceptions import QrPayloadTooLongError, UnsupportedTapeError
from app.schemas.label_layout import LabelOrientation, QlLayoutPreset
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from PIL import Image

_DATA = {
    "primary_id": "ST00019",
    "title": "DOCKER1",
    "secondary": ["Dell OptiPlex 3070 Micro", "S/N 72104Z2"],
    "qr_payload": "https://example.invalid/hardware/19",
}


def _app(service: object) -> FastAPI:
    app = FastAPI()
    app.state.print_service = service
    app.state.print_queue = MagicMock()
    app.include_router(router)
    app.include_router(render_router)
    ctx = AuthContext(source="api-key", scope="admin", api_key_id=uuid4(), ip="127.0.0.1")
    for dep in (require_read, require_print):
        app.dependency_overrides[dep] = lambda _c=ctx: _c
    return app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def test_print_accepts_orientation_and_preset_per_job() -> None:
    service = AsyncMock()
    service.submit_print_job.return_value = "job-1"
    async with _client(_app(service)) as c:
        r = await c.post(
            "/api/v1/print",
            json={
                "content_type": "qr_three_lines",
                "data": _DATA,
                "options": {"orientation": "across", "layout_preset": "standard"},
            },
        )
    assert r.status_code == 202, r.text
    options = service.submit_print_job.await_args.args[0].options
    assert options.orientation is LabelOrientation.ACROSS
    assert options.layout_preset is QlLayoutPreset.STANDARD


async def test_print_rejects_an_unknown_orientation() -> None:
    async with _client(_app(AsyncMock())) as c:
        r = await c.post(
            "/api/v1/print",
            json={"content_type": "qr_only", "data": _DATA, "options": {"orientation": "up"}},
        )
    assert r.status_code == 422


async def test_print_maps_a_too_long_qr_payload_to_422() -> None:
    service = AsyncMock()
    service.submit_print_job.side_effect = QrPayloadTooLongError(length=80, max_bytes=53)
    async with _client(_app(service)) as c:
        r = await c.post("/api/v1/print", json={"content_type": "qr_only", "data": _DATA})
    assert r.status_code == 422
    body = r.json()
    assert body["error_code"] == "qr_payload_too_long"
    assert body["error_detail"] == {"length": 80, "max_bytes": 53}


async def test_print_maps_across_on_a_narrow_tape_to_409() -> None:
    service = AsyncMock()
    service.submit_print_job.side_effect = UnsupportedTapeError(tape_mm=12, orientation="across")
    async with _client(_app(service)) as c:
        r = await c.post("/api/v1/print", json={"content_type": "qr_only", "data": _DATA})
    assert r.status_code == 409
    assert r.json()["error_code"] == "unsupported_tape"


async def _preview(body: dict[str, object]) -> tuple[int, Image.Image | None, dict[str, object]]:
    async with _client(_app(AsyncMock())) as c:
        r = await c.post("/api/v1/render/preview", json=body)
    if r.headers.get("content-type") == "image/png":
        return r.status_code, Image.open(io.BytesIO(r.content)), {}
    return r.status_code, None, r.json()


async def test_preview_of_62mm_is_the_compact_across_label_by_default() -> None:
    status, image, _ = await _preview(
        {"content_type": "qr_three_lines", "data": _DATA, "tape_mm": 62}
    )
    assert status == 200
    assert image is not None and image.size == (696, 198)


async def test_preview_follows_preset_and_orientation() -> None:
    _, standard, _ = await _preview(
        {
            "content_type": "qr_three_lines",
            "data": _DATA,
            "tape_mm": 62,
            "orientation": "across",
            "layout_preset": "standard",
        }
    )
    _, along, _ = await _preview(
        {"content_type": "qr_three_lines", "data": _DATA, "tape_mm": 62, "orientation": "along"}
    )
    assert standard is not None and standard.size == (696, 307)
    assert along is not None and along.height == 696


async def test_preview_refuses_across_on_12mm_and_too_long_payloads() -> None:
    status, _, body = await _preview(
        {"content_type": "qr_only", "data": _DATA, "tape_mm": 12, "orientation": "across"}
    )
    assert (status, body["error_code"]) == (409, "unsupported_tape")
    long_data = {**_DATA, "qr_payload": "https://example.invalid/" + "a" * 60}
    status, _, body = await _preview({"content_type": "qr_only", "data": long_data, "tape_mm": 62})
    assert (status, body["error_code"]) == (422, "qr_payload_too_long")
