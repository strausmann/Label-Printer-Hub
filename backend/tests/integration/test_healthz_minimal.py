"""Phase 7b Cluster 1e — /healthz never queries the database.

Locks in the liveness/readiness contract: /healthz must answer 200
even when the DB is unreachable, otherwise Docker autoheal would
restart-loop on transient DB failures. Deep checks belong to /readiness.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_healthz_returns_200_even_with_broken_db(api_client_with_broken_db):
    resp = await api_client_with_broken_db.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok" or body.get("ok") is True
