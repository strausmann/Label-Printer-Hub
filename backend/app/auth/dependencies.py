"""FastAPI authentication dependency — ``require_scope()``.

Paths, in this order (spec 8.1, 8.2; D7, D10):

1. API key header ``X-Label-Hub-Key: lh_...`` — bcrypt-verified, scope from the key
   (admin ⊇ print ⊇ read). CSRF-exempt: browsers never send it on their own.
2. Browser session cookie — issued by ``/api/v1/auth/session``. Re-validated on
   every use (``app.auth.sessions.load_valid``); state-changing methods need the
   ``X-CSRF-Token`` header. Bootstrap sessions may only create the first admin key.
3. SSO proxy headers — ``sso_user_header`` counts only together with
   ``sso_trust_header`` matching a non-empty ``sso_trust_token`` (constant-time
   compare). The legacy ``X-Pangolin-User`` header counts only with
   ``trust_legacy_pangolin_user``. State-changing requests on this path need an
   ``Origin`` equal to the origin of ``public_url``.
4. Pangolin ``Authorization: Basic`` bypass — only with
   ``trust_pangolin_basic_bypass``; limited to ``read`` when
   ``pangolin_bypass_scope_downgrade`` is set.

Only the trust-token path may mint a browser session (see auth_session.py).
This supersedes ADR 0014.
"""

from __future__ import annotations

import base64
import hmac
import logging
from collections.abc import Callable, Coroutine, Hashable
from typing import Any, Literal, cast
from uuid import UUID

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import csrf
from app.auth import sessions as ui_sessions
from app.auth.verifier import verify_api_key_async
from app.config import Settings, get_settings
from app.db.session import get_session
from app.repositories import api_keys as api_keys_repo
from app.services.rate_limiter import _rate_limiter

_log = logging.getLogger(__name__)


def _loggable(value: str) -> str:
    """Make a client-supplied value safe for a log line.

    ``unicode_escape`` turns every non-printable character (CR, LF, ANSI escapes, U+2028 …) into
    its backslash form. The final replaces are no-ops after that, but they are the sanitiser
    CodeQL's ``py/log-injection`` query recognises.
    """
    escaped = value.encode("unicode_escape").decode("ascii")
    return escaped.replace("\r", "").replace("\n", "")


# Header schema — auto_error=False so we can fall through to other paths
_api_key_header = APIKeyHeader(name="X-Label-Hub-Key", auto_error=False)

# Scope hierarchy: each scope also satisfies all scopes listed after it
_SCOPE_HIERARCHY: dict[str, list[str]] = {
    "admin": ["admin", "print", "read"],
    "print": ["print", "read"],
    "read": ["read"],
}

# #321: no key is longer than this; a longer value is refused before lookup and bcrypt
# (bcrypt >= 5 raises on more than 72 bytes). The URL token uses the same limit.
MAX_KEY_LENGTH = 128

# Scope → HTTP status for insufficient scope
_SCOPE_ORDER = ["read", "print", "admin"]


Scope = Literal["read", "print", "admin"]

# D7: the only routes a bootstrap session may use.
_BOOTSTRAP_ALLOWED: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/api/v1/admin/api-keys"),
        ("GET", "/api/v1/auth/session"),
        ("DELETE", "/api/v1/auth/session"),
    }
)

LEGACY_PANGOLIN_USER_HEADER = "X-Pangolin-User"


class AuthContext(BaseModel):
    """Resolved authentication context passed to route handlers."""

    source: Literal["api-key", "pangolin-sso", "pangolin-bypass", "session", "bootstrap"]
    scope: Scope
    api_key_id: UUID | None
    ip: str
    allowed_printer_ids: list[str] = []
    user: str | None = None
    session_id: UUID | None = None


def _scope_satisfies(key_scope: str, required_scope: str) -> bool:
    """Return True if ``key_scope`` satisfies ``required_scope``.

    admin satisfies everything; print satisfies read and print; read only read.

    Raises:
        ValueError: if ``key_scope`` is not a known scope value.  Fail-closed:
            unknown scopes must never grant implicit access.
    """
    if key_scope not in _SCOPE_HIERARCHY:
        raise ValueError(f"Unknown scope: {key_scope!r}")
    return required_scope in _SCOPE_HIERARCHY[key_scope]


