# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

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
    """The key id a stored owner names, or ``None`` when it names no key.

    Accepts exactly the two forms the hub writes: the canonical key id (tape batches) and
    ``key:<canonical id>`` (sheet batches). ``UUID()`` also parses upper case, missing
    hyphens, braces, ``urn:uuid:`` and non-ASCII digits; a legacy user name spelt like that
    must not read as a key, so the rest has to equal its own canonical form.
    """
    if stored is None:
        return None
    if isinstance(stored, UUID):
        return str(stored)
    text = stored.removeprefix(KEY_ACTOR_PREFIX)
    try:
        canonical = str(UUID(text))
    except ValueError:
        return None
    return canonical if text == canonical else None


def looks_like_key(name: str) -> bool:
    """Whether ``name`` could be read as a key in any spelling ``UUID()`` accepts.

    The lenient check for the write side: a user name like that is stored with a prefix,
    so it never collides with a key, whatever spelling a later reader accepts.
    """
    try:
        UUID(name.strip().removeprefix(KEY_ACTOR_PREFIX).strip())
    except ValueError:
        return False
    return True


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
