# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Server-side browser sessions for the web UI (spec 8.1, 8.2; D7, D10).

The cookie carries ``secrets.token_urlsafe(32)``; only its SHA-256 is stored. Sessions
expire 12 h after creation (absolute) and are re-validated on every use: not revoked,
not expired, the linked API key still enabled and unexpired, and — for bootstrap
sessions — still no admin key in the database.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col
from starlette.responses import Response

from app.auth import csrf
from app.config import Settings
from app.models.api_key import ApiKey
from app.models.ui_session import UiSession

_log = logging.getLogger(__name__)

SESSION_TTL = timedelta(hours=12)
MAX_ACTIVE_SESSIONS = 20
PURGE_AFTER = timedelta(days=1)

_SESSION_COOKIE = "lph_session"
_CSRF_COOKIE = "lph_csrf"


def _now() -> datetime:
    """Current UTC time; a module function so tests can move the clock."""
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes; values are stored as UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def trust_fingerprint(settings: Settings, trust_token: str) -> str:
    """HMAC-SHA256 of the SSO trust token, keyed with the hub's secret key (D5, D10).

    Stored on ``pangolin-sso`` sessions so a rotated or cleared token ends them,
    without ever storing the token itself.
    """
    text = settings.secret_key.get_secret_value()
    key = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    return hmac.new(key, b"sso-trust-token:" + trust_token.encode(), hashlib.sha256).hexdigest()


def is_secure(settings: Settings) -> bool:
    return settings.public_url.scheme == "https"


def cookie_names(settings: Settings) -> tuple[str, str]:
    """``(session, csrf)`` cookie names; ``__Host-`` prefixed when served over https."""
    if is_secure(settings):
        return f"__Host-{_SESSION_COOKIE}", f"__Host-{_CSRF_COOKIE}"
    return _SESSION_COOKIE, _CSRF_COOKIE


def public_origin(settings: Settings) -> str:
    """Origin (scheme://host[:port]) of ``public_url``, default ports omitted."""
    url = settings.public_url
    default_port = 443 if url.scheme == "https" else 80
    origin = f"{url.scheme}://{url.host}"
    if url.port is not None and url.port != default_port:
        origin += f":{url.port}"
    return origin.lower()


def warn_if_insecure(settings: Settings) -> None:
    if not is_secure(settings):
        _log.warning(
            "public_url is not https: session cookies are sent without the Secure flag; "
            "cookies are sent unencrypted. Use https outside of a local test setup."
        )


def set_cookies(response: Response, settings: Settings, token: str, csrf_token: str) -> None:
    session_name, csrf_name = cookie_names(settings)
    secure = is_secure(settings)
    max_age = int(SESSION_TTL.total_seconds())
    response.set_cookie(
        session_name,
        token,
        max_age=max_age,
        path="/",
        secure=secure,
        httponly=True,
        samesite="strict",
    )
    response.set_cookie(
        csrf_name,
        csrf_token,
        max_age=max_age,
        path="/",
        secure=secure,
        httponly=False,
        samesite="strict",
    )


def clear_cookies(response: Response, settings: Settings) -> None:
    session_name, csrf_name = cookie_names(settings)
    secure = is_secure(settings)
    response.delete_cookie(session_name, path="/", secure=secure, httponly=True, samesite="strict")
    response.delete_cookie(csrf_name, path="/", secure=secure, httponly=False, samesite="strict")


def _key_is_usable(key: ApiKey | None, now: datetime) -> bool:
    if key is None or not key.enabled:
        return False
    return key.expires_at is None or _aware(key.expires_at) > now


async def admin_key_exists(db: AsyncSession) -> bool:
    """True when an enabled, unexpired key with ``admin`` scope exists (D7)."""
    now = _now()
    rows = (await db.execute(select(ApiKey).where(col(ApiKey.enabled).is_(True)))).scalars()
    return any("admin" in (key.scopes or []) and _key_is_usable(key, now) for key in rows)


