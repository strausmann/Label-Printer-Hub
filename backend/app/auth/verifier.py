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
"""

from __future__ import annotations

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
    """
    cache_key = (plaintext, hashed)
    if cache_key in _cache:
        return _cache[cache_key]

    result = bcrypt.checkpw(plaintext.encode(), hashed.encode())
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
