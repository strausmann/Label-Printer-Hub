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

Phase 6b review fixes (Finding #1 — printer UUID not queue-id):
   14.  GET /loc/{entity_id}     — enabled printer in DB → SSE wired with DB UUID
   15.  GET /loc/{entity_id}     — no enabled printer → SSE block omitted
"""

from __future__ import annotations

import uuid as _uuid_mod
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.api.routes.qr import router
from app.db.session import get_session
from app.schemas.label_data import LabelData
from app.services.errors import AppLookupNotFoundError
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# App factory helpers
# ---------------------------------------------------------------------------


def _make_session_override(session: AsyncSession):  # type: ignore[no-untyped-def]
    """Return a dependency override function that yields the given session."""

    async def _override() -> AsyncIterator[AsyncSession]:
        yield session

    return _override


def _build_app(session: AsyncSession | None = None) -> FastAPI:
    """Return a minimal FastAPI app with the QR router mounted."""
    test_app = FastAPI()
    test_app.include_router(router)
    if session is not None:
        test_app.dependency_overrides[get_session] = _make_session_override(session)
    else:
        # Provide a no-op session so routes that call printers_repo.list_all
        # don't fail with "no session" — the call will be mocked anyway.
        mock_session = MagicMock(spec=AsyncSession)

        async def _noop_session() -> AsyncIterator[AsyncSession]:
            yield mock_session

        test_app.dependency_overrides[get_session] = _noop_session
    return test_app


def _build_app_with_printer_id(printer_id: str = "") -> FastAPI:
    """Return a minimal FastAPI app with the QR router and printer_id in app.state.

    Kept for compatibility with legacy tests that still exercise the template
    rendering path — the state value is irrelevant now that the route looks up
    the UUID from the DB, but preserving ``app.state.printer_id`` doesn't harm
    anything and makes test intent clear.
    """
    test_app = _build_app()
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
_FAKE_PRINTER_UUID = _uuid_mod.UUID("11111111-1111-1111-1111-111111111111")


def _make_enabled_printer(printer_uuid: _uuid_mod.UUID = _FAKE_PRINTER_UUID) -> MagicMock:
    """Return a mock Printer with enabled=True and the given UUID as id."""
    p = MagicMock()
    p.id = printer_uuid
    p.enabled = True
    return p


# ===========================================================================
# /loc — Snipe-IT location
# ===========================================================================


@pytest.mark.asyncio
async def test_loc_landing_happy_path_returns_200_html() -> None:
    """GET /loc/LOC-001 returns 200 HTML with the location name."""
    with (
        patch(
            "app.api.routes.qr._lookup_service.lookup",
            new=AsyncMock(return_value=_SNIPEIT_LOCATION_LABEL),
        ),
        patch(
            "app.api.routes.qr.printers_repo.list_all",
            new=AsyncMock(return_value=[]),
        ),
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
    with (
        patch(
            "app.api.routes.qr._lookup_service.lookup",
            new=AsyncMock(side_effect=AppLookupNotFoundError("not found")),
        ),
        patch(
            "app.api.routes.qr.printers_repo.list_all",
            new=AsyncMock(return_value=[]),
        ),
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
    with (
        patch(
            "app.api.routes.qr._lookup_service.lookup",
            new=AsyncMock(return_value=_SNIPEIT_ASSET_LABEL),
        ),
        patch(
            "app.api.routes.qr.printers_repo.list_all",
            new=AsyncMock(return_value=[]),
        ),
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
    with (
        patch(
            "app.api.routes.qr._lookup_service.lookup",
            new=AsyncMock(side_effect=AppLookupNotFoundError("not found")),
        ),
        patch(
            "app.api.routes.qr.printers_repo.list_all",
            new=AsyncMock(return_value=[]),
        ),
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
    with (
        patch(
            "app.api.routes.qr._lookup_service.lookup",
            new=AsyncMock(return_value=_SPOOLMAN_SPOOL_LABEL),
        ),
        patch(
            "app.api.routes.qr.printers_repo.list_all",
            new=AsyncMock(return_value=[]),
        ),
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
    with (
        patch(
            "app.api.routes.qr._lookup_service.lookup",
            new=AsyncMock(side_effect=AppLookupNotFoundError("not found")),
        ),
        patch(
            "app.api.routes.qr.printers_repo.list_all",
            new=AsyncMock(return_value=[]),
        ),
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
    with (
        patch(
            "app.api.routes.qr._lookup_service.lookup",
            new=AsyncMock(return_value=_GROCY_PRODUCT_LABEL),
        ),
        patch(
            "app.api.routes.qr.printers_repo.list_all",
            new=AsyncMock(return_value=[]),
        ),
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
    with (
        patch(
            "app.api.routes.qr._lookup_service.lookup",
            new=AsyncMock(side_effect=AppLookupNotFoundError("not found")),
        ),
        patch(
            "app.api.routes.qr.printers_repo.list_all",
            new=AsyncMock(return_value=[]),
        ),
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
    """Spool landing page must include the HTMX SSE connect block when enabled printer in DB."""
    with (
        patch(
            "app.api.routes.qr._lookup_service.lookup",
            new=AsyncMock(return_value=_SPOOLMAN_SPOOL_LABEL),
        ),
        patch(
            "app.api.routes.qr.printers_repo.list_all",
            new=AsyncMock(return_value=[_make_enabled_printer()]),
        ),
    ):
        client = TestClient(_build_app(), raise_server_exceptions=True)
        r = client.get("/spool/88")

    assert r.status_code == 200
    assert 'sse-connect="/api/events?printer_id=' in r.text
    assert 'hx-ext="sse"' in r.text


@pytest.mark.asyncio
async def test_loc_page_has_sse_connect_attribute() -> None:
    """Location landing page must include the HTMX SSE connect block when enabled printer in DB."""
    with (
        patch(
            "app.api.routes.qr._lookup_service.lookup",
            new=AsyncMock(return_value=_SNIPEIT_LOCATION_LABEL),
        ),
        patch(
            "app.api.routes.qr.printers_repo.list_all",
            new=AsyncMock(return_value=[_make_enabled_printer()]),
        ),
    ):
        client = TestClient(_build_app(), raise_server_exceptions=True)
        r = client.get("/loc/LOC-001")

    assert r.status_code == 200
    assert 'sse-connect="/api/events?printer_id=' in r.text
    assert 'hx-ext="sse"' in r.text


@pytest.mark.asyncio
async def test_asset_page_has_sse_connect_attribute() -> None:
    """Asset landing page must include the HTMX SSE connect block when enabled printer in DB."""
    with (
        patch(
            "app.api.routes.qr._lookup_service.lookup",
            new=AsyncMock(return_value=_SNIPEIT_ASSET_LABEL),
        ),
        patch(
            "app.api.routes.qr.printers_repo.list_all",
            new=AsyncMock(return_value=[_make_enabled_printer()]),
        ),
    ):
        client = TestClient(_build_app(), raise_server_exceptions=True)
        r = client.get("/asset/SRV-042")

    assert r.status_code == 200
    assert 'sse-connect="/api/events?printer_id=' in r.text
    assert 'hx-ext="sse"' in r.text


@pytest.mark.asyncio
async def test_product_page_has_sse_connect_attribute() -> None:
    """Product landing page must include the HTMX SSE connect block when enabled printer in DB."""
    with (
        patch(
            "app.api.routes.qr._lookup_service.lookup",
            new=AsyncMock(return_value=_GROCY_PRODUCT_LABEL),
        ),
        patch(
            "app.api.routes.qr.printers_repo.list_all",
            new=AsyncMock(return_value=[_make_enabled_printer()]),
        ),
    ):
        client = TestClient(_build_app(), raise_server_exceptions=True)
        r = client.get("/product/17")

    assert r.status_code == 200
    assert 'sse-connect="/api/events?printer_id=' in r.text
    assert 'hx-ext="sse"' in r.text


@pytest.mark.asyncio
async def test_spool_not_found_has_no_sse_block() -> None:
    """Not-found QR page must NOT include the SSE block (not_found=True suppresses it)."""
    with (
        patch(
            "app.api.routes.qr._lookup_service.lookup",
            new=AsyncMock(side_effect=AppLookupNotFoundError("not found")),
        ),
        patch(
            "app.api.routes.qr.printers_repo.list_all",
            new=AsyncMock(return_value=[_make_enabled_printer()]),
        ),
    ):
        client = TestClient(_build_app(), raise_server_exceptions=False)
        r = client.get("/spool/9999")

    assert r.status_code == 404
    # not_found=True → no SSE div rendered regardless of printer availability
    assert 'hx-ext="sse"' not in r.text


# ===========================================================================
# Finding #1 — QR pages must wire SSE with the DB UUID, not the queue-id
# ===========================================================================


@pytest.mark.asyncio
async def test_loc_page_sse_uses_db_uuid_not_queue_id() -> None:
    """GET /loc/LOC-001 with an enabled printer in DB must use the DB UUID in the
    SSE connect URL, not the queue-printer composite id (e.g. PT-P750W@host).

    This is the regression test for Finding #1: the old code passed
    app.state.printer_id (which is the queue-id string like 'PT-P750W@host')
    rather than the UUID from the printers table. The /api/events endpoint
    expects a valid UUID and returns 404 otherwise.
    """
    import uuid as _u

    db_uuid = _u.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    fake_printer = _make_enabled_printer(printer_uuid=db_uuid)

    with (
        patch(
            "app.api.routes.qr._lookup_service.lookup",
            new=AsyncMock(return_value=_SNIPEIT_LOCATION_LABEL),
        ),
        patch(
            "app.api.routes.qr.printers_repo.list_all",
            new=AsyncMock(return_value=[fake_printer]),
        ),
    ):
        client = TestClient(_build_app(), raise_server_exceptions=True)
        r = client.get("/loc/LOC-001")

    assert r.status_code == 200
    # The SSE URL must contain the real DB UUID, parseable by uuid.UUID
    assert f'sse-connect="/api/events?printer_id={db_uuid}"' in r.text
    # Confirm it is a valid UUID (would raise ValueError if not)
    url_part = f"/api/events?printer_id={db_uuid}"
    uuid_str = url_part.split("printer_id=")[1].split('"')[0]
    _u.UUID(uuid_str)  # raises if invalid


@pytest.mark.asyncio
async def test_loc_page_no_sse_when_no_enabled_printer() -> None:
    """GET /loc/LOC-001 with NO enabled printers must render page WITHOUT SSE block.

    When the DB has no enabled printers the SSE wiring is silently omitted so
    the page still renders usably — the user sees the label data but no live
    status updates.
    """
    with (
        patch(
            "app.api.routes.qr._lookup_service.lookup",
            new=AsyncMock(return_value=_SNIPEIT_LOCATION_LABEL),
        ),
        patch(
            "app.api.routes.qr.printers_repo.list_all",
            new=AsyncMock(return_value=[]),
        ),
    ):
        client = TestClient(_build_app(), raise_server_exceptions=True)
        r = client.get("/loc/LOC-001")

    assert r.status_code == 200
    assert "Server Room A" in r.text
    # No SSE block when no enabled printer exists
    assert 'hx-ext="sse"' not in r.text