async def create_session(
    db: AsyncSession,
    *,
    source: str,
    scope: str,
    api_key_id: UUID | None,
    allowed_printer_ids: list[str],
    user: str | None = None,
    sso_trust_fingerprint: str | None = None,
) -> tuple[UiSession, str]:
    """Insert a session and return ``(row, cookie_token)``.

    At most ``MAX_ACTIVE_SESSIONS`` active sessions exist per key (or per SSO user /
    bootstrap); creating one more revokes the oldest.
    """
    now = _now()
    token = secrets.token_urlsafe(32)
    row = UiSession(
        token_hash=hash_token(token),
        csrf_token=csrf.new_token(),
        source=source,
        scope=scope,
        api_key_id=api_key_id,
        allowed_printer_ids=list(allowed_printer_ids),
        user=user,
        sso_trust_fingerprint=sso_trust_fingerprint,
        created_at=now,
        expires_at=now + SESSION_TTL,
    )
    stmt = select(UiSession).where(
        col(UiSession.revoked_at).is_(None), col(UiSession.expires_at) > now
    )
    if api_key_id is not None:
        stmt = stmt.where(col(UiSession.api_key_id) == api_key_id)
    else:
        stmt = stmt.where(
            col(UiSession.api_key_id).is_(None),
            col(UiSession.source) == source,
            col(UiSession.user).is_(None) if user is None else col(UiSession.user) == user,
        )
    active = list((await db.execute(stmt.order_by(col(UiSession.created_at)))).scalars())
    excess = len(active) - (MAX_ACTIVE_SESSIONS - 1)
    for old in active[: max(excess, 0)]:
        old.revoked_at = now
        db.add(old)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row, token


@dataclass(frozen=True)
class ValidSession:
    row: UiSession
    allowed_printer_ids: list[str]
    # Set for sessions of an API key: the key's per-minute limit applies to the session too.
    rate_limit_per_minute: int | None = None
    key_name: str | None = None


async def load_valid(db: AsyncSession, token: str, settings: Settings) -> ValidSession | None:
    """Return the session for ``token`` if it may still be used, else ``None``."""
    if not token:
        return None
    row = (
        await db.execute(select(UiSession).where(col(UiSession.token_hash) == hash_token(token)))
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return None
    now = _now()
    if _aware(row.expires_at) <= now:
        return None
    allowed = list(row.allowed_printer_ids or [])
    rate_limit: int | None = None
    key_name: str | None = None
    if row.source == "pangolin-sso":
        # D10: the session lives only as long as the trust token it was minted with.
        current = settings.sso_trust_token
        stored = row.sso_trust_fingerprint or ""
        if (
            not current
            or not stored
            or not hmac.compare_digest(
                stored.encode(), trust_fingerprint(settings, current).encode()
            )
        ):
            return None
    if row.api_key_id is not None:
        key = await db.get(ApiKey, row.api_key_id)
        if key is None or not _key_is_usable(key, now):
            return None
        # The key's current restriction wins over the copy taken at sign-in.
        allowed = [] if "admin" in (key.scopes or []) else list(key.allowed_printer_ids or [])
        rate_limit = key.rate_limit_per_minute
        key_name = key.name
    if row.source == "bootstrap":
        # D7: the bootstrap session dies as soon as a real admin key exists
        # (or the variable has been removed).
        if not settings.bootstrap_admin_key.get_secret_value():
            return None
        if await admin_key_exists(db):
            return None
    return ValidSession(
        row=row, allowed_printer_ids=allowed, rate_limit_per_minute=rate_limit, key_name=key_name
    )


async def usable_key_printer_ids(db: AsyncSession, key_id: UUID) -> list[str] | None:
    """The key's current ``allowed_printer_ids`` while it is enabled and unexpired, else ``None``.

    Lets long-lived connections (the event stream) re-check an API key without a full sign-in.
    """
    key = await db.get(ApiKey, key_id)
    if key is None or not _key_is_usable(key, _now()):
        return None
    if "admin" in (key.scopes or []):
        return []  # #283: an admin key acts on every printer
    return list(key.allowed_printer_ids or [])


async def revoke(db: AsyncSession, session_id: UUID) -> None:
    await db.execute(
        update(UiSession)
        .where(col(UiSession.id) == session_id, col(UiSession.revoked_at).is_(None))
        .values(revoked_at=_now())
    )
    await db.commit()


async def purge_expired(session_factory: Callable[[], Any]) -> int:
    """Delete sessions that expired more than ``PURGE_AFTER`` ago; return the count."""
    cutoff = _now() - PURGE_AFTER
    async with session_factory() as db:
        result = await db.execute(delete(UiSession).where(col(UiSession.expires_at) < cutoff))
        await db.commit()
        return int(getattr(result, "rowcount", 0) or 0)
