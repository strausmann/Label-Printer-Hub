"""Browser sign-in for the web UI (spec 8.1, 8.2; D7, D10).

Routes
------
POST   /api/v1/auth/session — sign in with an API key (``print``/``admin`` scope) or the
                              one-time bootstrap key; sets the session + CSRF cookies.
GET    /api/v1/auth/session — current sign-in state; mints a session from trusted SSO
                              headers (trust token only) when no session cookie exists.
DELETE /api/v1/auth/session — sign out: revokes the session and clears the cookies.

POST and GET are public by design (they are the sign-in itself and the probe the UI
uses before it has a session). POST is rate limited per client IP. GET returns no
data beyond the caller's own sign-in state.
"""

from __future__ import annotations

import hmac
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import sessions as ui_sessions
from app.auth.dependencies import AuthContext, _validate_api_key, trusted_sso_user
from app.auth.scope_deps import require_read
from app.config import get_settings
from app.db.session import get_session
from app.models.ui_session import UiSession
from app.services.rate_limiter import _sign_in_rate_limiter

router = APIRouter(prefix="/api/v1/auth/session", tags=["auth"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class SignInRequest(BaseModel):
    key: str = Field(min_length=1, max_length=512)


class SessionInfo(BaseModel):
    signed_in: bool
    scope: Literal["read", "print", "admin"] | None = None
    source: Literal["api-key", "pangolin-sso", "bootstrap"] | None = None
    user: str | None = None
    # True for a bootstrap session: the UI leads straight to creating the first admin key.
    bootstrap: bool = False
    csrf_token: str | None = None


def _info(row: UiSession) -> SessionInfo:
    return SessionInfo(
        signed_in=True,
        scope=row.scope,  # type: ignore[arg-type]
        source=row.source,  # type: ignore[arg-type]
        user=row.user,
        bootstrap=row.source == "bootstrap",
        csrf_token=row.csrf_token,
    )


def _unauthorized(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error_code": code, "error_message": message},
    )


@router.post(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Sign in to the web UI",
    description=(
        "Exchanges an API key with ``print`` or ``admin`` scope — or, while no admin key "
        "exists, the one-time bootstrap key — for a browser session. Sets an HttpOnly "
        "session cookie and a CSRF cookie. The key itself is never stored in the browser. "
        "Rate limited per client IP."
    ),
    responses={
        401: {"description": "Invalid key"},
        403: {"description": "Key scope too low (read-only)"},
        429: {"description": "Too many sign-in attempts"},
    },
)
async def sign_in(
    body: SignInRequest, request: Request, response: Response, db: SessionDep
) -> None:
    settings = get_settings()
    # Limitation: keyed by the direct peer; behind a reverse proxy all users share one bucket.
    client_ip = request.client.host if request.client else "unknown"
    allowed, retry_after = _sign_in_rate_limiter.check_and_consume_with_retry_after(
        client_ip, limit_per_minute=settings.sign_in_limit_per_minute
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error_code": "rate_limit_exceeded",
                "error_message": f"Too many sign-in attempts. Retry after {retry_after} seconds.",
                "retry_after_seconds": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )

    bootstrap_key = settings.bootstrap_admin_key.get_secret_value()
    if bootstrap_key and hmac.compare_digest(body.key.encode(), bootstrap_key.encode()):
        # D7: one-time key, only while no admin key exists.
        if await ui_sessions.admin_key_exists(db):
            raise _unauthorized(
                "bootstrap_disabled",
                "The bootstrap key is disabled because an admin key exists. "
                "Remove PRINTER_HUB_BOOTSTRAP_ADMIN_KEY.",
            )
        row, token = await ui_sessions.create_session(
            db, source="bootstrap", scope="admin", api_key_id=None, allowed_printer_ids=[]
        )
    else:
        ctx = await _validate_api_key(db, body.key, "read", client_ip)
        if ctx.scope == "read":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error_code": "scope_too_low",
                    "error_message": "Sign-in needs a key with 'print' or 'admin' scope.",
                },
            )
        row, token = await ui_sessions.create_session(
            db,
            source="api-key",
            scope=ctx.scope,
            api_key_id=ctx.api_key_id,
            allowed_printer_ids=ctx.allowed_printer_ids,
        )
    ui_sessions.set_cookies(response, settings, token, row.csrf_token)


@router.get(
    "",
    response_model=SessionInfo,
    summary="Current sign-in state",
    description=(
        "Reports whether the caller has a valid session. Behind an SSO proxy with a "
        "matching trust token and no session cookie, creates a ``pangolin-sso`` session "
        "and sets the cookies."
    ),
)
async def get_session_info(request: Request, response: Response, db: SessionDep) -> SessionInfo:
    settings = get_settings()
    session_cookie, _ = ui_sessions.cookie_names(settings)
    token = request.cookies.get(session_cookie, "")
    if token:
        valid = await ui_sessions.load_valid(db, token, settings)
        if valid is not None:
            return _info(valid.row)
        ui_sessions.clear_cookies(response, settings)

    # D10: only the trust-token path may mint a session (never the legacy header or bypass).
    sso_user = trusted_sso_user(request, settings)
    if sso_user:
        row, new_token = await ui_sessions.create_session(
            db,
            source="pangolin-sso",
            scope="admin",
            api_key_id=None,
            allowed_printer_ids=[],
            user=sso_user,
            sso_trust_fingerprint=ui_sessions.trust_fingerprint(settings, settings.sso_trust_token),
        )
        ui_sessions.set_cookies(response, settings, new_token, row.csrf_token)
        return _info(row)
    return SessionInfo(signed_in=False)


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Sign out",
    description="Revokes the current browser session and clears its cookies.",
)
async def sign_out(
    response: Response,
    db: SessionDep,
    auth: Annotated[AuthContext, Depends(require_read)],
) -> None:
    if auth.session_id is not None:
        await ui_sessions.revoke(db, auth.session_id)
    ui_sessions.clear_cookies(response, get_settings())
