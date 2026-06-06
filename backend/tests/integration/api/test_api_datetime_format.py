"""Phase 7b Cluster 1c contract test — every datetime field in the API
response must include a timezone suffix (Z or +HH:MM).

Phase 1k.1a (Task 25): test_template_read_has_tz_suffix removed
(/api/templates endpoint deleted with template model).
"""

from __future__ import annotations

from datetime import datetime

import pytest

pytestmark = pytest.mark.asyncio


def _has_tz_suffix(s: str) -> bool:
    """True if string ends with Z or contains an explicit +/- TZ offset (skip date dashes)."""
    return s.endswith("Z") or "+" in s or "-" in s[10:]


async def test_printer_read_has_tz_suffix(api_client_with_seed):
    """GET /api/printers returns datetimes with TZ info.

    TODO: Task C2 (upsert_runtime_printer) will auto-seed a printer at startup,
    making this test always exercise the assertion block. Until then, the test
    skips gracefully when no printers exist in the test DB.
    """
    resp = await api_client_with_seed.get("/api/printers", headers={"X-Pangolin-User": "test"})
    assert resp.status_code == 200
    body = resp.json()
    if not body:
        pytest.skip("No printers seeded — will be re-enabled after Task C2 auto-seeds a printer")
    for p in body:
        for field in ("created_at", "updated_at"):
            assert _has_tz_suffix(p[field]), (
                f"printer {p.get('id', '?')}: {field}={p[field]!r} missing TZ suffix"
            )
            datetime.fromisoformat(p[field].replace("Z", "+00:00"))


async def test_job_read_has_tz_suffix(api_client_with_seed):
    """GET /api/jobs returns datetimes with TZ info on all datetime fields.

    TODO: Task C2 (upsert_runtime_printer) will auto-seed a printer; an explicit
    print invocation will create jobs. Until then, the test skips gracefully when
    no jobs exist in the test DB.
    """
    resp = await api_client_with_seed.get("/api/jobs", headers={"X-Pangolin-User": "test"})
    assert resp.status_code == 200
    body = resp.json()
    if not body:
        pytest.skip("No jobs seeded — will be re-enabled after Task C2 auto-seeds printer+jobs")
    for j in body:
        for field in ("created_at", "updated_at"):
            assert _has_tz_suffix(j[field]), (
                f"job {j.get('id', '?')}: {field}={j[field]!r} missing TZ suffix"
            )
            datetime.fromisoformat(j[field].replace("Z", "+00:00"))
        # nullable datetime fields — only assert when present
        for field in ("started_at", "finished_at"):
            if j[field] is not None:
                assert _has_tz_suffix(j[field]), (
                    f"job {j.get('id', '?')}: {field}={j[field]!r} missing TZ suffix"
                )
                datetime.fromisoformat(j[field].replace("Z", "+00:00"))
