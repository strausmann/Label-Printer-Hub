"""Tests for ``read_bounded``: a request body is read at most up to its limit (#281, R-281-3)."""

from __future__ import annotations

from typing import Any

import pytest
from app.api.bounded_body import read_bounded
from starlette.requests import Request

CHUNK = 64 * 1024
MIB = 1024 * 1024


class _TooLargeError(Exception):
    pass


def _request(chunks: int, chunk_size: int, content_length: int | None) -> tuple[Request, list[int]]:
    consumed = [0]
    headers: list[tuple[bytes, bytes]] = []
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode()))
    scope: dict[str, Any] = {"type": "http", "method": "POST", "path": "/", "headers": headers}

    async def receive() -> dict[str, Any]:
        if consumed[0] >= chunks:
            return {"type": "http.request", "body": b"", "more_body": False}
        consumed[0] += 1
        return {
            "type": "http.request",
            "body": b"a" * chunk_size,
            "more_body": consumed[0] < chunks,
        }

    return Request(scope, receive), consumed


@pytest.mark.asyncio
async def test_declared_length_over_limit_raises_and_reads_nothing() -> None:
    request, consumed = _request(chunks=40, chunk_size=CHUNK, content_length=40 * CHUNK)
    with pytest.raises(_TooLargeError):
        await read_bounded(request, MIB, _TooLargeError)
    assert consumed[0] == 0


@pytest.mark.asyncio
async def test_chunked_body_stops_after_limit() -> None:
    request, consumed = _request(chunks=1000, chunk_size=CHUNK, content_length=None)
    with pytest.raises(_TooLargeError):
        await read_bounded(request, MIB, _TooLargeError)
    assert consumed[0] <= 17


@pytest.mark.asyncio
async def test_body_at_limit_is_returned() -> None:
    request, _ = _request(chunks=16, chunk_size=CHUNK, content_length=MIB)
    body = await read_bounded(request, MIB, _TooLargeError)
    assert len(body) == MIB


@pytest.mark.asyncio
async def test_understated_length_still_stops_after_limit() -> None:
    # A Content-Length that lies low must not let more than the limit through.
    request, consumed = _request(chunks=1000, chunk_size=CHUNK, content_length=10)
    with pytest.raises(_TooLargeError):
        await read_bounded(request, MIB, _TooLargeError)
    assert consumed[0] <= 17
