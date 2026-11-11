"""#294: who may see a job or tape run of a given owner key."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.auth.dependencies import AuthContext
from app.auth.ownership import may_see, owner_only

KEY = uuid4()


def _ctx(source: str, scope: str, key=KEY) -> AuthContext:
    return AuthContext(source=source, scope=scope, api_key_id=key, ip="127.0.0.1")  # type: ignore[arg-type]


@pytest.mark.parametrize("scope", ["read", "print"])
def test_a_plain_key_sees_only_its_own(scope: str) -> None:
    ctx = _ctx("api-key", scope)
    assert owner_only(ctx)
    assert may_see(ctx, KEY) and may_see(ctx, str(KEY))
    assert not may_see(ctx, uuid4())
    assert not may_see(ctx, None)  # no owner key: belongs to no API key
    assert not may_see(ctx, "pangolin-sso")  # a batch a browser user created


def test_a_plain_key_without_an_id_sees_nothing() -> None:
    assert not may_see(_ctx("api-key", "print", key=None), None)


@pytest.mark.parametrize(
    ("source", "scope"),
    [("api-key", "admin"), ("session", "print"), ("pangolin-sso", "admin"), ("bootstrap", "admin")],
)
def test_admin_keys_sessions_and_sso_see_everything(source: str, scope: str) -> None:
    ctx = _ctx(source, scope)
    assert not owner_only(ctx)
    assert may_see(ctx, None) and may_see(ctx, uuid4())


def test_no_auth_context_is_not_restricted_here() -> None:
    """Routes without credentials are refused by the scope dependency, not by this helper."""
    assert not owner_only(None) and may_see(None, None)