def trusted_sso_user(request: Request, settings: Settings) -> str | None:
    """Return the SSO user when the trust token matches, else ``None`` (D10).

    Requires a non-empty ``sso_trust_token``, a non-empty user header and a
    trust header equal to the token (constant-time comparison). This is the only
    header path that may mint a browser session.
    """
    expected = settings.sso_trust_token
    if not expected:
        return None
    user = request.headers.get(settings.sso_user_header, "")
    presented = request.headers.get(settings.sso_trust_header, "")
    if not user or not presented:
        return None
    if not hmac.compare_digest(presented.encode(), expected.encode()):
        return None
    return user


def _sso_header_user(request: Request, settings: Settings) -> str | None:
    """SSO user from trusted headers, or from the legacy header when opted in (D10)."""
    user = trusted_sso_user(request, settings)
    if user:
        return user
    if settings.trust_legacy_pangolin_user:
        legacy = request.headers.get(LEGACY_PANGOLIN_USER_HEADER, "")
        if legacy:
            return legacy
    return None


def _has_pangolin_sso_session(request: Request, settings: Settings) -> bool:
    """True when the request carries SSO headers this hub trusts (D10)."""
    return _sso_header_user(request, settings) is not None


def _origin_matches(request: Request, settings: Settings) -> bool:
    origin = request.headers.get("origin", "").strip().rstrip("/").lower()
    return bool(origin) and origin == ui_sessions.public_origin(settings)


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


def enforce_key_rate_limit(key_id: Hashable, limit_per_minute: int, key_name: str) -> None:
    """Consume one token of the key's per-minute bucket; 429 with Retry-After when empty.

    Shared by the API key header and by browser sessions derived from a key, so a
    session cannot be used to get around the key's limit, and by the webhook key.
    """
    allowed, retry_after = _rate_limiter.check_and_consume_with_retry_after(
        key_id, limit_per_minute=limit_per_minute
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "error_code": "rate_limit_exceeded",
                "error_message": (
                    f"Key '{key_name}' exceeded {limit_per_minute}"
                    f" prints/minute. Retry after {retry_after} seconds."
                ),
                "retry_after_seconds": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )


class ScopeRefusedError(Exception):
    """A valid key whose effective scope the caller refuses (``refuse_scopes``)."""

    def __init__(self, scope: str) -> None:
        super().__init__(scope)
        self.scope = scope


