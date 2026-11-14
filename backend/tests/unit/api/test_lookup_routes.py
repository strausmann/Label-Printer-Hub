# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for app.api.routes.lookup — 1 endpoint, 3 scenarios (Phase 6a Task 4).

Test mapping:
    1. GET /api/v1/lookup/snipeit/ASSET-001  → 200 LookupResult (happy path)
    2. GET /api/v1/lookup/snipeit/MISSING    → 404 ProblemDetail (not-found)
    3. GET /api/v1/lookup/unknown/123        → 422 Unprocessable Entity (invalid app)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from app.api.routes.lookup import router
from app.auth.scope_deps import require_read
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
    # Authentication is covered in tests/integration/api/test_lookup_auth.py.
    test_app.dependency_overrides[require_read] = lambda: None

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
    """GET /api/v1/lookup/snipeit/ASSET-001 returns 200 LookupResult."""
    with patch(
        "app.api.routes.lookup._lookup_service.lookup",
        new=AsyncMock(return_value=_SNIPEIT_LABEL),
    ):
        client = TestClient(_build_app(), raise_server_exceptions=True)
        r = client.get("/api/v1/lookup/snipeit/ASSET-001")

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
    """GET /api/v1/lookup/snipeit/MISSING returns 404 ProblemDetail."""
    with patch(
        "app.api.routes.lookup._lookup_service.lookup",
        new=AsyncMock(side_effect=AppLookupNotFoundError("Asset MISSING not found")),
    ):
        client = TestClient(_build_app(), raise_server_exceptions=False)
        r = client.get("/api/v1/lookup/snipeit/MISSING")

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
    """GET /api/v1/lookup/unknown/123 returns 422 because 'unknown' is not in the Literal."""
    client = TestClient(_build_app(), raise_server_exceptions=True)
    r = client.get("/api/v1/lookup/unknown/123")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Grocy battery and chore details
# ---------------------------------------------------------------------------

from app.schemas.grocy_object import GrocyBatteryResult, GrocyChoreResult  # noqa: E402
from app.services.errors import IntegrationNotConfiguredError  # noqa: E402
from app.services.lookup_service import LookupFailedError  # noqa: E402

_BATTERY = GrocyBatteryResult(
    id="4", name="Remote AAA", url="https://grocy.example.invalid/battery/4", charge_cycles=3
)
_CHORE = GrocyChoreResult(
    id="7",
    name="Water the plants",
    url="https://grocy.example.invalid/chore/7",
    assigned_to="Anna B.",
)


def test_grocy_battery_route_returns_the_dto() -> None:
    with patch(
        "app.api.routes.lookup._lookup_service.grocy_battery", new=AsyncMock(return_value=_BATTERY)
    ) as svc:
        r = TestClient(_build_app()).get("/api/v1/lookup/grocy/batteries/4")
    assert r.status_code == 200
    assert r.json() == {
        "id": "4",
        "name": "Remote AAA",
        "description": None,
        "url": "https://grocy.example.invalid/battery/4",
        "last_charged": None,
        "next_estimated_charge": None,
        "charge_cycles": 3,
    }
    svc.assert_awaited_once_with("4")


def test_grocy_chore_route_returns_the_dto() -> None:
    with patch(
        "app.api.routes.lookup._lookup_service.grocy_chore", new=AsyncMock(return_value=_CHORE)
    ):
        r = TestClient(_build_app()).get("/api/v1/lookup/grocy/chores/7")
    assert r.status_code == 200
    assert r.json()["assigned_to"] == "Anna B."
    assert r.json()["url"].endswith("/chore/7")


@pytest.mark.parametrize("kind", ["batteries", "chores"])
def test_grocy_object_routes_map_the_errors_like_the_product_lookup(kind: str) -> None:
    method = "grocy_battery" if kind == "batteries" else "grocy_chore"
    cases = [
        (AppLookupNotFoundError("nope"), 404),
        (IntegrationNotConfiguredError("Grocy is not configured"), 503),
        (LookupFailedError("upstream failed"), 500),
    ]
    for error, status in cases:
        with patch(
            f"app.api.routes.lookup._lookup_service.{method}", new=AsyncMock(side_effect=error)
        ):
            r = TestClient(_build_app(), raise_server_exceptions=False).get(
                f"/api/v1/lookup/grocy/{kind}/4"
            )
        assert r.status_code == status, (kind, error)


@pytest.mark.parametrize("bad", ["abc", "4x", "-1", "1" * 19])
def test_grocy_object_routes_reject_non_numeric_ids(bad: str) -> None:
    with patch("app.api.routes.lookup._lookup_service.grocy_battery", new=AsyncMock()) as svc:
        r = TestClient(_build_app()).get(f"/api/v1/lookup/grocy/batteries/{bad}")
    assert r.status_code == 422
    svc.assert_not_called()


@pytest.mark.asyncio
async def test_service_wraps_unexpected_plugin_errors_and_lets_known_ones_through() -> None:
    import app.integrations  # noqa: F401
    from app.integrations.registry import IntegrationRegistry
    from app.services.lookup_service import AppLookupService

    plugin = IntegrationRegistry.get("grocy")
    service = AppLookupService()
    boom = AsyncMock(side_effect=RuntimeError("boom"))
    with patch.object(plugin, "battery", new=boom), pytest.raises(LookupFailedError):
        await service.grocy_battery("4")
    missing = AsyncMock(side_effect=AppLookupNotFoundError("x"))
    with patch.object(plugin, "chore", new=missing), pytest.raises(AppLookupNotFoundError):
        await service.grocy_chore("7")
