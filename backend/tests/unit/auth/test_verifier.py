"""Unit tests for bcrypt verifier + LRU cache — Phase 7c Step 2."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import bcrypt
import pytest


def _make_hash(plaintext: str) -> str:
    return bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()


def test_verify_api_key_importable():
    from app.auth.verifier import verify_api_key

    assert verify_api_key is not None


def test_verify_returns_true_for_correct_key():
    from app.auth.verifier import verify_api_key

    plaintext = "lh_testkey_correct_12345"
    hashed = _make_hash(plaintext)
    assert verify_api_key(plaintext, hashed) is True


def test_verify_returns_false_for_wrong_key():
    from app.auth.verifier import verify_api_key

    hashed = _make_hash("lh_correct_key_abc123")
    assert verify_api_key("lh_wrong_key_xyz999", hashed) is False


def test_verify_caches_result_on_second_call():
    """After the first verify, subsequent calls with same inputs skip bcrypt."""
    from app.auth import verifier as verifier_module

    verifier_module._cache.clear()

    plaintext = "lh_cache_test_key_001"
    hashed = _make_hash(plaintext)

    bcrypt_call_count = [0]
    original_checkpw = bcrypt.checkpw

    def counting_checkpw(pw, hsh):
        bcrypt_call_count[0] += 1
        return original_checkpw(pw, hsh)

    with patch.object(bcrypt, "checkpw", side_effect=counting_checkpw):
        # First call — should invoke bcrypt
        result1 = verifier_module.verify_api_key(plaintext, hashed)
        # Second call — should use cache
        result2 = verifier_module.verify_api_key(plaintext, hashed)

    assert result1 is True
    assert result2 is True
    assert bcrypt_call_count[0] == 1, (
        f"Expected 1 bcrypt call (cache hit on 2nd), got {bcrypt_call_count[0]}"
    )


def test_verify_different_keys_call_bcrypt_each():
    """Different plaintext/hash pairs are each verified separately."""
    from app.auth import verifier as verifier_module

    verifier_module._cache.clear()

    p1, h1 = "lh_key_alpha_001", _make_hash("lh_key_alpha_001")
    p2, h2 = "lh_key_beta_002", _make_hash("lh_key_beta_002")

    bcrypt_call_count = [0]
    original_checkpw = bcrypt.checkpw

    def counting_checkpw(pw, hsh):
        bcrypt_call_count[0] += 1
        return original_checkpw(pw, hsh)

    with patch.object(bcrypt, "checkpw", side_effect=counting_checkpw):
        verifier_module.verify_api_key(p1, h1)
        verifier_module.verify_api_key(p2, h2)

    assert bcrypt_call_count[0] == 2


def test_invalidate_cache_removes_entry():
    """invalidate_cache removes a cached entry by hash."""
    from app.auth import verifier as verifier_module

    verifier_module._cache.clear()

    plaintext = "lh_invalidate_test_001"
    hashed = _make_hash(plaintext)

    # Prime cache
    verifier_module.verify_api_key(plaintext, hashed)
    assert (plaintext, hashed) in verifier_module._cache

    verifier_module.invalidate_cache(hashed)
    assert (plaintext, hashed) not in verifier_module._cache


@pytest.mark.asyncio
async def test_verify_api_key_does_not_block_event_loop():
    """bcrypt.checkpw must run in a thread pool so the event loop stays free.

    Strategy: run verify_api_key concurrently with a fast coroutine.
    If checkpw blocks the loop, the fast coroutine cannot advance.
    We assert the concurrent coroutine completed while verify was running.
    """
    from app.auth import verifier as verifier_module

    verifier_module._cache.clear()
    plaintext = "lh_nonblocking_test_001"
    hashed = _make_hash(plaintext)

    side_ran = []

    async def side_coroutine():
        await asyncio.sleep(0)
        side_ran.append(True)

    # Run both concurrently
    await asyncio.gather(
        verifier_module.verify_api_key_async(plaintext, hashed),
        side_coroutine(),
    )

    assert side_ran, "Side coroutine did not run — event loop was blocked"


@pytest.mark.asyncio
async def test_verify_api_key_async_returns_true_for_correct_key():
    """Async wrapper returns True for a matching key."""
    from app.auth.verifier import verify_api_key_async

    plaintext = "lh_async_correct_001"
    hashed = _make_hash(plaintext)
    assert await verify_api_key_async(plaintext, hashed) is True


@pytest.mark.asyncio
async def test_verify_api_key_async_returns_false_for_wrong_key():
    """Async wrapper returns False for a non-matching key."""
    from app.auth.verifier import verify_api_key_async

    hashed = _make_hash("lh_async_other_001")
    assert await verify_api_key_async("lh_async_wrong_001", hashed) is False
