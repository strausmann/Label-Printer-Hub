"""Unit tests for app.api.routes.qr — 4 endpoints, 2 scenarios each (Phase 6a Task 6).

Test mapping:
    1.  GET /loc/{entity_id}     — happy path                    → 200 HTML with name
    2.  GET /loc/{entity_id}     — entity not found              → 404 HTML (not-found page)
    3.  GET /asset/{entity_id}   — happy path                    → 200 HTML with name
    4.  GET /asset/{entity_id}   — entity not found              → 404 HTML (not-found page)
    5.  GET /spool/{entity_id}   — happy path                    → 200 HTML with name
    6.  GET /spool/{entity_id}   — entity not found              → 404 HTML (not-found page)
    7.  GET /product/{entity_id} — happy path                    → 200 HTML with name
    8.  GET /product/{entity_id} — entity not found              → 404 HTML (not-found page)

Phase 6b additions (Task 7):
    9.  GET /spool/{entity_id}   — SSE connect attribute present  → hx-ext="sse" + sse-connect
   10.  GET /loc/{entity_id}     — SSE connect attribute present  → hx-ext="sse" + sse-connect
   11.  GET /asset/{entity_id}   — SSE connect attribute present  → hx-ext="sse" + sse-connect
   12.  GET /product/{entity_id} — SSE connect attribute present  → hx-ext="sse" + sse-connect
   13.  GET /spool/{entity_id}   — not_found → no SSE block (no printer_id in context)
"""

from __future__ import annotations

import uuid as _uuid_mod
from unittest.mock import AsyncMock, patch

import pytest
from app.api.routes.qr import router
from app.schemas.label_data import LabelData
from app.services.errors import AppLookupNotFoundError
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def _build_app() -> FastAPI:
    """Return a minimal FastAPI app with the QR router mounted."""
    test_app = FastAPI()
    test_app.include_router(router)
    return test_app


def _build_app_with_printer_id(printer_id: str = "") -> FastAPI:
    """Return a minimal FastAPI app with the QR router and printer_id in app.state."""
    test_app = FastAPI()
    test_app.include_router(router)
    test_app.state.printer_id = printer_id
    return test_app


# ---------------------------------------------------------------------------
# Shared LabelData fixtures
# ---------------------------------------------------------------------------

_SNIPEIT_LOCATION_LABEL = LabelData(
    title="Server Room A",
    primary_id="LOC-001",
    qr_payload="https://snipeit.example.com/locations/5",
    source_app="snipeit",
    secondary=(),
)

_SNIPEIT_ASSET_LABEL = LabelData(
    title="Dell PowerEdge R740",
    primary_id="SRV-042",
    qr_payload="https://snipeit.example.com/hardware/42",
    source_app="snipeit",
    secondary=("S/N: ABCDEF",),
)

_SPOOLMAN_SPOOL_LABEL = LabelData(
    title="Prusament PLA Galaxy Black",
    primary_id="#88",
    qr_payload="http://spoolman.local/spool/show/88",
    source_app="spoolman",
    secondary=("720g remaining",),
)

_GROCY_PRODUCT_LABEL = LabelData(
    title="Olive Oil Extra Virgin",
    primary_id="17",
    qr_payload="http://grocy.local/product/17",
    source_app="grocy",
    secondary=(),
)

_FAKE_PRINTER_ID = str(_uuid_mod.UUID("11111111-1111-1111-1111-111111111111"))


# ===========================================================================
# /loc — Snipe-IT location
# ===========================================================================


@pytest.mark.asyncio
async def test_loc_landing_happy_path_returns_200_html() -> None:
    """GET /loc/LOC-001 returns 200 HTML with the location name."""
    with patch(
        "app.api.routes.qr._lookup_service.lookup",
        new=AsyncMock(return_value=_SNIPEIT_LOCATION_LABEL),
    ):
        client = TestClient(_build_app(), raise_server_exceptions=True)
        r = client.get("/loc/LOC-001")

    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Server Room A" in r.text
    assert "LOC-001" in r.text
    assert "snipeit.example.com" in r.text


