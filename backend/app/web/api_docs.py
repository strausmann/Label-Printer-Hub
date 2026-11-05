"""The interactive API reference at ``/docs``, rendered by Scalar and served by the hub.

Issue #171: FastAPI's default Swagger UI and ReDoc load their scripts from a CDN.
The hub runs on private networks, often without internet access, so ``/docs`` serves
the Scalar standalone bundle (``@scalar/api-reference``, MIT) from the hub itself.

The bundle is copied into the web app's build output (``<web_dist_dir>/scalar/``) by
the frontend build, so the single image ships it and the pinned npm version is the one
Renovate keeps current. ``/redoc`` is retired and redirects to ``/docs``.

Content Security Policy for this page: scripts, connections, images and fonts come from
the hub only, and the page declares no inline script (the Scalar configuration lives in
``data-`` attributes of an inert ``application/json`` block). Styles need
``'unsafe-inline'``: Scalar injects several ``<style>`` elements at runtime (its Tailwind
sheet, the theme variables, the toast library's sheet) and sets ``style`` attributes. A nonce
only covers the first of them and hashes break silently on every bundle update, so this one
page allows inline styles, which cannot execute code, while ``script-src`` stays ``'self'``.
"""

from __future__ import annotations

import html
import json
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

logger = logging.getLogger(__name__)

BUNDLE_URL = "/docs/scalar.js"
# Relative to the web app's dist directory (see frontend/vite.config.ts).
BUNDLE_RELATIVE_PATH = Path("scalar") / "standalone.js"
TITLE = "Label Printer Hub API"

# Scalar options that keep the page from talking to anyone but the hub: no default web
# fonts, no telemetry, no hosted request proxy (``proxyUrl`` stays unset), no hosted AI
# agent or MCP promotion.
_SCALAR_CONFIGURATION: dict[str, object] = {
    "withDefaultFonts": False,
    "telemetry": False,
    "agent": {"disabled": True},
    "mcp": {"disabled": True},
    "hideClientButton": True,
    "showDeveloperTools": "never",
    "documentDownloadType": "json",
}


def docs_csp() -> str:
    """CSP for the docs page: everything from the hub; inline *styles* only (see module doc)."""
    return (
        "default-src 'self'; script-src 'self'; connect-src 'self'; "
        "img-src 'self' data: blob:; font-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "worker-src 'self' blob:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )


def render_docs_page(openapi_url: str) -> str:
    """The HTML shell: Scalar configuration in attributes, one external script."""
    configuration = html.escape(
        json.dumps(_SCALAR_CONFIGURATION, separators=(",", ":")), quote=False
    )
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{TITLE}</title>\n</head>\n<body>\n"
        '<script id="api-reference" type="application/json" '
        f'data-url="{html.escape(openapi_url, quote=True)}" '
        f"data-configuration='{configuration}'></script>\n"
        f'<script src="{BUNDLE_URL}"></script>\n'
        "</body>\n</html>\n"
    )


def mount_api_docs(app: FastAPI, dist_dir: Path) -> None:
    """Register ``/docs``, ``/docs/scalar.js`` and the ``/redoc`` redirect.

    Call before ``mount_spa`` so the SPA catch-all never sees these paths.
    """
    bundle = dist_dir / BUNDLE_RELATIVE_PATH
    available = bundle.is_file()
    if not available:
        logger.warning("API reference bundle not found at %s - /docs is unavailable", bundle)

    @app.get("/docs", include_in_schema=False)
    async def docs_page() -> Response:
        if not available:
            return JSONResponse(
                status_code=503,
                content={"detail": "The API reference is not available in this build."},
            )
        return Response(
            content=render_docs_page(app.openapi_url or "/openapi.json"),
            media_type="text/html",
            headers={"Cache-Control": "no-cache", "Content-Security-Policy": docs_csp()},
        )

    @app.get(BUNDLE_URL, include_in_schema=False)
    async def docs_bundle() -> Response:
        if not available:
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        return FileResponse(
            bundle, media_type="text/javascript", headers={"Cache-Control": "no-cache"}
        )

    @app.get("/redoc", include_in_schema=False)
    async def redoc_redirect() -> Response:
        return RedirectResponse("/docs", status_code=308)
