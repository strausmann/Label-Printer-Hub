"""Plain-text cleaning for the free text of the sheet archive (purposes, notes, names).

Removes every control character (Unicode category ``Cc``) and the bidi controls that can
reorder what a person reads (U+061C, U+200E, U+200F, U+202A-U+202E, U+2066-U+2069). Other
format characters (``Cf``) stay on purpose: the zero-width joiner U+200D holds emoji sequences
together, the soft hyphen is harmless. The result is trimmed; longer than ``max_len`` after
cleaning is a ``ValueError`` (the schema reports 422).
"""

from __future__ import annotations

import unicodedata

_BIDI_CONTROLS = frozenset({0x061C, 0x200E, 0x200F, *range(0x202A, 0x202F), *range(0x2066, 0x206A)})


def _keep(ch: str) -> bool:
    return ord(ch) not in _BIDI_CONTROLS and unicodedata.category(ch) != "Cc"


def sanitise_text(value: str, *, max_len: int) -> str:
    cleaned = "".join(ch for ch in value if _keep(ch)).strip()
    if len(cleaned) > max_len:
        raise ValueError(f"longer than {max_len} characters")
    return cleaned
