"""Phase 7b Cluster 1c contract test — every datetime field in the API
response must include a timezone suffix (Z or +HH:MM)."""

from __future__ import annotations

from datetime import datetime

import pytest

pytestmark = pytest.mark.asyncio


def _has_tz_suffix(s: str) -> bool:
    """True if string ends with Z or contains an explicit +/- TZ offset (skip date dashes)."""
    return s.endswith("Z") or "+" in s or "-" in s[10:]


async def test_template_read_has_tz_suffix(api_client_with_seed):
    """GET /api/templates returns datetimes with TZ info that fromisoformat can parse."""
    resp = await api_client_with_seed.get("/api/templates")
    assert resp.status_code == 200
    body = resp.json()
    assert body, "expected at least one seeded template"
    for t in body:
        for field in ("created_at", "updated_at"):
            assert _has_tz_suffix(t[field]), (
                f"template {t.get('key', '?')}: {field}={t[field]!r} missing TZ suffix"
            )
            datetime.fromisoformat(t[field].replace("Z", "+00:00"))
