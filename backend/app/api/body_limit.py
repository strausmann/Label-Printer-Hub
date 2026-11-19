# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""A global request body limit (#164).

Before this middleware only the routes that read a raw body bounded it
(:func:`app.api.bounded_body.read_bounded`); a JSON route parsed whatever a client sent, so a
body of any size was buffered before authentication ran. The limit sits in front of every
route, authentication included.

Pure ASGI, like the access log, and it buffers nothing:

- a declared ``Content-Length`` above the limit is refused before the app starts;
- a body without it (chunked) is counted chunk by chunk and refused at the chunk that takes
  the total past the limit. The refusal is written from inside ``receive``: whatever the app
  does with the failed read (FastAPI turns a read error into a 422) its answer is dropped
  and the client gets the 413.

Only ``http`` scopes are looked at; a GET without a body, the event stream and the health
probes see no change. The routes that read a body keep their own, smaller limits.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final

from starlette.types import ASGIApp, Message, Receive, Scope, Send

if TYPE_CHECKING:
    from fastapi import FastAPI

MAX_REQUEST_BODY_BYTES: Final = 2_097_152  # 2 MiB; above the Grocy route's 1 MiB

_PAYLOAD: Final = json.dumps(
    {
        "detail": {
            "error_code": "body_too_large",
            "error_message": "The request body is larger than 2 MiB.",
        }
    }
).encode()
_HEADERS: Final = [
    (b"content-type", b"application/json"),
    (b"content-length", str(len(_PAYLOAD)).encode()),
    (b"connection", b"close"),
]


class BodyLimitMiddleware:
    """Refuse a request body above ``limit`` bytes with 413 ``body_too_large``."""

    def __init__(self, app: ASGIApp, limit: int = MAX_REQUEST_BODY_BYTES) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = _declared_length(scope)
        if declared is not None and declared > self.limit:
            await _refuse(send)
            return

        received = 0
        started = False  # the app has begun its own answer
        refused = False  # we have written the 413 (or cannot: the app was first)

        async def counting_receive() -> Message:
            nonlocal received, refused
            if refused:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.limit:
                    refused = True
                    if not started:
                        await _refuse(send)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if refused and not started:
                return  # the 413 is out; drop what the app says about the failed read
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except Exception:
            # The app failed on the disconnect we handed it after the limit. The client has
            # its 413; anything else is a real error.
            if not refused:
                raise


def _declared_length(scope: Scope) -> int | None:
    for name, value in scope["headers"]:
        if name == b"content-length":
            text = value.decode("latin-1").strip()
            # ASCII digits only: str.isdigit() also accepts e.g. "²", which int() rejects.
            return int(text) if text.isascii() and text.isdigit() else None
    return None


async def _refuse(send: Send) -> None:
    await send({"type": "http.response.start", "status": 413, "headers": _HEADERS})
    await send({"type": "http.response.body", "body": _PAYLOAD})


def install_body_limit(app: FastAPI) -> None:
    """Add the limit as a middleware; call it before the access log so the 413 is logged."""
    app.add_middleware(BodyLimitMiddleware)
