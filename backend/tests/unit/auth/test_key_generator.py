"""Unit tests for API key generation — Phase 7c Step 2.

RED phase: these tests must fail before key_generator.py exists.
"""

from __future__ import annotations

import bcrypt


def test_generate_api_key_importable():
    """generate_api_key is importable from app.auth.key_generator."""
    from app.auth.key_generator import generate_api_key

    assert generate_api_key is not None


def test_generate_api_key_returns_three_tuple():
    from app.auth.key_generator import generate_api_key

    result = generate_api_key()
    assert len(result) == 3


def test_plaintext_starts_with_lh_pat_prefix():
    from app.auth.key_generator import generate_api_key

    plaintext, _, _ = generate_api_key()
    assert plaintext.startswith("lh_pat_"), f"Expected lh_pat_ prefix, got: {plaintext[:10]}"


def test_prefix_is_first_16_chars_of_plaintext():
    from app.auth.key_generator import generate_api_key

    plaintext, prefix, _ = generate_api_key()
    assert prefix == plaintext[:16], f"prefix={prefix!r}, plaintext[:16]={plaintext[:16]!r}"


def test_prefix_is_exactly_16_chars():
    from app.auth.key_generator import generate_api_key

    _, prefix, _ = generate_api_key()
    assert len(prefix) == 16, f"Expected 16 chars, got {len(prefix)}"


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
    """Characters after lh_pat_ prefix should be URL-safe (no +, /, =)."""
    from app.auth.key_generator import generate_api_key

    for _ in range(5):
        plaintext, _, _ = generate_api_key()
        body = plaintext[7:]  # strip "lh_pat_"
        assert "+" not in body and "/" not in body and "=" not in body, (
            f"Non-URL-safe chars in plaintext body: {body}"
        )


def test_plaintext_has_sufficient_entropy():
    """Plaintext body should be at least 43 chars (32 bytes base64url ≈ 43 chars)."""
    from app.auth.key_generator import generate_api_key

    plaintext, _, _ = generate_api_key()
    body = plaintext[7:]  # strip "lh_pat_"
    assert len(body) >= 43, f"Body too short for 256-bit entropy: {len(body)} chars"
