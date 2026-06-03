"""Phase 1i Sub-Task A — Integration tests for GET /api/templates/{key}/preview.png."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_preview_png_returns_bitmap(api_client_with_seed: AsyncClient) -> None:
    """GET /api/templates/{key}/preview.png returnt 200 image/png mit PNG-Magic."""
    response = await api_client_with_seed.get(
        "/api/templates/hangar-furniture-12mm/preview.png",
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
    response = await api_client_with_seed.get("/api/templates/nonexistent/preview.png")
    assert response.status_code == 404
