"""Hide the URL ``token`` in uvicorn's log records (#281, R-281-2, ADR 0027).

Grocy's label printer webhook carries a print-scope API key as ``?token=…`` in the URL,
and uvicorn writes the full request line to ``uvicorn.access`` (and parts of it to
``uvicorn.error`` for a malformed request). This filter rewrites the record before any
handler sees it: the value of every literal ``token=`` parameter becomes ``***``, in the
message and in every string argument.

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

# Same shape as require_print_token reads: a literal parameter name after '?' or '&'.
_TOKEN_VALUE = re.compile(r"(?<=[?&])token=[^&\s\"]*")
_REDACTED = "token=***"
_LOGGERS = ("uvicorn.access", "uvicorn.error")


def _redact(value: Any) -> Any:
    if isinstance(value, str) and "token=" in value:
        return _TOKEN_VALUE.sub(_REDACTED, value)
    return value


class QueryTokenRedactor(logging.Filter):
    """Replace the value of each literal ``token=`` query parameter with ``***``."""

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
