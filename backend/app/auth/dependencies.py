"""FastAPI authentication dependency — Phase 7c require_scope().

Three authentication paths (in priority order):

1. API-Key header ``X-Label-Hub-Key: lh_...``
   - Validated via bcrypt verify + LRU cache
   - Full 3-level scope model (read/print/admin)
   - Scope hierarchy: admin ⊇ print ⊇ read

2. Pangolin-SSO browser session (``X-Pangolin-User`` header set by Pangolin)
   - Only grants ``read`` scope
   - Used by the frontend after SSO login

3. Pangolin-bypass claude-automation (``Authorization: Basic ...`` with
   the claude-automation credential)
   - Grants ``read`` scope only (after Phase 7c deployment)
   - When ``settings.pangolin_bypass_scope_downgrade=True``, write operations
     (print/admin) require an explicit API key
   - Recovery pathway: if all app keys are lost, still allows diagnostics

Scope hierarchy for key-based auth:
  admin  → satisfies print, read
  print  → satisfies read
  read   → satisfies read only
"""

from __future__ import annotations

import base64
import logging
from typing import Literal
from uuid import UUID

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.verifier import verify_api_key_async
from app.config import Settings, get_settings
from app.db.session import get_session
from app.repositories import api_keys as api_keys_repo
from app.services.rate_limiter import _rate_limiter

_log = logging.getLogger(__name__)

# Header schema — auto_error=False so we can fall through to other paths
_api_key_header = APIKeyHeader(name="X-Label-Hub-Key", auto_error=False)

# Scope hierarchy: each scope also satisfies all scopes listed after it
_SCOPE_HIERARCHY: dict[str, list[str]] = {
    "admin": ["admin", "print", "read"],
    "print": ["print", "read"],
    "read": ["read"],
}

# Scope → HTTP status for insufficient scope
_SCOPE_ORDER = ["read", "print", "admin"]


class AuthContext(BaseModel):
    """Resolved authentication context passed to route handlers."""

    source: Literal["api-key", "pangolin-sso", "pangolin-bypass"]
    scope: Literal["read", "print", "admin"]
    api_key_id: UUID | None
    ip: str
    allowed_printer_ids: list[str] = []


def _scope_satisfies(key_scope: str, required_scope: str) -> bool:
    """Return True if ``key_scope`` satisfies ``required_scope``.

    admin satisfies everything; print satisfies read and print; read only read.
    """
    return required_scope in _SCOPE_HIERARCHY.get(key_scope, [required_scope])


def _has_pangolin_sso_session(request: Request) -> bool:
    """Return True when the Pangolin reverse proxy has set the SSO user header.

    Pangolin sets ``X-Pangolin-User`` after the user has authenticated via SSO.
    This header is trusted only when it originates from the Pangolin proxy —
    in HomeLab deployments, direct internet access to the backend is blocked
    at the network level (Tailscale), so the header cannot be spoofed by
    external callers.
    """
    return bool(request.headers.get("X-Pangolin-User"))


