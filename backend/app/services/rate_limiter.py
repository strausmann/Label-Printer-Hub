# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

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
from collections import OrderedDict
from collections.abc import Hashable

MAX_BUCKETS = 10_000
IDLE_TTL_SECONDS = 600.0


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
    """Global in-memory rate limiter — one token bucket per key (API-key id, client IP)."""

    def __init__(
        self, *, max_buckets: int = MAX_BUCKETS, idle_ttl_seconds: float = IDLE_TTL_SECONDS
    ) -> None:
        # Least recently used first. Bounded: keys can come from the network.
        self._buckets: OrderedDict[Hashable, _TokenBucket] = OrderedDict()
        self._max_buckets = max_buckets
        self._idle_ttl = idle_ttl_seconds

    def _evict(self) -> None:
        """Drop idle buckets (a full bucket is indistinguishable from a new one), then LRU."""
        now = time.monotonic()
        while self._buckets:
            oldest = next(iter(self._buckets.values()))
            if now - oldest.last_refill <= self._idle_ttl:
                break
            self._buckets.popitem(last=False)
        while len(self._buckets) > self._max_buckets:
            self._buckets.popitem(last=False)

    def _get_bucket(self, key_id: Hashable, limit_per_minute: int) -> _TokenBucket:
        """Return (and lazily create) the bucket for this key; mark it most recently used."""
        self._evict()
        bucket = self._buckets.get(key_id)
        if bucket is None:
            bucket = _TokenBucket(limit_per_minute)
            self._buckets[key_id] = bucket
            self._evict()  # room for the new entry (at most max_buckets afterwards)
        else:
            self._buckets.move_to_end(key_id)
            if bucket.capacity != limit_per_minute:
                # The key's limit was edited: the bucket follows. Tokens are only ever clamped
                # down, never topped up, so changing a limit cannot mint tokens.
                bucket.capacity = limit_per_minute
                bucket.tokens = min(bucket.tokens, float(limit_per_minute))
        return bucket

    def check_and_consume(self, key_id: Hashable, *, limit_per_minute: int) -> bool:
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
        self, key_id: Hashable, *, limit_per_minute: int
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

    def try_consume(
        self, key_id: Hashable, tokens: int, *, limit_per_minute: int
    ) -> tuple[bool, int, int]:
        """Take ``tokens`` at once from the key's bucket, or none (all or nothing).

        Charges work a request fans out into, on top of the token the request itself took
        (which pays for the first lookup). The bucket is created when it was evicted, so the
        charge is never skipped. ``tokens`` is capped at ``capacity - 1``: the request's own
        token is already gone, so a full bucket holds at most that, and a larger ask would be
        refused forever. Returns ``(allowed, retry_after_seconds, taken)``; ``taken`` is exactly
        what was removed from the bucket, and the only amount :meth:`refund` should give back.
        """
        rate_per_second = limit_per_minute / 60.0
        bucket = self._get_bucket(key_id, limit_per_minute)
        needed = min(tokens, bucket.capacity - 1)
        if needed <= 0:
            return True, 0, 0
        bucket.refill(rate_per_second)
        if bucket.tokens >= needed:
            bucket.tokens -= needed
            return True, 0, needed
        # The retried request takes its own token at authentication before it is charged again,
        # so the wait covers that token too; otherwise a client that follows Retry-After finds
        # the refill eaten by its own request and is refused again (Codex review on #399).
        # ``needed`` <= capacity - 1, so ``needed + 1`` always fits in a full bucket.
        deficit = needed + 1 - bucket.tokens
        return False, int(deficit / rate_per_second) + 1, 0

    def refund(self, key_id: Hashable, tokens: int) -> None:
        """Give back ``tokens`` that :meth:`try_consume` reported as taken, never above the
        bucket's current capacity. A missing (evicted) bucket starts full anyway."""
        bucket = self._buckets.get(key_id)
        if bucket is not None and tokens > 0:
            bucket.tokens = min(float(bucket.capacity), bucket.tokens + tokens)

    def reset(self, key_id: Hashable) -> None:
        """Remove the bucket for a key (e.g. after key revocation)."""
        self._buckets.pop(key_id, None)

    def clear(self) -> None:
        """Drop every bucket (tests, or a full reset)."""
        self._buckets.clear()


# Module-level singleton — shared across all requests in the process, keyed by API-key id
_rate_limiter = RateLimiter()

# Separate bucket for the browser sign-in route, keyed by client IP (spec 8.1).
# The limit itself is ``Settings.sign_in_limit_per_minute`` (default 10).
_sign_in_rate_limiter = RateLimiter()
