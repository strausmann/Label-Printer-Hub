# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Lookup answers are bounded in size and the whole lookup in time (#211, findings 3-4)."""

from __future__ import annotations

import asyncio
import logging
import tracemalloc
import zlib
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from app.api.routes.lookup import _answered
from app.integrations.grocy.plugin import GrocyPlugin
from app.integrations.live_config import (
    MAX_LOOKUP_RESPONSE_BYTES,
    LookupResponseTooLargeError,
    StoreBoundPlugin,
    read_json_bounded,
)
from app.integrations.snipeit.plugin import SnipeITPlugin
from app.integrations.spoolman.plugin import SpoolmanPlugin
from app.schemas.grocy_object import GrocyBatteryResult, GrocyChoreResult
from app.schemas.label_data import LabelData
from app.services import lookup_service
from app.services.lookup_service import AppLookupService, LookupFailedError
from fastapi import HTTPException

from tests.unit.integrations._bound import bound


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LABELYARD_SNIPEIT_URL", "https://snipe-it.example")
    monkeypatch.setenv("LABELYARD_SNIPEIT_API_KEY", "test-key")
    monkeypatch.setenv("LABELYARD_GROCY_URL", "https://grocy.example")
    monkeypatch.setenv("LABELYARD_GROCY_API_KEY", "grocy-key")
    monkeypatch.setenv("LABELYARD_SPOOLMAN_URL", "https://spoolman.example")
    from app.config import get_settings

    get_settings.cache_clear()


def _serve(plugin: StoreBoundPlugin, handler: Callable[[httpx.Request], httpx.Response]) -> None:
    plugin._slot.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _chunks(total: int, step: int = 65_536) -> AsyncIterator[bytes]:
    """``total`` bytes of filler in several chunks; an async body carries no Content-Length."""
    sent = 0
    while sent < total:
        n = min(step, total - sent)
        yield b" " * n
        sent += n


def _json_of_size(total: int) -> AsyncIterator[bytes]:
    async def gen() -> AsyncIterator[bytes]:
        yield b'{"id": 1, "name": "x"}'
        async for chunk in _chunks(total - len(b'{"id": 1, "name": "x"}')):
            yield chunk

    return gen()


_CASES: list[tuple[type[StoreBoundPlugin], str]] = [
    (SnipeITPlugin, "T-1"),
    (GrocyPlugin, "42"),
    (SpoolmanPlugin, "7"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("plugin_cls", "identifier"), _CASES, ids=lambda v: str(v))
async def test_lookup_answer_over_one_mib_maps_to_integration_lookup_failed(
    plugin_cls: type[StoreBoundPlugin], identifier: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_json_of_size(MAX_LOOKUP_RESPONSE_BYTES + 1))

    plugin = bound(plugin_cls)
    _serve(plugin, handler)
    monkeypatch.setattr(
        "app.integrations.registry.IntegrationRegistry.get", classmethod(lambda _c, _n: plugin)
    )
    # Through the service and the route's error mapping: the 502 the API answers.
    with pytest.raises(HTTPException) as info:
        await _answered(AppLookupService().lookup(plugin.name, identifier))
    assert info.value.status_code == 502
    assert info.value.detail["error_code"] == "integration_lookup_failed"  # type: ignore[index]
    assert issubclass(LookupResponseTooLargeError, LookupFailedError)


@pytest.mark.asyncio
async def test_answer_of_exactly_one_mib_is_still_read() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_json_of_size(MAX_LOOKUP_RESPONSE_BYTES))

    plugin = bound(SpoolmanPlugin)
    _serve(plugin, handler)
    label = await plugin.lookup("7")
    assert label.primary_id == "#1"


@pytest.mark.asyncio
async def test_declared_oversize_is_refused_before_the_body_is_read() -> None:
    read = 0

    async def body() -> AsyncIterator[bytes]:
        nonlocal read
        for _ in range(64):
            read += 1
            yield b" " * 65_536

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-length": str(MAX_LOOKUP_RESPONSE_BYTES * 4)}, content=body()
        )

    plugin = bound(SpoolmanPlugin)
    _serve(plugin, handler)
    with pytest.raises(LookupResponseTooLargeError):
        await plugin.lookup("7")
    assert read == 0


def _gzip_bomb(inflated: int) -> bytes:
    """A gzip stream that inflates to ``inflated`` zero bytes (about 0.1 % of that on the wire)."""
    packer = zlib.compressobj(9, zlib.DEFLATED, 31)
    out = bytearray()
    block = b"\0" * (1 << 20)
    for _ in range(inflated >> 20):
        out += packer.compress(block)
    out += packer.flush()
    return bytes(out)


