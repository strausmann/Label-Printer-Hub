from __future__ import annotations

import asyncio

import pytest
from app.printer_backends.exceptions import (
    PrinterOfflineError,
    StatusQueryFailedError,
)
from app.printer_backends.status_query import (
    ESC_I_S_REQUEST,
    parse_status_reply,
    query_status_over_socket,
)
from app.services.status_block import MediaType


def _good_reply(*, tape_mm: int = 24, err1: int = 0x00, err2: int = 0x00) -> bytes:
    """Build a valid 32-byte ESC i S reply with the given errors + tape width."""
    reply = bytearray(32)
    reply[0] = 0x80  # head mark
    reply[1] = 0x20  # size = 32
    reply[2] = ord("B")  # brand
    reply[8] = err1
    reply[9] = err2
    reply[10] = tape_mm
    reply[11] = 0x01  # laminated
    return bytes(reply)


def test_esc_i_s_request_bytes() -> None:
    assert ESC_I_S_REQUEST == b"\x1bi\x53"
    assert len(ESC_I_S_REQUEST) == 3


def test_parse_reply_happy_path() -> None:
    sb = parse_status_reply(_good_reply(tape_mm=24))
    assert sb.loaded_tape_mm == 24
    assert sb.media_type == MediaType.LAMINATED
    assert sb.tape_empty is False
    assert sb.cover_open is False


def test_parse_reply_tape_empty_flag() -> None:
    sb = parse_status_reply(_good_reply(err1=0x01))  # bit 0 = no media
    assert sb.tape_empty is True


def test_parse_reply_cover_open_flag() -> None:
    sb = parse_status_reply(_good_reply(err2=0x10))  # bit 4 = cover open
    assert sb.cover_open is True


def test_parse_reply_wrong_length_raises() -> None:
    with pytest.raises(StatusQueryFailedError):
        parse_status_reply(b"\x00" * 16)


def test_parse_reply_bad_head_marker_raises() -> None:
    reply = bytearray(32)
    reply[0] = 0xFF  # wrong head mark
    with pytest.raises(StatusQueryFailedError):
        parse_status_reply(bytes(reply))


async def test_query_status_over_socket_uses_open_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeReader:
        async def readexactly(self, n: int) -> bytes:
            captured["read_n"] = n
            return _good_reply(tape_mm=24)

    class FakeWriter:
        def write(self, data: bytes) -> None:
            captured["wrote"] = data

        async def drain(self) -> None:
            captured["drained"] = True

        def close(self) -> None:
            captured["closed"] = True

        async def wait_closed(self) -> None:
            captured["wait_closed"] = True

    async def fake_open_connection(host: str, port: int):
        captured["host"] = host
        captured["port"] = port
        return FakeReader(), FakeWriter()

    monkeypatch.setattr("asyncio.open_connection", fake_open_connection)
    sb = await query_status_over_socket("1.2.3.4", 9100, timeout_s=1.0)
    assert captured["host"] == "1.2.3.4"
    assert captured["port"] == 9100
    assert captured["wrote"] == ESC_I_S_REQUEST
    assert captured["drained"] is True
    assert captured["closed"] is True
    assert captured["wait_closed"] is True
    assert captured["read_n"] == 32
    assert sb.loaded_tape_mm == 24


async def test_query_status_offline_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_open_connection(*_a, **_kw):
        raise ConnectionRefusedError("nope")

    monkeypatch.setattr("asyncio.open_connection", fake_open_connection)
    with pytest.raises(PrinterOfflineError):
        await query_status_over_socket("1.2.3.4", 9100, timeout_s=0.1)


async def test_query_status_timeout_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_open_connection(*_a, **_kw):
        await asyncio.sleep(10)
        raise AssertionError("unreachable")

    monkeypatch.setattr("asyncio.open_connection", fake_open_connection)
    with pytest.raises(PrinterOfflineError):
        await query_status_over_socket("1.2.3.4", 9100, timeout_s=0.01)
