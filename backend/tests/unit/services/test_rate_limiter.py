"""Unit tests for in-memory token-bucket rate limiter — Phase 7c Step 5."""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest


def test_rate_limiter_importable():
    from app.services.rate_limiter import RateLimiter
    assert RateLimiter is not None


def test_60_tokens_per_minute_first_60_allowed():
    """First 60 requests with limit=60 should all be allowed."""
    from app.services.rate_limiter import RateLimiter
    limiter = RateLimiter()
    key_id = uuid4()
    for i in range(60):
        result = limiter.check_and_consume(key_id, limit_per_minute=60)
        assert result is True, f"Request {i+1} should be allowed"


def test_61st_request_exceeds_60_limit():
    """61st request with limit=60 should be denied."""
    from app.services.rate_limiter import RateLimiter
    limiter = RateLimiter()
    key_id = uuid4()
    for _ in range(60):
        limiter.check_and_consume(key_id, limit_per_minute=60)
    result = limiter.check_and_consume(key_id, limit_per_minute=60)
    assert result is False, "61st request should be denied"


def test_different_key_ids_have_independent_buckets():
    """Two different key IDs do not share tokens."""
    from app.services.rate_limiter import RateLimiter
    limiter = RateLimiter()
    key_a = uuid4()
    key_b = uuid4()
    # Exhaust key_a
    for _ in range(5):
        limiter.check_and_consume(key_a, limit_per_minute=5)
    result_a = limiter.check_and_consume(key_a, limit_per_minute=5)
    result_b = limiter.check_and_consume(key_b, limit_per_minute=5)
    assert result_a is False, "key_a should be exhausted"
    assert result_b is True, "key_b should have its own tokens"


def test_bucket_refills_over_time():
    """After consuming all tokens, waiting long enough allows new requests."""
    import time
    from app.services.rate_limiter import RateLimiter
    limiter = RateLimiter()
    key_id = uuid4()
    # Use a high rate so we can test quickly: limit=120 = 2/second refill
    # Exhaust all tokens
    for _ in range(120):
        limiter.check_and_consume(key_id, limit_per_minute=120)
    # Immediately denied
    assert limiter.check_and_consume(key_id, limit_per_minute=120) is False
    # Wait 1 second (should get ~2 tokens back)
    time.sleep(1.1)
    assert limiter.check_and_consume(key_id, limit_per_minute=120) is True


def test_retry_after_seconds_when_denied():
    """check_and_consume returns retry_after > 0 seconds when rate-limited."""
    from app.services.rate_limiter import RateLimiter
    limiter = RateLimiter()
    key_id = uuid4()
    for _ in range(60):
        limiter.check_and_consume(key_id, limit_per_minute=60)
    # Should return False and provide retry_after info
    result, retry_after = limiter.check_and_consume_with_retry_after(
        key_id, limit_per_minute=60
    )
    assert result is False
    assert retry_after > 0, f"Expected positive retry_after, got {retry_after}"


def test_retry_after_is_zero_when_allowed():
    from app.services.rate_limiter import RateLimiter
    limiter = RateLimiter()
    key_id = uuid4()
    result, retry_after = limiter.check_and_consume_with_retry_after(
        key_id, limit_per_minute=60
    )
    assert result is True
    assert retry_after == 0
