"""Phase 1i Sub-Task A+D — Integration tests for preview endpoints.

A: GET /api/templates/{key}/preview-png
D: GET /api/templates/{key}/preview-svg
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_preview_png_returns_bitmap(api_client_with_seed: AsyncClient) -> None:
    """GET /api/templates/{key}/preview.png returnt 200 image/png mit PNG-Magic."""
    response = await api_client_with_seed.get(
        "/api/templates/hangar-furniture-12mm/preview-png",
        params={
            "primary_id": "HH-AK-KX10-F0101",
            "title": "Kallax 4x4 Fach S1 R1",
            "qr_payload": "https://hangar.example/loc/HH-AK-KX10-F0101",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.anyio
async def test_preview_png_unknown_template_404(api_client_with_seed: AsyncClient) -> None:
    response = await api_client_with_seed.get("/api/templates/nonexistent/preview-png")
    assert response.status_code == 404


@pytest.mark.anyio
async def test_preview_svg_returns_svg(api_client_with_seed: AsyncClient) -> None:
    """GET /api/templates/{key}/preview-svg returnt 200 image/svg+xml."""
    response = await api_client_with_seed.get(
        "/api/templates/hangar-furniture-12mm/preview-svg",
        params={"primary_id": "X", "title": "Y", "qr_payload": "Z"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert response.content.startswith(b"<?xml") or response.content.startswith(b"<svg")


@pytest.mark.anyio
async def test_preview_svg_etag_seed_template(api_client_with_seed: AsyncClient) -> None:
    """ETag-Caching: zweiter Request mit If-None-Match gibt 304 zurück."""
    r1 = await api_client_with_seed.get("/api/templates/hangar-furniture-12mm/preview-svg")
    assert r1.status_code == 200
    assert "ETag" in r1.headers
    r2 = await api_client_with_seed.get(
        "/api/templates/hangar-furniture-12mm/preview-svg",
        headers={"If-None-Match": r1.headers["ETag"]},
    )
    assert r2.status_code == 304
