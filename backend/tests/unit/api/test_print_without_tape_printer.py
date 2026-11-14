# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""POST /api/v1/print on an install without a tape printer (fresh, or only IPP page printers)."""

from __future__ import annotations

from uuid import uuid4

from app.api.routes.print import router
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_print
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


async def test_post_print_without_print_service_is_503_with_error_shape() -> None:
    app = FastAPI()
    app.include_router(router)
    app.state.print_service = None
    ctx = AuthContext(source="api-key", scope="admin", api_key_id=uuid4(), ip="127.0.0.1")
    app.dependency_overrides[require_print] = lambda: ctx
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/v1/print",
            json={
                "content_type": "qr_two_lines",
                "data": {"title": "T", "primary_id": "P-1", "qr_payload": "https://e.x"},
            },
        )
    assert r.status_code == 503
    assert r.json() == {
        "error_code": "no_tape_printer",
        "error_message": "No tape printer is configured for label printing.",
    }
