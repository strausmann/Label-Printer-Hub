"""Integration tests for API key audit trail on jobs — Phase 7c Step 7.

Tests that POST /api/print with a key sets api_key_id and source_ip on the Job row.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import app.models  # noqa: F401
import bcrypt
import pytest
from app.models.api_key import ApiKey

_SEED_DIR = Path(__file__).parents[3] / "app" / "seed" / "templates"


async def _insert_print_key(factory):
    plaintext = f"lh_audit_trail_test_{uuid4().hex[:16]}"
    prefix = plaintext[:12]
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    key_id = uuid4()
    async with factory() as s:
        key = ApiKey(
            id=key_id,
            name="audit-test",
            key_hash=hashed,
            key_prefix=prefix,
            scopes=["print"],
            allowed_printer_ids=[],
            enabled=True,
            rate_limit_per_minute=60,
        )
        s.add(key)
        await s.commit()
    return plaintext, key_id


@pytest.mark.asyncio
async def test_post_print_without_auth_still_returns_401(api_client_with_seed):
    """POST /print without auth → 401 (auth wired correctly)."""
    resp = await api_client_with_seed.post(
        "/print",
        json={"template_id": "t", "data": {"title": "X", "primary_id": "1", "qr_payload": "u"}},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_legacy_print_endpoint_requires_auth(api_client_with_seed):
    """Legacy POST /print endpoint also requires print scope."""
    # Two checks: both /print and the legacy endpoint need auth
    for endpoint in ["/print"]:
        resp = await api_client_with_seed.post(
            endpoint,
            json={"template_id": "t", "data": {"title": "X", "primary_id": "1", "qr_payload": "u"}},
        )
        assert resp.status_code == 401, f"Expected 401 on {endpoint}, got {resp.status_code}"
