# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The global request body limit (#164): a pure ASGI middleware around a two-route mini app.

The tests drive the middleware with raw ASGI messages, so they see what the app's ``receive``
is asked for and how many chunks a client was able to push.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from app.api.body_limit import MAX_REQUEST_BODY_BYTES, BodyLimitMiddleware
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

pytestmark = pytest.mark.asyncio

CHUNK = 64 * 1024
LIMIT = MAX_REQUEST_BODY_BYTES
TOO_LARGE = {
    "detail": {
        "error_code": "body_too_large",
        "error_message": "The request body is larger than 2 MiB.",
    }
}


class _Probe:
    """Counts what the inner app did."""

    def __init__(self) -> None:
        self.app_calls = 0
        self.receive_calls = 0
        self.bytes_read = 0


def _make(probe: _Probe) -> BodyLimitMiddleware:
    async def echo(request: Request) -> PlainTextResponse:
        probe.app_calls += 1
        total = 0
        async for chunk in request.stream():
            probe.receive_calls += 1
            total += len(chunk)
        probe.bytes_read = total
        return PlainTextResponse(str(total))

    async def ping(request: Request) -> PlainTextResponse:
        probe.app_calls += 1
        return PlainTextResponse("pong")

    inner = Starlette(routes=[Route("/echo", echo, methods=["POST"]), Route("/ping", ping)])
    return BodyLimitMiddleware(inner)


def _client(app: BodyLimitMiddleware) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_declared_length_over_limit_is_413_before_the_app() -> None:
    probe = _Probe()
    async with _client(_make(probe)) as client:
        # The header alone is enough: no body is ever sent, the app must not even start.
        response = await client.post("/echo", headers={"content-length": str(LIMIT + 1)})
    assert response.status_code == 413
    assert response.json() == TOO_LARGE
    assert probe.app_calls == 0
    assert probe.receive_calls == 0


async def test_chunked_body_stops_at_the_limit() -> None:
    probe = _Probe()
    yielded = 0
    total = 40 * 1024 * 1024

    async def body() -> AsyncIterator[bytes]:
        nonlocal yielded
        for _ in range(total // CHUNK):
            yielded += 1
            yield b"x" * CHUNK

    async with _client(_make(probe)) as client:
        response = await client.post("/echo", content=body())  # no Content-Length: chunked
    assert response.status_code == 413
    assert response.json() == TOO_LARGE
    # 2 MiB = 32 chunks; the 33rd takes the total past the limit and is the last one read.
    assert yielded <= 33
    assert probe.bytes_read <= LIMIT


async def test_exactly_the_limit_passes() -> None:
    probe = _Probe()
    async with _client(_make(probe)) as client:
        declared = await client.post("/echo", content=b"x" * LIMIT)
        chunked = await client.post("/echo", content=_chunks(LIMIT))
    assert declared.status_code == 200
    assert declared.text == str(LIMIT)
    assert chunked.status_code == 200
    assert chunked.text == str(LIMIT)


async def test_one_byte_over_in_chunks_is_413() -> None:
    probe = _Probe()
    async with _client(_make(probe)) as client:
        response = await client.post("/echo", content=_chunks(LIMIT + 1))
    assert response.status_code == 413


async def test_get_and_non_http_scopes_pass_through() -> None:
    probe = _Probe()
    async with _client(_make(probe)) as client:
        response = await client.get("/ping")
    assert response.status_code == 200
    assert response.text == "pong"

    seen: list[str] = []

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        seen.append(scope["type"])

    middleware = BodyLimitMiddleware(inner)
    for kind in ("lifespan", "websocket"):
        await middleware({"type": kind}, None, None)  # type: ignore[arg-type]
    assert seen == ["lifespan", "websocket"]


async def test_the_answer_is_valid_json_with_a_json_content_type() -> None:
    probe = _Probe()
    async with _client(_make(probe)) as client:
        response = await client.post("/echo", headers={"content-length": str(LIMIT + 1)})
    assert response.headers["content-type"].startswith("application/json")
    assert json.loads(response.content) == TOO_LARGE


async def _chunks(total: int) -> AsyncIterator[bytes]:
    sent = 0
    while sent < total:
        piece = min(CHUNK, total - sent)
        sent += piece
        yield b"x" * piece


async def test_a_non_ascii_digit_content_length_is_ignored_not_a_crash() -> None:
    """``"²".isdigit()`` is true but ``int("²")`` raises; the header is just not a length."""
    from app.api.body_limit import _declared_length

    assert _declared_length({"headers": [(b"content-length", b"\xb2")]}) is None
    assert _declared_length({"headers": [(b"content-length", b"\xd9\xa1")]}) is None  # Arabic-Indic
    assert _declared_length({"headers": [(b"content-length", b" 42 ")]}) == 42

    probe = _Probe()
    async with _client(_make(probe)) as client:
        response = await client.get("/ping", headers={"content-length": "0"})
    assert response.status_code == 200
