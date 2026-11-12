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


def owner_only(auth: AuthContext | None) -> bool:
    """True when ``auth`` is bound to a plain API key: it sees its own jobs and runs only."""
    if auth is None or auth.scope == "admin":
        return False
    # A key context without an id cannot happen; if it did, it would see nothing (fail closed).
    return auth.api_key_id is not None or auth.source == "api-key"


def may_see(auth: AuthContext | None, owner_key_id: UUID | str | None) -> bool:
    """Whether ``auth`` may see a job or run whose owner key is ``owner_key_id``."""
    if not owner_only(auth):
        return True
    assert auth is not None  # owner_only is False for None
    return (
        auth.api_key_id is not None
        and owner_key_id is not None
        and str(owner_key_id) == str(auth.api_key_id)
    )
