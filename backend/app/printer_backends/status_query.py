"""Brother PT-Series status query — ESC i S over a raw asyncio socket.

Sends a 3-byte command (0x1B 0x69 0x53) and parses the 32-byte reply via
the existing StatusBlockParser. The ptouch library does not expose this —
only an internal _cmd_print_information send command exists.

See backend/docs/brother-status-block.md for the wire format.
"""

from __future__ import annotations

import asyncio
import contextlib

from app.printer_backends.exceptions import (
    PrinterOfflineError,
    StatusQueryFailedError,
)
from app.services.status_block import StatusBlock, StatusBlockError, StatusBlockParser

ESC_I_S_REQUEST: bytes = b"\x1bi\x53"
_STATUS_REPLY_LEN: int = 32
_HEAD_MARK: int = 0x80
_BRAND_BYTE: int = ord("B")


def parse_status_reply(reply: bytes) -> StatusBlock:
    """Parse the 32-byte ESC i S response. Raise StatusQueryFailedError if malformed."""
    if len(reply) != _STATUS_REPLY_LEN:
        raise StatusQueryFailedError(f"Expected {_STATUS_REPLY_LEN} bytes, got {len(reply)}")
    if reply[0] != _HEAD_MARK or reply[2] != _BRAND_BYTE:
        raise StatusQueryFailedError(f"Bad reply header: head={reply[0]:#x} brand={reply[2]:#x}")
    try:
        return StatusBlockParser.parse(reply)
    except StatusBlockError as exc:
        raise StatusQueryFailedError(str(exc)) from exc


async def query_status_over_socket(
    host: str,
    port: int = 9100,
    *,
    timeout_s: float = 5.0,
) -> StatusBlock:
    """Open a TCP connection, write ESC i S, read 32 bytes, parse."""
    try:
        async with asyncio.timeout(timeout_s):
            reader, writer = await asyncio.open_connection(host, port)
    except (OSError, TimeoutError) as exc:
        raise PrinterOfflineError(f"cannot reach {host}:{port}: {exc}") from exc

    try:
        writer.write(ESC_I_S_REQUEST)
        await writer.drain()
        try:
            async with asyncio.timeout(timeout_s):
                reply = await reader.readexactly(_STATUS_REPLY_LEN)
        except (OSError, TimeoutError, asyncio.IncompleteReadError) as exc:
            raise PrinterOfflineError(f"status read failed: {exc}") from exc
    finally:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()

    return parse_status_reply(reply)
