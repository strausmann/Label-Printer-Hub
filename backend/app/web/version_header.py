# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Report the running hub version on every API response (#288).

A browser tab that was opened before an update keeps running the old web app against the new
server. The web app compares this header with the version it was built for and, on a mismatch,
offers a reload: one click loads the new version, nothing reloads by itself. Only ``/api/...``
responses carry it: static files and the app shell are cached by browsers and proxies, where a
stale copy would report a wrong version.
"""

from __future__ import annotations

from typing import Final

from fastapi import FastAPI
from starlette.types import ASGIApp, Message, Receive, Scope, Send

VERSION_HEADER: Final = "X-Hub-Version"


def is_api_path(path: str) -> bool:
    """True for ``/api`` and everything below it, but not for ``/apix``."""
    return path == "/api" or path.startswith("/api/")


class _VersionHeader:
    """Pure ASGI middleware (BaseHTTPMiddleware would buffer the event stream)."""

    def __init__(self, app: ASGIApp, version: str) -> None:
        self.app = app
        self._value = version.encode("latin-1", "replace")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not is_api_path(scope["path"]):
            await self.app(scope, receive, send)
            return

        async def send_with_version(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers: list[tuple[bytes, bytes]] = list(message.get("headers", []))
                headers.append((VERSION_HEADER.lower().encode(), self._value))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_version)


def add_version_header(app: FastAPI, version: str) -> None:
    app.add_middleware(_VersionHeader, version=version)