@pytest.mark.asyncio
async def test_loc_landing_not_found_returns_404_html() -> None:
    """GET /loc/MISSING returns 404 HTML (not-found page, not JSON)."""
    with patch(
        "app.api.routes.qr._lookup_service.lookup",
        new=AsyncMock(side_effect=AppLookupNotFoundError("not found")),
    ):
        client = TestClient(_build_app(), raise_server_exceptions=False)
        r = client.get("/loc/MISSING")

    assert r.status_code == 404
    assert "text/html" in r.headers["content-type"]
    assert "not found" in r.text.lower()


# ===========================================================================
# /asset — Snipe-IT asset
# ===========================================================================


@pytest.mark.asyncio
async def test_asset_landing_happy_path_returns_200_html() -> None:
    """GET /asset/SRV-042 returns 200 HTML with the asset name."""
    with patch(
        "app.api.routes.qr._lookup_service.lookup",
        new=AsyncMock(return_value=_SNIPEIT_ASSET_LABEL),
    ):
        client = TestClient(_build_app(), raise_server_exceptions=True)
        r = client.get("/asset/SRV-042")

    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Dell PowerEdge R740" in r.text
    assert "SRV-042" in r.text
    assert "snipeit.example.com" in r.text


@pytest.mark.asyncio
async def test_asset_landing_not_found_returns_404_html() -> None:
    """GET /asset/MISSING returns 404 HTML (not-found page, not JSON)."""
    with patch(
        "app.api.routes.qr._lookup_service.lookup",
        new=AsyncMock(side_effect=AppLookupNotFoundError("not found")),
    ):
        client = TestClient(_build_app(), raise_server_exceptions=False)
        r = client.get("/asset/MISSING")

    assert r.status_code == 404
    assert "text/html" in r.headers["content-type"]
    assert "not found" in r.text.lower()


# ===========================================================================
# /spool — Spoolman filament spool
# ===========================================================================


@pytest.mark.asyncio
async def test_spool_landing_happy_path_returns_200_html() -> None:
    """GET /spool/88 returns 200 HTML with the spool name."""
    with patch(
        "app.api.routes.qr._lookup_service.lookup",
        new=AsyncMock(return_value=_SPOOLMAN_SPOOL_LABEL),
    ):
        client = TestClient(_build_app(), raise_server_exceptions=True)
        r = client.get("/spool/88")

    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Prusament PLA Galaxy Black" in r.text
    assert "88" in r.text
    assert "spoolman.local" in r.text


@pytest.mark.asyncio
async def test_spool_landing_not_found_returns_404_html() -> None:
    """GET /spool/9999 returns 404 HTML (not-found page, not JSON)."""
    with patch(
        "app.api.routes.qr._lookup_service.lookup",
        new=AsyncMock(side_effect=AppLookupNotFoundError("not found")),
    ):
        client = TestClient(_build_app(), raise_server_exceptions=False)
        r = client.get("/spool/9999")

    assert r.status_code == 404
    assert "text/html" in r.headers["content-type"]
    assert "not found" in r.text.lower()


# ===========================================================================
# /product — Grocy product
# ===========================================================================


@pytest.mark.asyncio
async def test_product_landing_happy_path_returns_200_html() -> None:
    """GET /product/17 returns 200 HTML with the product name."""
    with patch(
        "app.api.routes.qr._lookup_service.lookup",
        new=AsyncMock(return_value=_GROCY_PRODUCT_LABEL),
    ):
        client = TestClient(_build_app(), raise_server_exceptions=True)
        r = client.get("/product/17")

    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Olive Oil Extra Virgin" in r.text
    assert "17" in r.text
    assert "grocy.local" in r.text


