"""Phase 7b Cluster 1e — /readiness deep-check endpoint.

Phase 1k.1a (Task 25): template_seed removed from required checks
(template seeding removed in Phase 1k.1a).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_readiness_returns_200_when_ready(api_client_with_seed):
    resp = await api_client_with_seed.get("/readiness", headers={"X-Pangolin-User": "test"})
    body = resp.json()
    # printer_runtime may fail (no PT-P750W env) but that's non-critical, so degraded.
    # Both ready and degraded should be 200.
    assert resp.status_code == 200
    assert body["status"] in {"ready", "degraded"}
    assert "checks" in body
    for required in (
        "database",
        "alembic",
        "printer_runtime",
        "printer_db_sync",
        "print_queue",
        "snmp_discovery",
        "sse_bus",
    ):
        assert required in body["checks"], f"missing check: {required}"
    # Phase 1k.1a: template_seed removed from readiness checks
    assert "template_seed" not in body["checks"], (
        "template_seed should not appear in readiness checks after Phase 1k.1a"
    )


async def test_readiness_returns_503_when_not_ready(api_client_with_broken_db):
    resp = await api_client_with_broken_db.get("/readiness", headers={"X-Pangolin-User": "test"})
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "not-ready"