async def _validate_api_key(
    session: AsyncSession,
    key_header: str,
    required_scope: str,
    client_ip: str,
    *,
    refuse_scopes: frozenset[str] = frozenset(),
) -> AuthContext:
    """Validate the X-Label-Hub-Key header.

    1. Extract prefix (first 16 chars) to look up the key row.
    2. bcrypt-verify the full plaintext against the stored hash.
    3. Check the key is enabled and not expired.
    4. Check the key's scopes satisfy ``required_scope``.
    5. Update last_used_at asynchronously (best-effort, no transaction wait).

    ``refuse_scopes`` lists effective scopes the caller refuses (the URL token refuses
    ``admin``). Such a key raises :class:`ScopeRefusedError` before it uses a rate-limit
    slot or is marked as used, so a refused key never looks used in the key list.

    Raises:
        HTTPException 401: key not found / bcrypt mismatch / disabled
        HTTPException 403: key valid but insufficient scope
        ScopeRefusedError: key valid but its effective scope is in ``refuse_scopes``
    """
    if len(key_header) < 16:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "invalid_key_format", "error_message": "Invalid key format"},
        )

    if len(key_header) > MAX_KEY_LENGTH:
        # #321: same answer as an unknown key, before the lookup and bcrypt.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "invalid_key", "error_message": "Invalid or unknown API key"},
        )

    prefix = key_header[:16]
    key_row = await api_keys_repo.get_by_prefix(session, prefix)

    if key_row is None:
        _log.debug("API key not found for prefix %s", _loggable(prefix))
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

    try:
        key_matches = await verify_api_key_async(key_header, key_row.key_hash)
    except ValueError:
        # #321: bcrypt >= 5 refuses more than 72 bytes; no key is that long.
        key_matches = False
    if not key_matches:
        _log.debug("bcrypt mismatch for prefix %s", _loggable(prefix))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "invalid_key", "error_message": "Invalid or unknown API key"},
        )

    # Determine the effective scope from the key's scopes list.
    # admin > print > read; a key with no recognised scopes has no access.
    key_scopes = key_row.scopes or []
    effective_scope: str | None = None
    for s in ["admin", "print", "read"]:
        if s in key_scopes:
            effective_scope = s
            break

    if effective_scope is None:
        # Key exists and bcrypt matched, but it has no valid scopes assigned.
        # Fail with 401 (not 403) — the key is structurally invalid, not just
        # insufficient for this endpoint.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "key_no_scopes",
                "error_message": "API key has no scopes assigned.",
            },
        )

    try:
        scope_ok = _scope_satisfies(effective_scope, required_scope)
    except ValueError as exc:
        # Scope value from DB is not in the known hierarchy — treat as 401.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "key_invalid_scope",
                "error_message": "API key has an unrecognised scope value.",
            },
        ) from exc

    if not scope_ok:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "insufficient_scope",
                "error_message": (
                    f"Key has scope '{effective_scope}' but '{required_scope}' is required"
                ),
            },
        )

    # #281: refused before the rate-limit slot and the last-used write.
    if effective_scope in refuse_scopes:
        raise ScopeRefusedError(effective_scope)

    # Rate limit check — after bcrypt verify to avoid info leak on exhaustion
    enforce_key_rate_limit(key_row.id, key_row.rate_limit_per_minute, key_row.name)

    # Read before the update: a rollback expires the row's attributes.
    key_id = key_row.id
    # #283: an admin key acts on every printer; a list stored by an older version is ignored.
    allowed_printer_ids = [] if effective_scope == "admin" else key_row.allowed_printer_ids or []

    # Best-effort last-used update (don't fail auth if this errors)
    try:
        await api_keys_repo.update_last_used(session, key_id, ip=client_ip)
    except Exception as exc:
        _log.warning("Failed to update last_used for key %s: %s", key_id, exc)
        await session.rollback()  # a failed commit leaves the session unusable until rolled back

    return AuthContext(
        source="api-key",
        scope=effective_scope,  # type: ignore[arg-type]
        api_key_id=key_id,
        ip=client_ip,
        allowed_printer_ids=allowed_printer_ids,
    )


def _require_origin_for_writes(request: Request, settings: Settings) -> None:
    """Cookie-less header auth (SSO headers, Basic bypass): writes need Origin == public_url."""
    if request.method.upper() in csrf.UNSAFE_METHODS and not _origin_matches(request, settings):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "origin_mismatch",
                "error_message": "State-changing requests need an Origin of public_url.",
            },
        )


def _session_context(
    request: Request, valid: ui_sessions.ValidSession, required: Scope, client_ip: str
) -> AuthContext:
    row = valid.row
    is_bootstrap = row.source == "bootstrap"
    # Limitation: matches the raw URL path, so a root_path prefix would break this check.
    if is_bootstrap and (request.method.upper(), request.url.path) not in _BOOTSTRAP_ALLOWED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "bootstrap_only",
                "error_message": (
                    "The bootstrap key can only create the first admin key. "
                    "Create one and sign in with it."
                ),
            },
        )
    csrf.verify(request, row)
    if row.scope not in _SCOPE_HIERARCHY or not _scope_satisfies(row.scope, required):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "insufficient_scope",
                "error_message": f"Session has scope '{row.scope}' but '{required}' is required",
            },
        )
    if row.api_key_id is not None and valid.rate_limit_per_minute is not None:
        enforce_key_rate_limit(
            row.api_key_id, valid.rate_limit_per_minute, valid.key_name or str(row.api_key_id)
        )
    return AuthContext(
        source="bootstrap" if is_bootstrap else "session",
        scope=cast(Scope, row.scope),
        api_key_id=row.api_key_id,
        ip=client_ip,
        # #283: an admin session is never restricted, whatever a stored copy says.
        allowed_printer_ids=[] if row.scope == "admin" else valid.allowed_printer_ids,
        user=row.user,
        session_id=row.id,
    )


