# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""A print-scope API key passed as the URL ``token`` (#281, ADR 0027).

Grocy's label printer webhook calls a fixed URL and sends no headers of its own, so the
key travels in the query string. The rules:

- The token is the value of a **literal** ``token=`` parameter of the raw query string
  (``request.scope["query_string"]``). Only the value is percent-decoded; a parameter
  whose *name* is percent-encoded (``to%6Ben=``) is not a token. This is the same shape
  the log filter in :mod:`app.observability.redact_query` redacts; the filter also hides
  every look-alike this reader refuses (``TOKEN=``, ``;token=``, ``%74oken=``).
- The ``X-Label-Hub-Key`` header is accepted too and wins over the query.
- Every failure of the token itself (missing, malformed, longer than
  ``MAX_TOKEN_LENGTH``, unknown, disabled, expired, wrong) answers one and the same 401
  ``invalid_token``: Grocy shows the answer to its user, who learns nothing about keys.
- A key with the ``read`` scope answers 403 ``insufficient_scope``, a key with the
  ``admin`` scope 403 ``token_scope_too_wide``: an admin key must never live in Grocy's
  config and log. The key's own rate limit applies (429 with ``Retry-After``).
"""

from __future__ import annotations

from urllib.parse import unquote

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    MAX_KEY_LENGTH,
    AuthContext,
    ScopeRefusedError,
    _validate_api_key,
)
from app.db.session import get_session

TOKEN_QUERY_PARAM = "token"
MAX_TOKEN_LENGTH = MAX_KEY_LENGTH  # one limit for the header and the URL token (#321)

_TOKEN_NAME = TOKEN_QUERY_PARAM.encode("ascii")
_REFUSED_SCOPES = frozenset({"admin"})


def _invalid_token() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "error_code": "invalid_token",
            "error_message": "The token is missing or not valid.",
        },
    )


def _query_token(raw_query: bytes) -> str:
    """Value of the first literal ``token=`` parameter, percent-decoded; ``""`` if none."""
    for part in raw_query.split(b"&"):
        name, sep, value = part.partition(b"=")
        if sep and name == _TOKEN_NAME:
            # Only the value is decoded; '+' stays '+' (keys are URL-safe base64).
            return unquote(value.decode("latin-1"), errors="replace")
    return ""


async def require_print_token(
    request: Request,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> AuthContext:
    """Authenticate a print-scope key from ``X-Label-Hub-Key`` or the URL ``token``."""
    token = request.headers.get("X-Label-Hub-Key", "") or _query_token(
        request.scope.get("query_string", b"")
    )
    # bcrypt >= 5 raises on more than 72 bytes; an overlong token never reaches a lookup.
    if not token or len(token) > MAX_TOKEN_LENGTH:
        raise _invalid_token()

    client_ip = request.client.host if request.client else "unknown"
    try:
        return await _validate_api_key(
            session, token, "print", client_ip, refuse_scopes=_REFUSED_SCOPES
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            raise _invalid_token() from None
        raise  # 403 insufficient_scope, 429 rate_limit_exceeded
    except ScopeRefusedError:
        # An admin key must never live in Grocy's config and log.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "token_scope_too_wide",
                "error_message": "Use a key with the print scope for a URL token.",
            },
        ) from None
