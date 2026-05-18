"""bcrypt verifier with LRU cache to avoid slow re-verification on every request.

bcrypt.checkpw takes ~100-200ms per call (by design — work factor 12).  For a
HomeLab with a handful of keys and hundreds of requests per day this is fine,
but for interactive use (frontend page loads doing multiple API calls) it would
be noticeable.

The LRU cache keyed on (plaintext, hash) avoids repeated bcrypt rounds for the
same key within the TTL window.  The cache is invalidated explicitly when a key
is revoked or updated.

Cache design:
  - Key:   (plaintext, hashed) — using both avoids cache-poisoning if two keys
           happen to share a prefix
  - Value: bool (True=valid, False=invalid)
  - Size:  maxsize=512 (sufficient for HomeLab, tiny memory footprint)
  - TTL:   300 seconds (5 minutes) — after expiry the next call re-verifies

Thread-safety: cachetools.TTLCache is NOT thread-safe, so we use an explicit
asyncio-compatible pattern (single event loop = single thread for FastAPI).
For multi-process deployments an external cache would be needed (out of scope
for HomeLab single-instance design per spec Section 5).

Async design: bcrypt.checkpw is CPU-intensive (~100-200ms).  Calling it
directly inside an ``async def`` blocks the event loop and prevents other
coroutines from running.  ``verify_api_key_async`` offloads the work to a
thread pool via ``asyncio.to_thread``, keeping the loop free.  The cache
check/write still happens on the event-loop thread (single-threaded, no lock
needed for in-process use).
"""

from __future__ import annotations

import asyncio

import bcrypt
from cachetools import TTLCache

# _cache is module-level so test code can inspect/clear it
_cache: TTLCache[tuple[str, str], bool] = TTLCache(maxsize=512, ttl=300)


def verify_api_key(plaintext: str, hashed: str) -> bool:
    """Return True if ``plaintext`` matches the bcrypt ``hashed`` value.

    Results are cached for ``ttl`` seconds (default 300s / 5 minutes) to avoid
    repeated expensive bcrypt verifications.

    Args:
        plaintext: The full API key as provided in the ``X-Label-Hub-Key`` header.
        hashed:    The bcrypt hash stored in the DB.

    Returns:
        True if the key is valid, False otherwise.

    Note:
        This is a synchronous helper.  In async contexts prefer
        ``verify_api_key_async`` to avoid blocking the event loop.
    """
    cache_key = (plaintext, hashed)
    if cache_key in _cache:
        return _cache[cache_key]

    result = bcrypt.checkpw(plaintext.encode(), hashed.encode())
    _cache[cache_key] = result
    return result


async def verify_api_key_async(plaintext: str, hashed: str) -> bool:
    """Async wrapper around ``verify_api_key`` that offloads bcrypt to a thread.

    bcrypt.checkpw is CPU-intensive (~100-200ms).  Running it on the event-loop
    thread would block all other coroutines for that duration.  This wrapper:

    1. Checks the TTL cache first (fast, on the loop thread).
    2. If a cache miss, runs bcrypt.checkpw in a thread pool via
       ``asyncio.to_thread``, freeing the loop for other work.
    3. Writes the result back to the cache (on the loop thread after await).

    Args:
        plaintext: The full API key as provided in the ``X-Label-Hub-Key`` header.
        hashed:    The bcrypt hash stored in the DB.

    Returns:
        True if the key is valid, False otherwise.
    """
    cache_key = (plaintext, hashed)
    if cache_key in _cache:
        return _cache[cache_key]

    result = await asyncio.to_thread(bcrypt.checkpw, plaintext.encode(), hashed.encode())
    _cache[cache_key] = result
    return result


def invalidate_cache(hashed: str) -> None:
    """Remove all cache entries for a given hash (e.g. after key revocation).

    Called when a key is revoked or the hash changes so that subsequent
    requests re-verify against the DB rather than getting a stale cache hit.
    """
    keys_to_remove = [k for k in list(_cache.keys()) if k[1] == hashed]
    for k in keys_to_remove:
        _cache.pop(k, None)
