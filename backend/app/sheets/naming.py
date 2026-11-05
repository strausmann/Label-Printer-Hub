"""Derivation of sheet type keys and code prefixes from vendor and product code."""

from __future__ import annotations

import re

from app.sheets.geometry import Geometry

KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
PREFIX_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")
_PACK_SUFFIX = re.compile(r"-\d+$")
_REV_SUFFIX = re.compile(r"REV$")
_QR_MIN_SIDE_HMM = 1500


def derive_prefix(vendor: str, first_code: str) -> str:
    code = _PACK_SUFFIX.sub("", first_code.strip().upper())
    code = _REV_SUFFIX.sub("", code)
    code = re.sub(r"[^A-Z0-9]", "", code)
    if code and code[0].isdigit():
        letters = re.sub(r"[^A-Za-z]", "", vendor)
        if not letters:
            raise ValueError("vendor has no letter to prefix a numeric code")
        code = letters[0].upper() + code
    if not PREFIX_PATTERN.match(code):
        raise ValueError(f"cannot derive a valid prefix from {first_code!r}")
    return code


def derive_key(vendor: str, first_code: str) -> str:
    base = _PACK_SUFFIX.sub("", first_code.strip())
    key = re.sub(r"[^a-z0-9]+", "-", f"{vendor} {base}".lower()).strip("-")
    if not KEY_PATTERN.match(key):
        raise ValueError(f"cannot derive a valid key from {vendor!r} {first_code!r}")
    return key


def default_allow_qr(g: Geometry) -> bool:
    """A QR code is allowed by default when the shorter label side is at least 15 mm."""
    return min(g.label_w, g.label_h) >= _QR_MIN_SIDE_HMM  # OC-28
