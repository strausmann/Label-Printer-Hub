# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for in-memory token-bucket rate limiter — Phase 7c Step 5."""

from __future__ import annotations

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
        assert result is True, f"Request {i + 1} should be allowed"


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
    result, retry_after = limiter.check_and_consume_with_retry_after(key_id, limit_per_minute=60)
    assert result is False
    assert retry_after > 0, f"Expected positive retry_after, got {retry_after}"


def test_retry_after_is_zero_when_allowed():
    from app.services.rate_limiter import RateLimiter

    limiter = RateLimiter()
    key_id = uuid4()
    result, retry_after = limiter.check_and_consume_with_retry_after(key_id, limit_per_minute=60)
    assert result is True
    assert retry_after == 0


def test_bucket_map_is_bounded_by_max_buckets():
    from app.services.rate_limiter import RateLimiter

    limiter = RateLimiter(max_buckets=100)
    for i in range(1_000):
        limiter.check_and_consume(f"k{i}", limit_per_minute=10)
    assert len(limiter._buckets) <= 100


def test_lru_keeps_recently_used_bucket_and_its_state():
    from app.services.rate_limiter import RateLimiter

    limiter = RateLimiter(max_buckets=3)
    for _ in range(10):
        assert limiter.check_and_consume("busy", limit_per_minute=10)
    assert not limiter.check_and_consume("busy", limit_per_minute=10)  # drained
    for i in range(2):
        limiter.check_and_consume(f"other{i}", limit_per_minute=10)
        limiter.check_and_consume("busy", limit_per_minute=10)  # touch: stays most recent
    assert not limiter.check_and_consume("busy", limit_per_minute=10)  # still drained, not reset


def test_idle_buckets_are_evicted(monkeypatch):
    import app.services.rate_limiter as rl

    clock = [1000.0]
    monkeypatch.setattr(rl.time, "monotonic", lambda: clock[0])
    limiter = rl.RateLimiter(idle_ttl_seconds=600)
    for i in range(50):
        limiter.check_and_consume(f"k{i}", limit_per_minute=10)
    assert len(limiter._buckets) == 50
    clock[0] += 601
    limiter.check_and_consume("fresh", limit_per_minute=10)
    assert list(limiter._buckets) == ["fresh"]


def test_try_consume_takes_all_or_nothing():
    from app.services.rate_limiter import RateLimiter

    rl = RateLimiter()
    assert rl.check_and_consume("k", limit_per_minute=10)  # 9 left
    assert rl.try_consume("k", 5, limit_per_minute=10) == (True, 0, 5)  # 4 left
    allowed, retry_after, taken = rl.try_consume("k", 5, limit_per_minute=10)
    assert not allowed and retry_after >= 1 and taken == 0
    # the refusal took nothing: the 4 left can still be taken
    assert rl.try_consume("k", 4, limit_per_minute=10) == (True, 0, 4)


def test_try_consume_retry_after_covers_the_next_requests_own_token(monkeypatch):
    """A client that waits the given Retry-After must get through: the retried request takes
    its own token at authentication before the fan-out is charged (Codex review on #399)."""
    from app.services import rate_limiter as rl

    clock = [1000.0]
    monkeypatch.setattr(rl.time, "monotonic", lambda: clock[0])
    limiter = rl.RateLimiter()
    for _ in range(5):
        assert limiter.check_and_consume("k", limit_per_minute=10)  # 5 left
    allowed, retry_after, _ = limiter.try_consume("k", 9, limit_per_minute=10)
    assert not allowed
    clock[0] += retry_after
    assert limiter.check_and_consume("k", limit_per_minute=10)  # the retry's own token
    assert limiter.try_consume("k", 9, limit_per_minute=10)[0] is True


def test_try_consume_cap_leaves_room_for_the_requests_own_token():
    """A fresh bucket minus the request's token holds capacity - 1: asking for more than the
    limit must still be servable, or such a request is refused forever (review 1)."""
    from app.services.rate_limiter import RateLimiter

    rl = RateLimiter()
    assert rl.check_and_consume("k", limit_per_minute=5)  # the request's own token: 4 left
    assert rl.try_consume("k", 9, limit_per_minute=5) == (True, 0, 4)  # capped at 4


def test_try_consume_creates_a_missing_bucket_and_charges_it():
    from app.services.rate_limiter import RateLimiter

    rl = RateLimiter()
    assert rl.try_consume("evicted", 3, limit_per_minute=5) == (True, 0, 3)  # 2 left
    assert rl.try_consume("evicted", 3, limit_per_minute=5)[0] is False


