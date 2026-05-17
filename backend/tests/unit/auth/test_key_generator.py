"""Unit tests for API key generation — Phase 7c Step 2.

RED phase: these tests must fail before key_generator.py exists.
"""

from __future__ import annotations

import bcrypt
import pytest


def test_generate_api_key_importable():
    """generate_api_key is importable from app.auth.key_generator."""
    from app.auth.key_generator import generate_api_key  # noqa: F401
    assert generate_api_key is not None


def test_generate_api_key_returns_three_tuple():
    from app.auth.key_generator import generate_api_key
    result = generate_api_key()
    assert len(result) == 3


def test_plaintext_starts_with_lh_prefix():
    from app.auth.key_generator import generate_api_key
    plaintext, _, _ = generate_api_key()
    assert plaintext.startswith("lh_"), f"Expected lh_ prefix, got: {plaintext[:5]}"


def test_prefix_is_first_12_chars_of_plaintext():
    from app.auth.key_generator import generate_api_key
    plaintext, prefix, _ = generate_api_key()
    assert prefix == plaintext[:12], f"prefix={prefix!r}, plaintext[:12]={plaintext[:12]!r}"


def test_prefix_is_exactly_12_chars():
    from app.auth.key_generator import generate_api_key
    _, prefix, _ = generate_api_key()
    assert len(prefix) == 12, f"Expected 12 chars, got {len(prefix)}"


def test_bcrypt_hash_verifies_against_plaintext():
    from app.auth.key_generator import generate_api_key
    plaintext, _, hashed = generate_api_key()
    assert bcrypt.checkpw(plaintext.encode(), hashed.encode()), (
        "bcrypt.checkpw failed — hash does not match plaintext"
    )


def test_bcrypt_hash_rejects_wrong_plaintext():
    from app.auth.key_generator import generate_api_key
    _, _, hashed = generate_api_key()
    assert not bcrypt.checkpw(b"wrong_key", hashed.encode())


def test_generate_produces_unique_keys():
    """10 consecutive calls produce unique plaintexts (collision probability negligible)."""
    from app.auth.key_generator import generate_api_key
    plaintexts = [generate_api_key()[0] for _ in range(10)]
    assert len(set(plaintexts)) == 10, "Duplicate keys detected in 10 generations"


def test_plaintext_body_is_urlsafe():
    """Characters after lh_ prefix should be URL-safe (no +, /, =)."""
    from app.auth.key_generator import generate_api_key
    for _ in range(5):
        plaintext, _, _ = generate_api_key()
        body = plaintext[3:]  # strip "lh_"
        assert "+" not in body and "/" not in body and "=" not in body, (
            f"Non-URL-safe chars in plaintext body: {body}"
        )


def test_plaintext_has_sufficient_entropy():
    """Plaintext body should be at least 43 chars (32 bytes base64url ≈ 43 chars)."""
    from app.auth.key_generator import generate_api_key
    plaintext, _, _ = generate_api_key()
    body = plaintext[3:]
    assert len(body) >= 43, f"Body too short for 256-bit entropy: {len(body)} chars"
