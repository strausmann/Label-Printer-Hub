"""Who may see and act on a job or a tape run (#294).

A job and a tape run belong to the API key that submitted it (``Job.api_key_id``,
``PrintBatch.created_by``). A plain API key (scope ``read`` or ``print``) sees and acts on its
own only; browser sessions, SSO users and admin keys on everything their printers allow. A job
without an owner key (browser, SSO, webhook, recovery, or a row from before the key was
recorded) belongs to no API key.
"""

from __future__ import annotations

from uuid import UUID

from app.auth.dependencies import AuthContext


def owner_only(auth: AuthContext | None) -> bool:
    """True when ``auth`` is a plain API key: it sees its own jobs and runs only."""
    return auth is not None and auth.source == "api-key" and auth.scope != "admin"


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