def test_try_consume_of_nothing_is_free():
    from app.services.rate_limiter import RateLimiter

    rl = RateLimiter()
    assert rl.try_consume("k", 0, limit_per_minute=5) == (True, 0, 0)
    assert rl.try_consume("k", -1, limit_per_minute=5) == (True, 0, 0)


def test_refund_gives_tokens_back_up_to_capacity():
    from app.services.rate_limiter import RateLimiter

    rl = RateLimiter()
    assert rl.try_consume("k", 4, limit_per_minute=5) == (True, 0, 4)  # 1 left
    rl.refund("k", 4)
    assert rl.try_consume("k", 4, limit_per_minute=5) == (True, 0, 4)  # all 4 back, none lost
    rl.refund("k", 100)  # never above the capacity
    assert rl.try_consume("k", 4, limit_per_minute=5) == (True, 0, 4)
    assert rl.try_consume("k", 4, limit_per_minute=5)[0] is False
    rl.refund("missing", 3)  # no bucket, nothing to do


def test_refund_gives_back_exactly_what_was_taken_when_the_limit_changed():
    """The key's limit is edited between charge and refund (mint attempt): the bucket follows
    the new limit, never ends above its capacity, and never above what it held before."""
    from app.services.rate_limiter import RateLimiter

    rl = RateLimiter()
    assert rl.check_and_consume("k", limit_per_minute=50)  # 49 left
    allowed, _, taken = rl.try_consume("k", 40, limit_per_minute=50)  # 9 left
    assert allowed and taken == 40
    # An admin lowers the limit to 5; the next use resizes the bucket (9 -> 5, clamped).
    assert rl.try_consume("k", 0, limit_per_minute=5) == (True, 0, 0)
    bucket = rl._buckets["k"]
    assert bucket.capacity == 5 and bucket.tokens <= 5
    rl.refund("k", taken)  # exactly the 40 taken, but never above the capacity
    assert bucket.tokens == 5.0
    # ... which is not more than the 49 it held before the charge, and a recomputed refund of
    # min(lookups - 1, new_limit - 1) = 4 could not have been distinguished here; so also check
    # the raised-limit direction: raising the limit never tops the bucket up.
    rl2 = RateLimiter()
    assert rl2.check_and_consume("j", limit_per_minute=10)  # 9 left
    _, _, took = rl2.try_consume("j", 9, limit_per_minute=10)  # 0 left
    assert took == 9
    assert rl2.try_consume("j", 0, limit_per_minute=1000) == (True, 0, 0)
    assert rl2._buckets["j"].tokens < 1.0  # raised limit did not mint tokens
    rl2.refund("j", took)
    assert rl2._buckets["j"].tokens == pytest.approx(9.0, abs=0.5)


def test_charge_returns_what_was_taken_and_refund_restores_exactly_that():
    from uuid import uuid4

    from app.auth.dependencies import AuthContext, charge_lookup_fan_out, refund_lookup_fan_out
    from app.services.rate_limiter import _rate_limiter

    key = uuid4()
    ctx = AuthContext(
        source="api-key", scope="print", api_key_id=key, ip="x", rate_limit_per_minute=100
    )
    try:
        assert _rate_limiter.check_and_consume(key, limit_per_minute=100)  # the request's token
        before = _rate_limiter._buckets[key].tokens
        taken = charge_lookup_fan_out(ctx, 30)
        assert taken == 29
        # the limit drops to 10 before the refund: the context still says 100
        _rate_limiter.try_consume(key, 0, limit_per_minute=10)
        refund_lookup_fan_out(ctx, taken)
        bucket = _rate_limiter._buckets[key]
        assert bucket.tokens <= bucket.capacity == 10
        assert bucket.tokens <= before
    finally:
        _rate_limiter.reset(key)


def test_refund_never_exceeds_the_charge():
    """30 lookups on a limit of 10 take only 9 tokens (the cap). Refunding the 29 asked for
    instead of the 9 taken would end above the bucket's state before the charge."""
    from uuid import uuid4

    from app.auth.dependencies import AuthContext, charge_lookup_fan_out, refund_lookup_fan_out
    from app.services.rate_limiter import _rate_limiter

    key = uuid4()
    ctx = AuthContext(
        source="api-key", scope="print", api_key_id=key, ip="x", rate_limit_per_minute=10
    )
    try:
        assert _rate_limiter.check_and_consume(key, limit_per_minute=10)  # 9 left
        before = _rate_limiter._buckets[key].tokens
        taken = charge_lookup_fan_out(ctx, 30)
        assert taken == 9
        refund_lookup_fan_out(ctx, taken)
        assert _rate_limiter._buckets[key].tokens <= before + 0.1
    finally:
        _rate_limiter.reset(key)
