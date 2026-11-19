# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The ``no-store`` middleware on a small app (#160). The full app is in
``tests/integration/api/test_no_store.py``."""

from __future__ import annotations

import httpx
from app.web.no_store import add_no_store
from fastapi import FastAPI, Response


def _client() -> httpx.AsyncClient:
    app = FastAPI()

    @app.get("/api/v1/thing")
    async def thing() -> dict[str, int]:
        return {"a": 1}

    @app.get("/api/v1/stream")
    async def stream(response: Response) -> dict[str, int]:
        response.headers["Cache-Control"] = "no-cache"
        return {"a": 1}

    @app.get("/readiness")
    async def readiness() -> dict[str, str]:
        return {"status": "ready"}

    @app.get("/")
    async def index() -> dict[str, str]:
        return {"app": "shell"}

    @app.get("/api/v10/other")
    async def lookalike() -> dict[str, str]:
        return {"x": "y"}

    add_no_store(app)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_api_paths_get_no_store() -> None:
    async with _client() as client:
        assert (await client.get("/api/v1/thing")).headers["cache-control"] == "no-store"
        assert (await client.get("/readiness")).headers["cache-control"] == "no-store"
        # An error answer of the API path is covered too.
        assert (await client.get("/api/v1/missing")).headers["cache-control"] == "no-store"


async def test_an_existing_cache_control_is_kept() -> None:
    async with _client() as client:
        resp = await client.get("/api/v1/stream")
    assert resp.headers.get_list("cache-control") == ["no-cache"]


async def test_other_paths_untouched() -> None:
    async with _client() as client:
        for path in ("/", "/api/v10/other"):
            assert "cache-control" not in (await client.get(path)).headers
