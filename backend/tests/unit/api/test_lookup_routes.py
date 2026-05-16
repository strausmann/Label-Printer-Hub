"""Unit tests for app.api.routes.lookup — 1 endpoint, 3 scenarios (Phase 6a Task 4).

Test mapping:
    1. GET /api/lookup/snipeit/ASSET-001  → 200 LookupResult (happy path)
    2. GET /api/lookup/snipeit/MISSING    → 404 ProblemDetail (not-found)
    3. GET /api/lookup/unknown/123        → 422 Unprocessable Entity (invalid app)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from app.api.routes.lookup import router
from app.schemas.label_data import LabelData
from app.services.errors import AppLookupNotFoundError
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Error-handler wiring (so 404 from AppLookupNotFoundError is exercised)
# ---------------------------------------------------------------------------


def _build_app() -> FastAPI:
    """Return a FastAPI app with the lookup router and error handlers."""
    test_app = FastAPI()
    test_app.include_router(router)

    from app.api.error_handlers import register_error_handlers

    register_error_handlers(test_app)
    return test_app


# ---------------------------------------------------------------------------
# Shared LabelData fixture
# ---------------------------------------------------------------------------

_SNIPEIT_LABEL = LabelData(
    title="ThinkPad X1 Carbon",
    primary_id="ASSET-001",
    qr_payload="https://snipeit.example.com/hardware/42",
    source_app="snipeit",
    secondary=("S/N: ABC123",),
)


# ---------------------------------------------------------------------------
# Test 1: happy path — known app, known entity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lookup_known_app_and_entity_returns_200_lookup_result() -> None:
    """GET /api/lookup/snipeit/ASSET-001 returns 200 LookupResult."""
    with patch(
        "app.api.routes.lookup._lookup_service.lookup",
        new=AsyncMock(return_value=_SNIPEIT_LABEL),
    ):
        client = TestClient(_build_app(), raise_server_exceptions=True)
        r = client.get("/api/lookup/snipeit/ASSET-001")

    assert r.status_code == 200
    body = r.json()
    assert body["app"] == "snipeit"
    assert body["id"] == "ASSET-001"
    assert body["name"] == "ThinkPad X1 Carbon"
    assert body["url"] == "https://snipeit.example.com/hardware/42"
    # secondary lines are projected into extra["secondary"]
    assert body["extra"]["secondary"] == ["S/N: ABC123"]


# ---------------------------------------------------------------------------
# Test 2: entity not found — service raises AppLookupNotFoundError → 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lookup_not_found_entity_returns_404_problem_detail() -> None:
    """GET /api/lookup/snipeit/MISSING returns 404 ProblemDetail."""
    with patch(
        "app.api.routes.lookup._lookup_service.lookup",
        new=AsyncMock(side_effect=AppLookupNotFoundError("Asset MISSING not found")),
    ):
        client = TestClient(_build_app(), raise_server_exceptions=False)
        r = client.get("/api/lookup/snipeit/MISSING")

    assert r.status_code == 404
    body = r.json()
    # Global handler wraps in ProblemDetail
    assert body["status"] == 404
    assert "not-found" in body["type"]


# ---------------------------------------------------------------------------
# Test 3: invalid app — FastAPI validates Literal → 422
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lookup_invalid_app_returns_422() -> None:
    """GET /api/lookup/unknown/123 returns 422 because 'unknown' is not in the Literal."""
    client = TestClient(_build_app(), raise_server_exceptions=True)
    r = client.get("/api/lookup/unknown/123")
    assert r.status_code == 422
