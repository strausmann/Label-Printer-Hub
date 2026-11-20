# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""#398, finding 1: a large IPP answer is decoded in a worker thread, not on the event loop."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from app.printer_backends.ipp.client import DECODE_IN_THREAD_BYTES, IppClient
from app.printer_backends.ipp.codec import Attr, Group, Message, Tag, decode, encode

pytestmark = pytest.mark.anyio

URI = "ipp://printer.example.invalid/ipp/print"


def _answer(info_values: int) -> bytes:
    """A Get-Printer-Attributes answer with *info_values* 1000-character ``printer-info``
    values (about 1 KB each on the wire)."""
    ops = [
        Attr("attributes-charset", Tag.CHARSET, ["utf-8"]),
        Attr("attributes-natural-language", Tag.LANGUAGE, ["en"]),
    ]
    printer = [Attr("printer-info", Tag.TEXT, ["x" * 1000] * info_values)]
    return encode(Message((1, 1), 0, 1, [Group(Tag.OPERATION, ops), Group(Tag.PRINTER, printer)]))


class _Body(httpx.AsyncByteStream):
    """A streamed body (``content=`` is pre-read and cannot be streamed again)."""

    def __init__(self, body: bytes) -> None:
        self.body = body

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self.body


class _Spy:
    def __init__(self) -> None:
        self.calls: list[Any] = []
        self._real = asyncio.to_thread

    async def __call__(self, func: Any, /, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(func)
        return await self._real(func, *args, **kwargs)


async def _query(monkeypatch: pytest.MonkeyPatch, raw: bytes) -> tuple[_Spy, dict[str, Any]]:
    spy = _Spy()
    monkeypatch.setattr(asyncio, "to_thread", spy)  # the client calls asyncio.to_thread

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/ipp"}, stream=_Body(raw))

    async with IppClient(URI, transport=httpx.MockTransport(respond)) as client:
        attrs = await client.get_printer_attributes(["printer-info"])
    return spy, attrs


async def test_large_ipp_answer_decodes_in_a_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _answer(80)
    assert len(raw) > DECODE_IN_THREAD_BYTES
    spy, attrs = await _query(monkeypatch, raw)
    assert spy.calls == [decode]
    assert len(attrs["printer-info"]) == 80


async def test_small_ipp_answer_decodes_inline(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _answer(2)
    assert len(raw) <= DECODE_IN_THREAD_BYTES
    spy, attrs = await _query(monkeypatch, raw)
    assert spy.calls == []
    assert len(attrs["printer-info"]) == 2