def require_scope(
    required: Literal["read", "print", "admin"],
    *,
    settings: Settings | None = None,
    own_session: bool = False,
) -> Callable[..., Coroutine[Any, Any, AuthContext]]:
    """Return a FastAPI dependency that enforces the required scope.

    Args:
        required: One of "read", "print", "admin".
        settings: Override settings (for testing). Defaults to ``get_settings()``,
            read on every request so configuration changes in tests take effect.
        own_session: Authenticate in a short-lived DB session that is closed before the
            route runs. FastAPI keeps request-scoped ``Depends(get_session)`` sessions open
            until a streaming response has ended, which would pin a pooled connection per
            open stream; long-lived routes (the event stream) use this.

    Order: API key header → session cookie → SSO headers → Basic bypass → 401.
    See the module docstring for the trust rules of each path.
    """
    if required not in _SCOPE_HIERARCHY:
        raise ValueError(f"Unknown scope: {required!r}")
    required_scope: Scope = required

    async def _authenticate(
        request: Request, key_header: str | None, session: AsyncSession
    ) -> AuthContext:
        effective_settings = settings or get_settings()
        client_ip = request.client.host if request.client else "unknown"

        # Path 1: API-Key header takes priority over every other path.
        if key_header:
            return await _validate_api_key(session, key_header, required_scope, client_ip)

        # Path 2: browser session cookie. An unusable cookie falls through, so a
        # browser behind SSO keeps working after its session expired.
        session_cookie, _ = ui_sessions.cookie_names(effective_settings)
        token = request.cookies.get(session_cookie, "")
        if token:
            valid = await ui_sessions.load_valid(session, token, effective_settings)
            if valid is not None:
                return _session_context(request, valid, required_scope, client_ip)

        # Path 3: SSO proxy headers (D10: trust token, legacy header only opt-in).
        sso_user = _sso_header_user(request, effective_settings)
        if sso_user:
            _require_origin_for_writes(request, effective_settings)
            return AuthContext(
                source="pangolin-sso",
                scope=required_scope,
                api_key_id=None,
                ip=client_ip,
                user=sso_user,
            )

        # Path 4: Pangolin Basic bypass — opt-in (D10), optionally read-only.
        if effective_settings.trust_pangolin_basic_bypass and _is_pangolin_bypass(request):
            # Browsers can cache Basic credentials, so writes need the Origin rule too.
            _require_origin_for_writes(request, effective_settings)
            bypass_scope: Scope = (
                "read" if effective_settings.pangolin_bypass_scope_downgrade else required_scope
            )
            if not _scope_satisfies(bypass_scope, required_scope):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "error_code": "insufficient_scope",
                        "error_message": (
                            "The Basic bypass is limited to 'read'; use an API key for "
                            f"'{required_scope}'."
                        ),
                    },
                )
            return AuthContext(
                source="pangolin-bypass",
                scope=bypass_scope,
                api_key_id=None,
                ip=client_ip,
            )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "missing_credentials",
                "error_message": "Authentication required. Provide X-Label-Hub-Key header.",
            },
        )

    async def _check(
        request: Request,
        key_header: str | None = Security(_api_key_header),
        session: AsyncSession = Depends(get_session),  # noqa: B008
    ) -> AuthContext:
        return await _authenticate(request, key_header, session)

    async def _check_own_session(
        request: Request,
        key_header: str | None = Security(_api_key_header),
    ) -> AuthContext:
        import app.db.engine as db_engine  # attribute lookup at call time (test engines)

        async with db_engine.async_session() as session:
            return await _authenticate(request, key_header, session)

    return _check_own_session if own_session else _check


def check_printer_access(
    auth_context: AuthContext, printer_id: UUID, *, default_printer: bool = False
) -> None:
    """Verify the AuthContext allows access to the given printer.

    API keys and browser sessions carry ``allowed_printer_ids`` (a session uses
    its key's current list). Empty list = all printers allowed. SSO and bypass
    contexts have an empty list and are therefore unrestricted.

    Raises:
        HTTPException 403 if the restricted list excludes printer_id. With ``default_printer``
        (the routes that act on the default printer without naming it) the answer does not
        carry the printer id: the caller never named it and may not learn it (263-80).
    """
    if auth_context.allowed_printer_ids and str(printer_id) not in auth_context.allowed_printer_ids:
        message = (
            "No access to the default printer"
            if default_printer
            else f"These credentials are not authorised for printer {printer_id}."
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "printer_not_allowed", "error_message": message},
        )
