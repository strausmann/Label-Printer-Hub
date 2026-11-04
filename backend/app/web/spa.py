"""Serve the built web app (single page application) from the backend.

Decision D1: one process serves both the API and the UI, so there is no second
container and no proxy hop between them.

``mount_spa`` registers one catch-all GET route *after* every router. Anything
no other route matched is answered with ``index.html`` so client-side routes
survive a reload, except ``/api/...``, the interactive API docs and the OpenAPI
document, which keep their JSON 404. Requests for ``/assets/...`` that do not
exist are a real 404 as well: handing a browser HTML where it asked for a
script only hides the problem.

When ``dist_dir/index.html`` is missing the hub runs API-only: one warning is
logged and nothing is mounted (tests and the backend-only compose example rely
on that).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

IMMUTABLE = "public, max-age=31536000, immutable"
NO_CACHE = "no-cache"

# Paths owned by the API; never answered with the app shell.
_RESERVED_PREFIXES = ("api/", "docs", "redoc", "openapi.json")

# react-aria injects one fixed `<style>` (id react-aria-pressable-style, a touch-action rule) at
# runtime. It is allowed by its hash only, never by a blanket inline allowance.
# `src/build.test.ts` recomputes the
# hash from the built bundle, so a react-aria update that changes the text fails the build.
_REACT_ARIA_PRESSABLE_STYLE = "'sha256-38RhXrc7EdReTKsOm23ZPOCUgniTUUcjky8QOOrQx6o='"

SPA_CSP = (
    "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self'; "
    "img-src 'self' data: blob:; connect-src 'self'; style-src 'self' "
    + _REACT_ARIA_PRESSABLE_STYLE
    + "; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)
_SPA_SCOPE_KEY = "hub.spa_response"


def spa_index_path(app: FastAPI) -> Path | None:
    """Path of the mounted ``index.html`` or ``None`` in API-only mode."""
    index = getattr(app.state, "spa_index", None)
    return index if isinstance(index, Path) else None


def serve_index(request: Request) -> Response | None:
    """The app shell for ``request``, or ``None`` when no web app is mounted."""
    index = spa_index_path(request.app)
    if index is None:
        return None
    request.scope[_SPA_SCOPE_KEY] = True
    return FileResponse(index, media_type="text/html", headers={"Cache-Control": NO_CACHE})


def _is_reserved(path: str) -> bool:
    return any(path == p.rstrip("/") or path.startswith(p) for p in _RESERVED_PREFIXES)


# Old links (and the client route /jobs/$jobId) point a browser at the legacy JSON route.
_JOB_LINK = re.compile(r"^/jobs/[^/]+$")


class _BrowserJobLinks:
    """Hand a browser navigation to ``GET /jobs/<id>`` the app shell, before route auth.

    The client route ``/jobs/$jobId`` collides with the legacy JSON route of the same
    path. Negotiating inside that route runs after authentication, so an unauthenticated
    browser would get a JSON 401 instead of the app (which shows sign-in). Rewriting the
    path to ``/`` before routing lets the catch-all serve ``index.html``. API clients
    (no ``text/html`` in ``Accept``) keep the JSON route, auth included.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope["method"] == "GET"
            and _JOB_LINK.match(scope["path"])
            and any(b"text/html" in value for name, value in scope["headers"] if name == b"accept")
        ):
            scope = {**scope, "path": "/", "raw_path": b"/"}
        await self.app(scope, receive, send)


def mount_spa(app: FastAPI, dist_dir: Path) -> None:
    """Serve ``dist_dir`` (a Vite build) from ``app``; call after all routers (D1)."""
    index = dist_dir / "index.html"
    if not index.is_file():
        logger.warning("web app not found at %s - running API-only", dist_dir)
        app.state.spa_index = None
        return
    root = dist_dir.resolve()
    app.state.spa_index = index

    async def spa(request: Request) -> Response:
        full_path: str = request.path_params.get("full_path", "")
        if _is_reserved(full_path):
            raise HTTPException(status_code=404, detail="Not Found")
        if full_path:
            candidate = (root / full_path).resolve()
            if candidate.is_file() and candidate.is_relative_to(root):
                request.scope[_SPA_SCOPE_KEY] = True
                is_asset = candidate.is_relative_to(root / "assets")
                return FileResponse(
                    candidate,
                    headers={"Cache-Control": IMMUTABLE if is_asset else NO_CACHE},
                )
            if full_path.startswith("assets/"):
                raise HTTPException(status_code=404, detail="Not Found")
        response = serve_index(request)
        assert response is not None  # index existed at mount time
        return response

    app.add_route("/{full_path:path}", spa, methods=["GET"], include_in_schema=False)
    app.add_middleware(_BrowserJobLinks)


class _SecurityHeaders:
    """Pure ASGI middleware (BaseHTTPMiddleware would buffer the event stream)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers: list[tuple[bytes, bytes]] = list(message.get("headers", []))
                headers.append((b"x-content-type-options", b"nosniff"))
                headers.append((b"referrer-policy", b"same-origin"))
                if scope.get(_SPA_SCOPE_KEY):
                    headers.append((b"content-security-policy", SPA_CSP.encode()))
                    headers.append((b"permissions-policy", b"camera=(self)"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


def add_security_headers(app: FastAPI) -> None:
    """Add the security headers; the CSP only goes on responses the SPA mount served."""
    app.add_middleware(_SecurityHeaders)