@pytest.mark.asyncio
async def test_product_landing_not_found_returns_404_html() -> None:
    """GET /product/9999 returns 404 HTML (not-found page, not JSON)."""
    with patch(
        "app.api.routes.qr._lookup_service.lookup",
        new=AsyncMock(side_effect=AppLookupNotFoundError("not found")),
    ):
        client = TestClient(_build_app(), raise_server_exceptions=False)
        r = client.get("/product/9999")

    assert r.status_code == 404
    assert "text/html" in r.headers["content-type"]
    assert "not found" in r.text.lower()


# ===========================================================================
# Phase 6b Task 7 — HTMX SSE wiring assertions
# ===========================================================================


@pytest.mark.asyncio
async def test_spool_page_has_sse_connect_attribute() -> None:
    """Spool landing page must include the HTMX SSE connect block when printer_id set."""
    with patch(
        "app.api.routes.qr._lookup_service.lookup",
        new=AsyncMock(return_value=_SPOOLMAN_SPOOL_LABEL),
    ):
        client = TestClient(
            _build_app_with_printer_id(_FAKE_PRINTER_ID),
            raise_server_exceptions=True,
        )
        r = client.get("/spool/88")

    assert r.status_code == 200
    assert 'sse-connect="/api/events?printer_id=' in r.text
    assert 'hx-ext="sse"' in r.text


@pytest.mark.asyncio
async def test_loc_page_has_sse_connect_attribute() -> None:
    """Location landing page must include the HTMX SSE connect block when printer_id set."""
    with patch(
        "app.api.routes.qr._lookup_service.lookup",
        new=AsyncMock(return_value=_SNIPEIT_LOCATION_LABEL),
    ):
        client = TestClient(
            _build_app_with_printer_id(_FAKE_PRINTER_ID),
            raise_server_exceptions=True,
        )
        r = client.get("/loc/LOC-001")

    assert r.status_code == 200
    assert 'sse-connect="/api/events?printer_id=' in r.text
    assert 'hx-ext="sse"' in r.text


@pytest.mark.asyncio
async def test_asset_page_has_sse_connect_attribute() -> None:
    """Asset landing page must include the HTMX SSE connect block when printer_id set."""
    with patch(
        "app.api.routes.qr._lookup_service.lookup",
        new=AsyncMock(return_value=_SNIPEIT_ASSET_LABEL),
    ):
        client = TestClient(
            _build_app_with_printer_id(_FAKE_PRINTER_ID),
            raise_server_exceptions=True,
        )
        r = client.get("/asset/SRV-042")

    assert r.status_code == 200
    assert 'sse-connect="/api/events?printer_id=' in r.text
    assert 'hx-ext="sse"' in r.text


@pytest.mark.asyncio
async def test_product_page_has_sse_connect_attribute() -> None:
    """Product landing page must include the HTMX SSE connect block when printer_id set."""
    with patch(
        "app.api.routes.qr._lookup_service.lookup",
        new=AsyncMock(return_value=_GROCY_PRODUCT_LABEL),
    ):
        client = TestClient(
            _build_app_with_printer_id(_FAKE_PRINTER_ID),
            raise_server_exceptions=True,
        )
        r = client.get("/product/17")

    assert r.status_code == 200
    assert 'sse-connect="/api/events?printer_id=' in r.text
    assert 'hx-ext="sse"' in r.text


@pytest.mark.asyncio
async def test_spool_not_found_has_no_sse_block() -> None:
    """Not-found QR page must NOT include the SSE block (not_found=True suppresses it)."""
    with patch(
        "app.api.routes.qr._lookup_service.lookup",
        new=AsyncMock(side_effect=AppLookupNotFoundError("not found")),
    ):
        client = TestClient(
            _build_app_with_printer_id(_FAKE_PRINTER_ID),
            raise_server_exceptions=False,
        )
        r = client.get("/spool/9999")

    assert r.status_code == 404
    # not_found=True → no SSE div rendered
    assert 'hx-ext="sse"' not in r.text
