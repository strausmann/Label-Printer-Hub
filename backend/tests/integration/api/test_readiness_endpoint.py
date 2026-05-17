"""Phase 7b Cluster 1e — /readiness deep-check endpoint."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_readiness_returns_200_when_ready(api_client_with_seed):
    resp = await api_client_with_seed.get("/readiness")
    body = resp.json()
    # template_seed will be ok (the fixture seeds), other critical checks ok →
    # printer_runtime may fail (no PT-P750W env) but that's non-critical, so degraded.
    # Both ready and degraded should be 200.
    assert resp.status_code == 200
    assert body["status"] in {"ready", "degraded"}
    assert "checks" in body
    for required in (
        "database",
        "alembic",
        "template_seed",
        "printer_runtime",
        "printer_db_sync",
        "snmp_discovery",
        "print_queue",
        "sse_bus",
    ):
        assert required in body["checks"], f"missing check: {required}"


async def test_readiness_returns_503_when_not_ready(api_client_with_broken_db):
    resp = await api_client_with_broken_db.get("/readiness")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "not-ready"
