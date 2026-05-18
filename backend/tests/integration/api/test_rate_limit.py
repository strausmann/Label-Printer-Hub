"""Integration tests for per-key rate limiting — Phase 7c Step 5.

Tests the 429 response when a key exceeds its rate limit.
Uses a small rate limit (3 req/min) to avoid slow tests.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import app.models  # noqa: F401
import bcrypt
import pytest
from app.models.api_key import ApiKey

_SEED_DIR = Path(__file__).parents[3] / "app" / "seed" / "templates"


async def _insert_key(factory, *, rate_limit: int = 3, scopes=None):
    """Insert an API key with the given rate limit and return plaintext."""
    plaintext = f"lh_ratelimit_test_{uuid4().hex[:20]}"
    prefix = plaintext[:12]
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    async with factory() as s:
        key = ApiKey(
            name="rate-limit-test",
            key_hash=hashed,
            key_prefix=prefix,
            scopes=scopes or ["read"],
            allowed_printer_ids=[],
            enabled=True,
            rate_limit_per_minute=rate_limit,
        )
        s.add(key)
        await s.commit()
    return plaintext


@pytest.mark.asyncio
async def test_429_after_rate_limit_exceeded(api_client_with_seed):
    """After limit+1 requests, the response should be 429."""
    import app.db.engine as _engine_module

    factory = _engine_module.async_session
    plaintext = await _insert_key(factory, rate_limit=3)

    # First 3 requests should succeed (or 200-level)
    for i in range(3):
        resp = await api_client_with_seed.get(
            "/api/printers",
            headers={"X-Label-Hub-Key": plaintext},
        )
        assert resp.status_code in (200, 404), (
            f"Request {i + 1} should succeed, got {resp.status_code}: {resp.text}"
        )

    # 4th request should be rate-limited
    resp = await api_client_with_seed.get(
        "/api/printers",
        headers={"X-Label-Hub-Key": plaintext},
    )
    assert resp.status_code == 429, f"Expected 429, got {resp.status_code}: {resp.text}"


@pytest.mark.asyncio
async def test_429_body_has_correct_error_code(api_client_with_seed):
    """429 response body has error_code = rate_limit_exceeded."""
    import app.db.engine as _engine_module

    factory = _engine_module.async_session
    plaintext = await _insert_key(factory, rate_limit=2)

    for _ in range(2):
        await api_client_with_seed.get(
            "/api/printers",
            headers={"X-Label-Hub-Key": plaintext},
        )

    resp = await api_client_with_seed.get(
        "/api/printers",
        headers={"X-Label-Hub-Key": plaintext},
    )
    assert resp.status_code == 429
    body = resp.json()
    detail = body.get("detail", {})
    assert detail.get("error_code") == "rate_limit_exceeded"


@pytest.mark.asyncio
async def test_429_response_has_retry_after_header(api_client_with_seed):
    """429 response includes Retry-After header."""
    import app.db.engine as _engine_module

    factory = _engine_module.async_session
    plaintext = await _insert_key(factory, rate_limit=2)

    for _ in range(2):
        await api_client_with_seed.get(
            "/api/printers",
            headers={"X-Label-Hub-Key": plaintext},
        )

    resp = await api_client_with_seed.get(
        "/api/printers",
        headers={"X-Label-Hub-Key": plaintext},
    )
    assert resp.status_code == 429
    assert "retry-after" in [h.lower() for h in resp.headers], (
        f"Missing Retry-After header. Headers: {dict(resp.headers)}"
    )
    retry_after = int(resp.headers.get("retry-after", 0))
    assert retry_after > 0, f"Retry-After should be > 0, got {retry_after}"
