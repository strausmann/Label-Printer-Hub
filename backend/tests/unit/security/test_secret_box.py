# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for the AES-GCM secret box (decision D5)."""

from __future__ import annotations

import base64

import pytest
from app.config import Settings
from app.security.secret_box import SecretBox, UndecryptableSecret, secret_box_from_settings

KEY_A = b"a" * 32
KEY_B = b"b" * 32
AAD = "integrations.snipeit.api_key"


def test_seal_open_roundtrip() -> None:
    box = SecretBox(KEY_A)
    token = box.seal("t0k", aad=AAD)
    assert token.startswith("v1.")
    assert box.open(token, aad=AAD) == "t0k"


def test_open_with_other_aad_fails() -> None:
    box = SecretBox(KEY_A)
    token = box.seal("t0k", aad=AAD)
    with pytest.raises(UndecryptableSecret):
        box.open(token, aad="integrations.grocy.api_key")


def test_open_with_other_key_fails() -> None:
    token = SecretBox(KEY_A).seal("t0k", aad=AAD)
    with pytest.raises(UndecryptableSecret):
        SecretBox(KEY_B).open(token, aad=AAD)


def test_seal_is_randomised() -> None:
    box = SecretBox(KEY_A)
    assert box.seal("t0k", aad=AAD) != box.seal("t0k", aad=AAD)


@pytest.mark.parametrize("token", ["", "garbage", "v2.aa.bb", "v1.only-two", "v1.!!!.???"])
def test_open_malformed_token_fails(token: str) -> None:
    with pytest.raises(UndecryptableSecret):
        SecretBox(KEY_A).open(token, aad=AAD)


def test_open_tampered_ciphertext_fails() -> None:
    box = SecretBox(KEY_A)
    version, nonce, ct = box.seal("t0k", aad=AAD).split(".")
    raw = bytearray(base64.urlsafe_b64decode(ct + "=" * (-len(ct) % 4)))
    raw[0] ^= 0x01
    bad = base64.urlsafe_b64encode(bytes(raw)).decode().rstrip("=")
    with pytest.raises(UndecryptableSecret):
        box.open(f"{version}.{nonce}.{bad}", aad=AAD)


def test_wrong_key_length_rejected() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        SecretBox(b"short")


def test_from_settings_uses_secret_key() -> None:
    raw = b"k" * 32
    key = base64.urlsafe_b64encode(raw).decode()
    settings = Settings(_env_file=None, secret_key=key, public_url="http://localhost:8000")  # type: ignore[arg-type]
    box = secret_box_from_settings(settings)
    assert box.open(SecretBox(raw).seal("v", aad=AAD), aad=AAD) == "v"
