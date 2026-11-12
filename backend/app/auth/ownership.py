"""Who may see and act on a job or a tape run (#294).

A job and a tape run belong to the API key that submitted it (``Job.api_key_id``,
``PrintBatch.created_by``). A caller bound to a plain API key (scope ``read`` or ``print``)
sees and acts on its own only: the key in the ``X-Label-Hub-Key`` header, and a browser session
signed in with such a key. Privilege is decided by scope and key, never by the auth source, so
a key cannot widen its reach by signing in. SSO users, header-trusted callers (no key),
bootstrap and every admin-scope caller act on everything their printers allow. A job without
an owner key (SSO, webhook, recovery, or a row from before the key was recorded) belongs to no
API key.
"""

from __future__ import annotations

from uuid import UUID

from app.auth.dependencies import AuthContext

# How a write records a key as its author (``sheet_common.actor``): sheet batches, sheets and
# sheet types store ``key:<uuid>``; tape batches store the bare key id.
KEY_ACTOR_PREFIX = "key:"


def key_actor(key_id: UUID) -> str:
    """The recorded author of a write made with ``key_id``."""
    return f"{KEY_ACTOR_PREFIX}{key_id}"


def owner_key_of(stored: UUID | str | None) -> str | None:
    """The key id a stored owner names, in canonical form, or ``None`` when it names no key.

    Accepts both forms a batch stores: the bare key id (tape batches) and ``key:<uuid>``
    (sheet batches). Anything else (a user name, an auth source) names no key.
    """
    if stored is None:
        return None
    text = str(stored)
    if text.startswith(KEY_ACTOR_PREFIX):
        text = text[len(KEY_ACTOR_PREFIX) :]
    try:
        return str(UUID(text))
    except ValueError:
        return None


def owner_only(auth: AuthContext | None) -> bool:
    """True when ``auth`` is bound to a plain API key: it sees its own jobs and runs only.

    ``None`` (no auth context) is deliberately unrestricted: every route depends on a scope
    dependency that yields a context or answers 401/403, so ``None`` only occurs where a test
    overrides that dependency. It never means "not signed in".
    """
    if auth is None or auth.scope == "admin":
        return False
    # A key context without an id cannot happen; if it did, it would see nothing (fail closed).
    return auth.api_key_id is not None or auth.source == "api-key"


def may_see(auth: AuthContext | None, owner_key_id: UUID | str | None) -> bool:
    """Whether ``auth`` may see a job or run whose owner key is ``owner_key_id``."""
    if not owner_only(auth):
        return True
    assert auth is not None  # owner_only is False for None
    owner = owner_key_of(owner_key_id)
    return auth.api_key_id is not None and owner is not None and owner == str(auth.api_key_id)
