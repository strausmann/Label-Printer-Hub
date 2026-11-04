"""AES-256-GCM box for secrets stored in the database.

D5: secrets are encrypted with PRINTER_HUB_SECRET_KEY and are write-only in the UI.

Token format: ``v1.<b64url nonce>.<b64url ciphertext>``. The associated data is the
setting key of the record (for example ``integrations.snipeit.api_key``), so a
ciphertext copied to another record does not open.
"""

from __future__ import annotations

import base64
import binascii
import os
from typing import TYPE_CHECKING

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

if TYPE_CHECKING:
    from app.config import Settings

_VERSION = "v1"
_NONCE_BYTES = 12
_KEY_BYTES = 32


class UndecryptableSecret(Exception):  # noqa: N818 - public name fixed by the spec
    """The stored token cannot be opened (wrong key, wrong AAD, or damaged)."""


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class SecretBox:
    def __init__(self, key: bytes) -> None:
        if len(key) != _KEY_BYTES:
            raise ValueError("secret key must be exactly 32 bytes")
        self._aead = AESGCM(key)

    def seal(self, plaintext: str, *, aad: str) -> str:
        nonce = os.urandom(_NONCE_BYTES)
        ct = self._aead.encrypt(nonce, plaintext.encode("utf-8"), aad.encode("utf-8"))
        return f"{_VERSION}.{_b64e(nonce)}.{_b64e(ct)}"

    def open(self, token: str, *, aad: str) -> str:
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != _VERSION:
            raise UndecryptableSecret("unsupported or malformed secret token")
        try:
            nonce = _b64d(parts[1])
            ct = _b64d(parts[2])
            return self._aead.decrypt(nonce, ct, aad.encode("utf-8")).decode("utf-8")
        except (binascii.Error, ValueError, InvalidTag) as exc:
            raise UndecryptableSecret("secret cannot be decrypted") from exc


def secret_box_from_settings(settings: Settings) -> SecretBox:
    return SecretBox(_b64d(settings.secret_key.get_secret_value()))
