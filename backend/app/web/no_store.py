# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""``Cache-Control: no-store`` on API responses (#160).

An authenticated API response (printer status, settings, an export download) must not be
kept by a shared cache between the hub and the browser, whatever the proxy's defaults are.
Every response under ``/api/v1/`` and ``/readiness`` that has no ``Cache-Control`` of its own
gets ``no-store``. A route that sets its own value keeps it: the event stream sends
``no-cache``, the web app and the API docs send theirs, and none of those paths is under
``/api/v1/`` apart from the stream.
"""

from __future__ import annotations

from typing import Final

from fastapi import FastAPI
from starlette.types import ASGIApp, Message, Receive, Scope, Send

NO_STORE: Final = b"no-store"
_PREFIXES: Final = ("/api/v1/",)
_EXACT: Final = ("/readiness",)


def needs_no_store(path: str) -> bool:
    """True for ``/api/v1/...`` and ``/readiness``, not for ``/api/v10`` or ``/readiness-x``."""
    return path in _EXACT or path.startswith(_PREFIXES)


class _NoStore:
    """Pure ASGI middleware (BaseHTTPMiddleware would buffer the event stream)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not needs_no_store(scope["path"]):
            await self.app(scope, receive, send)
            return

        async def send_with_no_store(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers: list[tuple[bytes, bytes]] = list(message.get("headers", []))
                if not any(name.lower() == b"cache-control" for name, _ in headers):
                    headers.append((b"cache-control", NO_STORE))
                    message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_no_store)


def add_no_store(app: FastAPI) -> None:
    app.add_middleware(_NoStore)
