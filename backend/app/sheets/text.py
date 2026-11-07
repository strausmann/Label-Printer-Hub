"""Plain-text cleaning for the free text of the sheet archive (purposes, notes, names).

Line breaks (CRLF, CR, LF) become ``\\n``. A ``multiline`` field (notes, descriptions, change
notes) keeps ``\\n``; every other field turns a run of whitespace that holds a line break or a
tab into one space, so words are never glued together. A tab is a space in both kinds.

Removes every other control character (Unicode category ``Cc``) and the bidi controls that can
reorder what a person reads (U+061C, U+200E, U+200F, U+202A-U+202E, U+2066-U+2069). Other
format characters (``Cf``) stay on purpose: the zero-width joiner U+200D holds emoji sequences
together, the soft hyphen is harmless. The result is trimmed; longer than ``max_len`` after
cleaning is a ``ValueError`` (the schema reports 422).
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse

_BIDI_CONTROLS = frozenset({0x061C, 0x200E, 0x200F, *range(0x202A, 0x202F), *range(0x2066, 0x206A)})


_WHITESPACE_RUN = re.compile(r"[ \t\n]+")  # one quantifier, no overlap: linear
_INPUT_FACTOR = 4  # input longer than this many times ``max_len`` is refused unprocessed


def _collapse_breaks(match: re.Match[str]) -> str:
    run = match.group()
    return " " if "\t" in run or "\n" in run else run


def _keep(ch: str) -> bool:
    return ch == "\n" or (ord(ch) not in _BIDI_CONTROLS and unicodedata.category(ch) != "Cc")


def sanitise_text(value: str, *, max_len: int, multiline: bool = False) -> str:
    """Clean ``value``; ``multiline`` keeps line breaks, otherwise they become a space."""
    if len(value) > _INPUT_FACTOR * max_len:  # before any work on the text
        raise ValueError(f"longer than {max_len} characters")
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\t", " ") if multiline else _WHITESPACE_RUN.sub(_collapse_breaks, text)
    cleaned = "".join(ch for ch in text if _keep(ch)).strip()
    if len(cleaned) > max_len:
        raise ValueError(f"longer than {max_len} characters")
    return cleaned


def check_http_url(value: str) -> str:
    """Only http(s) URLs without control characters; shared by import, the API and the service."""
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("only http and https URLs are allowed")
    if any(ch.isspace() or ord(ch) < 32 for ch in value):
        raise ValueError("control characters are not allowed")
    return value


_LOG_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")


def log_value(value: object) -> str:
    """Return ``value`` as one log-safe line: CR, LF and every other control character removed
    (C0, DEL, C1, line and paragraph separator), so it cannot forge or hide a log entry."""
    return _LOG_CONTROL.sub("", str(value).replace("\r", "").replace("\n", ""))
