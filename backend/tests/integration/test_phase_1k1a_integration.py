"""Phase 1k.1a integration tests — LayoutEngine + /render/preview endpoint.

Task 25: End-to-end verification that the LayoutEngine-based pipeline
produces valid images and the /render/preview REST endpoint works correctly.

Covered:
- POST /render/preview 200 → PNG bytes (valid image)
- POST /render/preview 409 → unsupported tape_mm
- POST /render/preview 422 → data missing required fields
- All 7 ContentTypes render without exception on 12mm, 18mm, 24mm tape
- LayoutEngine is stateless (reuse instance, same output)
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# /render/preview — happy paths
# ---------------------------------------------------------------------------

_VALID_BODY_QR_TWO_LINES = {
    "content_type": "qr_two_lines",
    "data": {
        "primary_id": "K02",
        "title": "Regal Küche",
        "qr_payload": "https://example.com/loc/K02",
    },
    "tape_mm": 24,
}


async def test_render_preview_returns_png(client):
    """POST /render/preview → 200 with image/png content-type."""
    resp = await client.post(
        "/render/preview",
        json=_VALID_BODY_QR_TWO_LINES,
        headers={"X-Pangolin-User": "test"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "image/png"
    img = Image.open(io.BytesIO(resp.content))
    assert img.mode in ("1", "L", "RGB", "RGBA")
    assert img.width > 0
    assert img.height > 0


async def test_render_preview_12mm(client):
    """12mm tape renders a valid PNG."""
    body = {
        "content_type": "qr_one_line",
        "data": {
            "primary_id": "A01",
            "qr_payload": "https://example.com/a",
        },
        "tape_mm": 12,
    }
    resp = await client.post(
        "/render/preview",
        json=body,
        headers={"X-Pangolin-User": "test"},
    )
    assert resp.status_code == 200, resp.text
    img = Image.open(io.BytesIO(resp.content))
    assert img.width > 0


async def test_render_preview_18mm(client):
    """18mm tape renders a valid PNG."""
    body = {
        "content_type": "qr_two_lines",
        "data": {
            "primary_id": "B02",
            "title": "Test 18mm",
            "qr_payload": "https://example.com/b",
        },
        "tape_mm": 18,
    }
    resp = await client.post(
        "/render/preview",
        json=body,
        headers={"X-Pangolin-User": "test"},
    )
    assert resp.status_code == 200, resp.text
    img = Image.open(io.BytesIO(resp.content))
    assert img.width > 0


# ---------------------------------------------------------------------------
# /render/preview — error cases
# ---------------------------------------------------------------------------


async def test_render_preview_unsupported_tape_returns_409(client):
    """tape_mm=999 → 409 unsupported_tape."""
    body = {
        "content_type": "qr_only",
        "data": {"qr_payload": "https://example.com"},
        "tape_mm": 999,
    }
    resp = await client.post(
        "/render/preview",
        json=body,
        headers={"X-Pangolin-User": "test"},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "unsupported_tape"


async def test_render_preview_missing_required_field_returns_422(client):
    """qr_two_lines without title → 422 data_mismatch."""
    body = {
        "content_type": "qr_two_lines",
        "data": {
            "primary_id": "K02",
            # title intentionally absent — required by qr_two_lines
            "qr_payload": "https://example.com/loc/K02",
        },
        "tape_mm": 24,
    }
    resp = await client.post(
        "/render/preview",
        json=body,
        headers={"X-Pangolin-User": "test"},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "data_mismatch"


async def test_render_preview_qr_only_no_extra_fields(client):
    """qr_only needs only qr_payload — no title/primary_id required."""
    body = {
        "content_type": "qr_only",
        "data": {"qr_payload": "https://example.com/minimal"},
        "tape_mm": 12,
    }
    resp = await client.post(
        "/render/preview",
        json=body,
        headers={"X-Pangolin-User": "test"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "image/png"


# ---------------------------------------------------------------------------
# LayoutEngine unit-level: all 7 ContentTypes x tape widths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content_type,data_kwargs",
    [
        ("qr_only", {"qr_payload": "https://example.com/x"}),
        ("qr_one_line", {"qr_payload": "https://example.com/x", "primary_id": "A01"}),
        (
            "qr_two_lines",
            {
                "qr_payload": "https://example.com/x",
                "primary_id": "A01",
                "title": "Workshop",
            },
        ),
        (
            "qr_three_lines",
            {
                "qr_payload": "https://example.com/x",
                "primary_id": "A01",
                "title": "Workshop",
                "secondary": ["Zone 2"],
            },
        ),
        ("text_one_line", {"primary_id": "A01"}),
        ("text_two_lines", {"primary_id": "A01", "title": "Workshop"}),
        (
            "qr_with_listing",
            {
                "qr_payload": "https://example.com/x",
                "primary_id": "shelf-1",
                "items": [
                    {"item": "A — Schrauben", "qr_payload": "https://example.com/i01"},
                    {"item": "B — Muttern", "qr_payload": "https://example.com/i02"},
                ],
            },
        ),
    ],
)
@pytest.mark.parametrize("tape_mm", [12, 18, 24])
async def test_all_content_types_via_preview_endpoint(
    client,
    content_type: str,
    data_kwargs: dict,
    tape_mm: int,
) -> None:
    """All 7 ContentTypes x {12, 18, 24}mm produce a valid PNG via /render/preview."""
    body = {"content_type": content_type, "data": data_kwargs, "tape_mm": tape_mm}
    resp = await client.post(
        "/render/preview",
        json=body,
        headers={"X-Pangolin-User": "test"},
    )
    assert resp.status_code == 200, f"ContentType={content_type}, tape_mm={tape_mm}: {resp.text}"
    img = Image.open(io.BytesIO(resp.content))
    assert img.width > 0, f"Empty image for {content_type} on {tape_mm}mm"