def _is_pangolin_bypass(request: Request) -> bool:
    """Return True when the request uses the Pangolin claude-automation Basic-Auth bypass.

    Pangolin's Header-Auth bypass attaches an ``Authorization: Basic <b64>`` header
    where the credential is the ``claude-automation`` username.  We check only
    for the presence of this mechanism — the actual credential verification is
    done by Pangolin's edge layer before the request reaches us.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("basic "):
        return False
    try:
        decoded = base64.b64decode(auth[6:]).decode("utf-8", errors="replace")
        username = decoded.split(":")[0]
        return username == "claude-automation"
    except Exception:
        return False


async def _validate_api_key(
    session: AsyncSession,
    key_header: str,
    required_scope: str,
    client_ip: str,
) -> AuthContext:
    """Validate the X-Label-Hub-Key header.

    1. Extract prefix (first 12 chars) to look up the key row.
    2. bcrypt-verify the full plaintext against the stored hash.
    3. Check the key is enabled and not expired.
    4. Check the key's scopes satisfy ``required_scope``.
    5. Update last_used_at asynchronously (best-effort, no transaction wait).

    Raises:
        HTTPException 401: key not found / bcrypt mismatch / disabled
        HTTPException 403: key valid but insufficient scope
    """
    if len(key_header) < 12:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "invalid_key_format", "error_message": "Invalid key format"},
        )

    prefix = key_header[:12]
    key_row = await api_keys_repo.get_by_prefix(session, prefix)

    if key_row is None:
        _log.debug("API key not found for prefix %s", prefix)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "invalid_key", "error_message": "Invalid or unknown API key"},
        )

    if not key_row.enabled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "key_disabled", "error_message": "API key is disabled"},
        )

    from datetime import UTC, datetime

    if key_row.expires_at is not None:
        expires = key_row.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if datetime.now(UTC) > expires:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error_code": "key_expired", "error_message": "API key has expired"},
            )

    if not await verify_api_key_async(key_header, key_row.key_hash):
        _log.debug("bcrypt mismatch for prefix %s", prefix)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "invalid_key", "error_message": "Invalid or unknown API key"},
        )

    # Determine the effective scope from the key's scopes list
    # admin > print > read
    key_scopes = key_row.scopes or []
    effective_scope: str = "read"
    for s in ["admin", "print", "read"]:
        if s in key_scopes:
            effective_scope = s
            break

    if not _scope_satisfies(effective_scope, required_scope):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "insufficient_scope",
                "error_message": (
                    f"Key has scope '{effective_scope}' but '{required_scope}' is required"
                ),
            },
        )

    # Rate limit check — after bcrypt verify to avoid info leak on exhaustion
    allowed, retry_after = _rate_limiter.check_and_consume_with_retry_after(
        key_row.id, limit_per_minute=key_row.rate_limit_per_minute
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "error_code": "rate_limit_exceeded",
                "error_message": (
                    f"Key '{key_row.name}' exceeded {key_row.rate_limit_per_minute}"
                    " prints/minute. Retry after {retry_after} seconds."
                ),
                "retry_after_seconds": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )

    # Best-effort last-used update (don't fail auth if this errors)
    try:
        await api_keys_repo.update_last_used(session, key_row.id, ip=client_ip)
    except Exception as exc:
        _log.warning("Failed to update last_used for key %s: %s", key_row.id, exc)

    return AuthContext(
        source="api-key",
        scope=effective_scope,  # type: ignore[arg-type]
        api_key_id=key_row.id,
        ip=client_ip,
        allowed_printer_ids=key_row.allowed_printer_ids or [],
    )


def require_scope(required: str, *, settings: Settings | None = None):
    """Return a FastAPI dependency that enforces the required scope.

    Args:
        required: One of "read", "print", "admin".
        settings: Override settings (for testing). Defaults to get_settings().

    The dependency resolves through three paths (in priority order):
      1. X-Label-Hub-Key API key header
      2. Pangolin-SSO (X-Pangolin-User) — read scope only
      3. Pangolin-bypass (claude-automation Basic Auth) — read scope only

    Returns a callable that FastAPI injects as ``Depends(require_scope("read"))``.
    """
    effective_settings = settings or get_settings()

    async def _check(
        request: Request,
        key_header: str | None = Security(_api_key_header),
        session: AsyncSession = Depends(get_session),  # noqa: B008
    ) -> AuthContext:
        client_ip = request.client.host if request.client else "unknown"

        # Path 1: API-Key header takes priority over SSO/bypass
        if key_header:
            return await _validate_api_key(session, key_header, required, client_ip)

        # Path 2: Pangolin-SSO (browser session)
        if _has_pangolin_sso_session(request) and required == "read":
            return AuthContext(
                source="pangolin-sso",
                scope="read",
                api_key_id=None,
                ip=client_ip,
            )

        # Path 3: Pangolin-bypass (claude-automation) — read-only
        if _is_pangolin_bypass(request):
            # After Phase 7c, bypass is downgraded to read-only.
            # The feature flag controls when the downgrade is enforced.
            if required == "read" or not effective_settings.pangolin_bypass_scope_downgrade:
                return AuthContext(
                    source="pangolin-bypass",
                    scope="read",
                    api_key_id=None,
                    ip=client_ip,
                )
            # Downgrade enforced: bypass cannot satisfy print/admin
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error_code": "bypass_scope_downgraded",
                    "error_message": (
                        "Pangolin bypass is read-only. Use X-Label-Hub-Key for write operations."
                    ),
                },
            )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "missing_credentials",
                "error_message": "Authentication required. Provide X-Label-Hub-Key header.",
            },
        )

    return _check


def check_printer_access(auth_context: AuthContext, printer_id: UUID) -> None:
    """Verify the AuthContext allows access to the given printer.

    For api-key auth: checks allowed_printer_ids.
    Empty list = all printers allowed. Non-empty = must contain printer_id.

    For pangolin-sso / pangolin-bypass: unrestricted (single-user HomeLab).

    Raises:
        HTTPException 403 if the key has a restricted list that excludes printer_id.
    """
    if auth_context.source != "api-key":
        return  # SSO and bypass have unrestricted printer access

    if auth_context.allowed_printer_ids and str(printer_id) not in auth_context.allowed_printer_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "printer_not_allowed",
                "error_message": (f"This API key is not authorised for printer {printer_id}."),
            },
        )
