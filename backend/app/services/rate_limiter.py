"""In-memory token-bucket rate limiter — Phase 7c Step 5.

Single-instance design (no Redis): suitable for HomeLab single-process
deployment.  Bucket state is lost on restart (gives an extra "free" minute).

Algorithm: token bucket
  - capacity = limit_per_minute tokens
  - refill rate = limit_per_minute / 60 tokens/second
  - consume 1 token per allowed request
"""

from __future__ import annotations

import time
from uuid import UUID


class _TokenBucket:
    """Per-key token bucket tracking consumed tokens and last refill timestamp."""

    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self.tokens: float = float(capacity)  # start full
        self.last_refill: float = time.monotonic()

    def refill(self, rate_per_second: float) -> None:
        """Add tokens based on elapsed time since last refill, capped at capacity."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * rate_per_second)
        self.last_refill = now


class RateLimiter:
    """Global in-memory rate limiter — one token bucket per API key."""

    def __init__(self) -> None:
        self._buckets: dict[UUID, _TokenBucket] = {}

    def _get_bucket(self, key_id: UUID, limit_per_minute: int) -> _TokenBucket:
        """Return (and lazily create) the bucket for this key."""
        if key_id not in self._buckets:
            self._buckets[key_id] = _TokenBucket(limit_per_minute)
        return self._buckets[key_id]

    def check_and_consume(self, key_id: UUID, *, limit_per_minute: int) -> bool:
        """Check if the key is within its rate limit and consume one token.

        Returns True if the request is allowed (token consumed), False if
        the bucket is empty (rate limit exceeded).
        """
        rate_per_second = limit_per_minute / 60.0
        bucket = self._get_bucket(key_id, limit_per_minute)
        bucket.refill(rate_per_second)
        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return True
        return False

    def check_and_consume_with_retry_after(
        self, key_id: UUID, *, limit_per_minute: int
    ) -> tuple[bool, int]:
        """Like check_and_consume but also returns retry_after_seconds.

        Returns (allowed: bool, retry_after_seconds: int) where retry_after
        is 0 if the request is allowed, or the number of seconds until the
        next token is available.
        """
        rate_per_second = limit_per_minute / 60.0
        bucket = self._get_bucket(key_id, limit_per_minute)
        bucket.refill(rate_per_second)
        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return True, 0
        # Calculate when next token will be available
        deficit = 1.0 - bucket.tokens
        retry_after = int(deficit / rate_per_second) + 1
        return False, retry_after

    def reset(self, key_id: UUID) -> None:
        """Remove the bucket for a key (e.g. after key revocation)."""
        self._buckets.pop(key_id, None)


# Module-level singleton — shared across all requests in the process
_rate_limiter = RateLimiter()
