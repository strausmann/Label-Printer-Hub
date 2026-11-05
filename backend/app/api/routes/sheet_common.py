"""Helpers shared by the sheet type and the sheet routers (spec 15)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from app.auth.dependencies import AuthContext
from app.sheets.errors import SheetApiError

SYSTEM_PREFIX = "system:"


@contextmanager
def mapped() -> Iterator[None]:
    """Turn a domain error into the API error shape."""
    try:
        yield
    except SheetApiError as exc:
        raise exc.to_http() from None


def actor(auth: AuthContext) -> str:
    """Who is recorded as the author of a write: the user, else the key, else the source."""
    if auth.user:
        # "system:" is reserved for the hub itself (the seeder); a person with such a name
        # must not be mistaken for it.
        return f"user:{auth.user}" if auth.user.startswith(SYSTEM_PREFIX) else auth.user
    return f"key:{auth.api_key_id}" if auth.api_key_id else auth.source
