"""API key generation for Phase 7c — generates bcrypt-hashed keys with prefix.

Key format: ``lh_pat_<43-char-urlsafe-base64>``
  - ``lh_pat_`` — Label Hub Personal Access Token infix, unambiguously
    identifies token type for both humans and secret-scanning tools
  - 43-char body — secrets.token_urlsafe(32) produces ~43 URL-safe chars
    from 256 bits of entropy (no padding)

The plaintext is returned only at generation time and must be shown to the
user ONCE. Only the bcrypt hash and the 16-char prefix are persisted.
"""

from __future__ import annotations

import secrets

import bcrypt

# bcrypt work factor: 12 rounds is the 2024-2026 industry default (~100-200ms on
# modern hardware). Deliberately slow to resist offline brute-force attacks.
_BCRYPT_ROUNDS = 12


def generate_api_key() -> tuple[str, str, str]:
    """Generate a new API key.

    Returns:
        (plaintext, prefix, bcrypt_hash) where:
        - plaintext — the full key, shown to the user ONCE, never persisted
        - prefix    — first 16 chars (e.g. "lh_pat_ab12cd34X"), stored for UI display
        - bcrypt_hash — stored in the DB, used for verify_api_key()
    """
    body = secrets.token_urlsafe(32)  # 256 bits of entropy, URL-safe charset
    plaintext = f"lh_pat_{body}"
    prefix = plaintext[:16]
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode()
    return plaintext, prefix, hashed
