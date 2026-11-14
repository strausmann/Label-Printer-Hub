"""Hide the URL ``token`` in uvicorn's log records (#281, R-281-2, ADR 0027).

Grocy's label printer webhook carries a print-scope API key as ``?token=…`` in the URL,
and uvicorn writes the full request line to ``uvicorn.access`` (and parts of it to
``uvicorn.error`` for a malformed request). This filter rewrites the record before any
handler sees it: the value of every ``token=`` parameter becomes ``***`` (any case,
``&``/``?``/``;`` separated, also with a percent-encoded name), and so does any value in
the shape of a hub API key, in the message and in every string argument.

A filter on a logger runs in ``Logger.handle`` before the record is passed to any handler,
including the handlers of parent loggers it propagates to (the root logger's log buffer).
A record logged on a *child* of these loggers would not pass through it; uvicorn logs on
these two names only.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

# A superset of what require_print_token accepts: the reader takes only a literal
# "token=", but an operator may mistype the name (TOKEN=, %74oken=, %54oken=) or use ";"
# as a separator. The key is live either way, so every look-alike is hidden too.


def _letter(ch: str) -> str:
    """One name letter: itself or its percent code, lower or upper case, once or twice
    encoded (``t`` -> ``t``, ``%74``, ``%54``, ``%2574``, ``%2554``; hex in any case)."""
    lower, upper = ord(ch.lower()), ord(ch.upper())
    hexes = "|".join(sorted({f"{lower:02x}", f"{upper:02x}"}))
    return f"(?:{ch}|%(?:25)?(?:{hexes}))"


_TOKEN_VALUE = re.compile(
    r"(?<=[?&;])" + "".join(_letter(c) for c in "token") + r"=[^&;\s\"]*",
    re.IGNORECASE,
)
# Any value in the shape of a hub API key, wherever it appears in the line, also with
# percent-encoded characters inside (lh%5Fpat%5F..., %2D, double-encoded %255F).
_PCT = r"%(?:25)?[0-9a-f]{2}"
_KEY_SHAPE = re.compile(
    rf"lh(?:_|%(?:25)?5f)pat(?:_|%(?:25)?5f)(?:[A-Za-z0-9_-]|{_PCT}){{8,}}",
    re.IGNORECASE,
)
_LOGGERS = ("uvicorn.access", "uvicorn.error")


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        value = _TOKEN_VALUE.sub(lambda m: m.group(0).split("=", 1)[0] + "=***", value)
        value = _KEY_SHAPE.sub("lh_pat_***", value)
    return value


class QueryTokenRedactor(logging.Filter):
    """Replace every ``token=`` look-alike value and every key-shaped value with ``***``."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact(record.msg)
        args = record.args
        if isinstance(args, tuple):
            record.args = tuple(_redact(a) for a in args)
        elif isinstance(args, Mapping):
            record.args = {k: _redact(v) for k, v in args.items()}
        return True


def install_query_token_redaction() -> None:
    """Attach one redactor to ``uvicorn.access`` and ``uvicorn.error`` (idempotent)."""
    for name in _LOGGERS:
        logger = logging.getLogger(name)
        if not any(isinstance(f, QueryTokenRedactor) for f in logger.filters):
            logger.addFilter(QueryTokenRedactor())