@pytest.mark.asyncio
@pytest.mark.parametrize(("plugin_cls", "identifier"), _CASES, ids=lambda v: str(v))
async def test_compressed_answer_is_refused_without_inflating_it(
    plugin_cls: type[StoreBoundPlugin], identifier: str
) -> None:
    """A 64 KiB gzip chunk inflates to ~64 MiB in one httpx decode call, so the 1 MiB limit
    cannot be enforced on decoded bytes: lookups ask for identity and refuse anything else."""
    bomb = _gzip_bomb(100 << 20)
    assert len(bomb) < MAX_LOOKUP_RESPONSE_BYTES  # small on the wire, huge when inflated
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("accept-encoding", ""))

        # A stream, not bytes: httpx.Response(content=...) would inflate it right here.
        async def wire() -> AsyncIterator[bytes]:
            for i in range(0, len(bomb), 65_536):
                yield bomb[i : i + 65_536]

        return httpx.Response(200, headers={"content-encoding": "gzip"}, content=wire())

    plugin = bound(plugin_cls)
    _serve(plugin, handler)
    tracemalloc.start()
    try:
        with pytest.raises(LookupFailedError):
            await plugin.lookup(identifier)  # type: ignore[attr-defined]
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert seen
    assert set(seen) == {"identity"}
    assert peak < 4 << 20, f"peak allocation {peak} bytes: the answer was inflated"


@pytest.mark.asyncio
async def test_read_json_bounded_refuses_a_read_response_over_the_limit() -> None:
    response = httpx.Response(200, content=b" " * (MAX_LOOKUP_RESPONSE_BYTES + 1))
    with pytest.raises(LookupResponseTooLargeError):
        await read_json_bounded(response)


@pytest.mark.asyncio
async def test_too_large_error_and_log_do_not_carry_the_upstream(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_json_of_size(MAX_LOOKUP_RESPONSE_BYTES + 1))

    plugin = bound(SpoolmanPlugin)
    _serve(plugin, handler)
    with caplog.at_level(logging.DEBUG), pytest.raises(LookupResponseTooLargeError) as info:
        await plugin.lookup("7")
    assert "spoolman.example" not in str(info.value)
    ours = " ".join(r.getMessage() for r in caplog.records if r.name.startswith("app"))
    assert "spoolman.example" not in ours


@pytest.mark.asyncio
@pytest.mark.parametrize(("plugin_cls", "identifier"), _CASES, ids=lambda v: str(v))
async def test_network_error_still_maps_to_integration_lookup_failed(
    plugin_cls: type[StoreBoundPlugin], identifier: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    plugin = bound(plugin_cls)
    _serve(plugin, handler)
    monkeypatch.setattr(
        "app.integrations.registry.IntegrationRegistry.get", classmethod(lambda _c, _n: plugin)
    )
    with pytest.raises(LookupFailedError):
        await AppLookupService().lookup(plugin.name, identifier)


# ---------------------------------------------------------------------------
# Deadline over the whole lookup
# ---------------------------------------------------------------------------


class _SlowGrocy:
    """Makes three sequential upstream calls of 0.15 s each, like a lookup with follow-ups."""

    name = "grocy"

    def __init__(self) -> None:
        self.started = 0
        self.finished = 0

    async def _calls(self) -> None:
        for _ in range(3):
            self.started += 1
            await asyncio.sleep(0.15)
            self.finished += 1

    async def lookup(self, identifier: str) -> LabelData:
        await self._calls()
        raise AssertionError("the deadline must have cut the lookup")

    async def battery(self, battery_id: str) -> GrocyBatteryResult:
        await self._calls()
        raise AssertionError("the deadline must have cut the lookup")

    async def chore(self, chore_id: str) -> GrocyChoreResult:
        await self._calls()
        raise AssertionError("the deadline must have cut the lookup")


def _entry(service: AppLookupService, which: str) -> Any:
    return {
        "lookup": lambda: service.lookup("grocy", "1"),
        "battery": lambda: service.grocy_battery("1"),
        "chore": lambda: service.grocy_chore("1"),
    }[which]()


@pytest.mark.asyncio
@pytest.mark.parametrize("entry_point", ["lookup", "battery", "chore"])
async def test_lookup_deadline_covers_follow_up_calls(
    entry_point: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fake = _SlowGrocy()
    monkeypatch.setattr(lookup_service, "LOOKUP_DEADLINE_S", 0.2)
    monkeypatch.setattr(
        "app.integrations.registry.IntegrationRegistry.get", classmethod(lambda _c, _n: fake)
    )
    with caplog.at_level(logging.DEBUG), pytest.raises(LookupFailedError):
        await _entry(AppLookupService(), entry_point)
    # Cut during the second call: the first finished, the third never started. A timeout per
    # call (0.15 s each, all inside 0.2 s) would let all three finish.
    assert (fake.started, fake.finished) == (2, 1)
    assert "TimeoutError" not in caplog.text


def test_lookup_deadline_default_is_fifteen_seconds() -> None:
    assert lookup_service.LOOKUP_DEADLINE_S == 15.0
