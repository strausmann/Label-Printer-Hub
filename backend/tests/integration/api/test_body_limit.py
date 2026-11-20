# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The global body limit inside the real app (#164).

The limit sits in front of authentication, so an oversized body is a 413 for a caller with no
credentials, not a 401. The routes with their own, smaller limits keep them, and nothing that
carries no body is touched.
"""

from __future__ import annotations

import json

import pytest

from tests.integration.api.test_auth_session import _insert_key
from tests.integration.api.test_events_v1 import (
    STREAM_PATH,
    _connected,
    _key_header,
    _open,
    hub_app,  # noqa: F401  (fixture)
)

pytestmark = pytest.mark.asyncio

OVER = 2_097_153
TOO_LARGE_CODE = "body_too_large"


async def test_oversized_batch_is_413_not_401(hub_app) -> None:  # noqa: F811
    _, client = hub_app
    response = await client.post(
        "/api/v1/print/x/batch",
        headers={"Content-Length": str(OVER), "Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["detail"]["error_code"] == TOO_LARGE_CODE


async def test_chunked_oversized_body_is_413_not_401(hub_app) -> None:  # noqa: F811
    _, client = hub_app

    async def body():
        for _ in range(48):
            yield b" " * 65_536

    response = await client.post(
        "/api/v1/print/x/batch", content=body(), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413
    assert response.json()["detail"]["error_code"] == TOO_LARGE_CODE


async def test_one_mib_grocy_body_passes_the_global_limit(hub_app) -> None:  # noqa: F811
    _, client = hub_app
    body = json.dumps({"product": "x", "pad": "a" * (1_048_576 - 40)}).encode()
    response = await client.post(
        "/api/v1/webhook/grocy/label", content=body, headers={"Content-Type": "application/json"}
    )
    # The route's own answer: unauthenticated, so 401 from its token check, not 413.
    assert response.status_code == 401


async def test_every_post_route_is_covered(hub_app) -> None:  # noqa: F811
    """Not only the batch route: a sample of body-taking routes of different shapes."""
    app, client = hub_app
    paths = [
        (method.upper(), path)
        for path, item in app._app.openapi()["paths"].items()
        for method in item
        if method in {"post", "put", "patch", "delete"}
    ]
    assert len(paths) > 20  # the sample is real, not an empty loop
    for method, path in paths:
        url = path.replace("{", "x").replace("}", "")  # path params -> any value
        response = await client.request(
            method, url, headers={"Content-Length": str(OVER), "Content-Type": "application/json"}
        )
        assert response.status_code == 413, (method, path, response.status_code)


async def test_sse_stream_unaffected(hub_app) -> None:  # noqa: F811
    app, _ = hub_app
    key, _ = await _insert_key(["admin"])
    stream = await _open(app, _key_header(key))
    try:
        await _connected(stream)
    finally:
        await stream.close()
    assert STREAM_PATH == "/api/v1/events"


async def test_healthz_unaffected(hub_app) -> None:  # noqa: F811
    _, client = hub_app
    response = await client.get("/healthz")
    assert response.status_code == 200
