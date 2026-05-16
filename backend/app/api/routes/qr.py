"""QR landing pages — scan-friendly HTML detail pages (Phase 6a Task 6).

Routes (no /api/ prefix — these are end-user QR-scan URLs)
----------------------------------------------------------
GET /loc/{entity_id}     — Snipe-IT location landing page
GET /asset/{entity_id}   — Snipe-IT asset landing page
GET /spool/{entity_id}   — Spoolman filament-spool landing page
GET /product/{entity_id} — Grocy product landing page

Design notes
------------
These routes intentionally live outside the ``/api/`` prefix.  They are
printed as QR payloads on physical labels; the URL must be short and
human-readable when someone manually types it.

Each handler:

1. Calls ``AppLookupService`` for the integration data.
2. Renders the appropriate Jinja2 HTML template (``app/templates/qr/``).
3. Returns ``HTMLResponse`` — not JSON — so the result renders directly on
   a phone screen without any JavaScript.

404 handling
------------
Rather than returning a JSON ProblemDetail (ugly on a phone), 404 cases
render the same Jinja2 template with ``not_found=True`` and
``status_code=404``.  The browser gets a styled "not found" page rather
than raw JSON.

Jinja2 setup
------------
``Jinja2Templates`` is instantiated once at module level, pointed at
``app/templates/``.  FastAPI's ``Jinja2Templates.TemplateResponse`` accepts
the ``request`` object as first positional argument (FastAPI ≥ 0.111 / Starlette
≥ 0.37 API).

References:
    docs/superpowers/specs/2026-05-16-phase6a-rest-api-design.md — QR section
    docs/superpowers/plans/2026-05-16-phase6a-rest-api.md — Task 6
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.services.errors import AppLookupNotFoundError
from app.services.lookup_service import AppLookupService

router = APIRouter(tags=["qr-landing"])

# Templates directory: backend/app/templates/
_templates_dir = Path(__file__).parent.parent.parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))

# Shared service instance — stateless, safe to reuse across requests.
_lookup_service = AppLookupService()


# ---------------------------------------------------------------------------
# GET /loc/{entity_id} — Snipe-IT location
# ---------------------------------------------------------------------------


@router.get(
    "/loc/{entity_id}",
    response_class=HTMLResponse,
    summary="QR landing page — Snipe-IT location",
    description=(
        "Renders a minimal HTML detail page for the Snipe-IT location "
        "identified by ``entity_id``.  Intended as the QR-code payload on "
        "printed location labels.  Returns 404 HTML when the location is not "
        "found (rather than JSON, so it renders cleanly on a phone browser)."
    ),
)
async def loc_landing(request: Request, entity_id: str) -> HTMLResponse:
    """Render the location detail page for ``entity_id``."""
    try:
        data = await _lookup_service.lookup("snipeit", entity_id)
        return templates.TemplateResponse(
            request=request,
            name="qr/loc.html",
            context={
                "title": data.title,
                "entity_id": entity_id,
                "name": data.title,
                "external_url": data.qr_payload,
                "not_found": False,
                "printer_id": str(getattr(request.app.state, "printer_id", "")),
            },
        )
    except AppLookupNotFoundError:
        return templates.TemplateResponse(
            request=request,
            name="qr/loc.html",
            context={
                "title": "Not Found",
                "entity_id": entity_id,
                "name": "",
                "external_url": None,
                "not_found": True,
            },
            status_code=status.HTTP_404_NOT_FOUND,
        )


# ---------------------------------------------------------------------------
# GET /asset/{entity_id} — Snipe-IT asset
# ---------------------------------------------------------------------------


@router.get(
    "/asset/{entity_id}",
    response_class=HTMLResponse,
    summary="QR landing page — Snipe-IT asset",
    description=(
        "Renders a minimal HTML detail page for the Snipe-IT asset identified "
        "by ``entity_id`` (asset tag).  Intended as the QR-code payload on "
        "printed asset labels.  Returns 404 HTML when the asset is not found."
    ),
)
async def asset_landing(request: Request, entity_id: str) -> HTMLResponse:
    """Render the asset detail page for ``entity_id``."""
    try:
        data = await _lookup_service.lookup("snipeit", entity_id)
        return templates.TemplateResponse(
            request=request,
            name="qr/asset.html",
            context={
                "title": data.title,
                "entity_id": entity_id,
                "name": data.title,
                "external_url": data.qr_payload,
                "not_found": False,
                "printer_id": str(getattr(request.app.state, "printer_id", "")),
            },
        )
    except AppLookupNotFoundError:
        return templates.TemplateResponse(
            request=request,
            name="qr/asset.html",
            context={
                "title": "Not Found",
                "entity_id": entity_id,
                "name": "",
                "external_url": None,
                "not_found": True,
            },
            status_code=status.HTTP_404_NOT_FOUND,
        )


# ---------------------------------------------------------------------------
# GET /spool/{entity_id} — Spoolman filament spool
# ---------------------------------------------------------------------------


@router.get(
    "/spool/{entity_id}",
    response_class=HTMLResponse,
    summary="QR landing page — Spoolman filament spool",
    description=(
        "Renders a minimal HTML detail page for the Spoolman filament spool "
        "identified by ``entity_id``.  Intended as the QR-code payload on "
        "printed spool labels.  Returns 404 HTML when the spool is not found."
    ),
)
async def spool_landing(request: Request, entity_id: str) -> HTMLResponse:
    """Render the spool detail page for ``entity_id``."""
    try:
        data = await _lookup_service.lookup("spoolman", entity_id)
        return templates.TemplateResponse(
            request=request,
            name="qr/spool.html",
            context={
                "title": data.title,
                "entity_id": entity_id,
                "name": data.title,
                "external_url": data.qr_payload,
                "not_found": False,
                "printer_id": str(getattr(request.app.state, "printer_id", "")),
            },
        )
    except AppLookupNotFoundError:
        return templates.TemplateResponse(
            request=request,
            name="qr/spool.html",
            context={
                "title": "Not Found",
                "entity_id": entity_id,
                "name": "",
                "external_url": None,
                "not_found": True,
            },
            status_code=status.HTTP_404_NOT_FOUND,
        )


# ---------------------------------------------------------------------------
# GET /product/{entity_id} — Grocy product
# ---------------------------------------------------------------------------


@router.get(
    "/product/{entity_id}",
    response_class=HTMLResponse,
    summary="QR landing page — Grocy product",
    description=(
        "Renders a minimal HTML detail page for the Grocy product identified "
        "by ``entity_id``.  Intended as the QR-code payload on printed product "
        "labels.  Returns 404 HTML when the product is not found."
    ),
)
async def product_landing(request: Request, entity_id: str) -> HTMLResponse:
    """Render the product detail page for ``entity_id``."""
    try:
        data = await _lookup_service.lookup("grocy", entity_id)
        return templates.TemplateResponse(
            request=request,
            name="qr/product.html",
            context={
                "title": data.title,
                "entity_id": entity_id,
                "name": data.title,
                "external_url": data.qr_payload,
                "not_found": False,
                "printer_id": str(getattr(request.app.state, "printer_id", "")),
            },
        )
    except AppLookupNotFoundError:
        return templates.TemplateResponse(
            request=request,
            name="qr/product.html",
            context={
                "title": "Not Found",
                "entity_id": entity_id,
                "name": "",
                "external_url": None,
                "not_found": True,
            },
            status_code=status.HTTP_404_NOT_FOUND,
        )
