# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""CSRF protection for requests authenticated by the browser session cookie (spec 8.1).

The session stores a random CSRF token; the browser reads it from the non-HttpOnly
CSRF cookie (or ``GET /api/v1/auth/session``) and sends it back in ``X-CSRF-Token`` on
every state-changing request. Requests authenticated by an API key header are exempt:
browsers never attach that header on their own.
"""

from __future__ import annotations

import hmac
import secrets
from typing import Protocol

from fastapi import HTTPException, Request, status

CSRF_HEADER = "X-CSRF-Token"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class _HasCsrfToken(Protocol):
    csrf_token: str


def new_token() -> str:
    """Return a fresh, URL-safe CSRF token (256 bits)."""
    return secrets.token_urlsafe(32)


def verify(request: Request, session: _HasCsrfToken) -> None:
    """Raise 403 ``csrf_failed`` when a state-changing request lacks the session's token."""
    if request.method.upper() not in UNSAFE_METHODS:
        return
    presented = request.headers.get(CSRF_HEADER, "")
    expected = session.csrf_token or ""
    if (
        not presented
        or not expected
        or not hmac.compare_digest(presented.encode(), expected.encode())
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "csrf_failed",
                "error_message": f"Missing or wrong {CSRF_HEADER} header.",
            },
        )
