# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Read a request body without ever buffering more than a limit (#281, R-281-3).

The app has no global body limit, so ``Request.body()`` would buffer anything a client
sends. Every route that reads a raw body uses :func:`read_bounded` instead.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Request


async def read_bounded(request: Request, limit: int, too_large: Callable[[], Exception]) -> bytes:
    """Return the body, or raise ``too_large()`` as soon as it exceeds ``limit`` bytes.

    A declared ``Content-Length`` above the limit is refused before a byte is read;
    otherwise reading stops at the first chunk that takes the total past the limit, so
    at most the limit plus one chunk is held in memory.
    """
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise too_large()
    buffer = bytearray()
    async for chunk in request.stream():
        buffer.extend(chunk)
        if len(buffer) > limit:
            raise too_large()
    return bytes(buffer)
