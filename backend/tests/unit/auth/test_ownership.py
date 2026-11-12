"""#294: who may see a job or tape run of a given owner key."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.auth.dependencies import AuthContext
from app.auth.ownership import may_see, owner_only

KEY = uuid4()


def _ctx(source: str, scope: str, key=KEY) -> AuthContext:
    return AuthContext(source=source, scope=scope, api_key_id=key, ip="127.0.0.1")  # type: ignore[arg-type]


@pytest.mark.parametrize("source", ["api-key", "session"])
@pytest.mark.parametrize("scope", ["read", "print"])
def test_a_plain_key_sees_only_its_own(source: str, scope: str) -> None:
    """The header key and a browser session signed in with it are bound alike (fix round 1)."""
    ctx = _ctx(source, scope)
    assert owner_only(ctx)
    assert may_see(ctx, KEY) and may_see(ctx, str(KEY))
    assert not may_see(ctx, uuid4())
    assert not may_see(ctx, None)  # no owner key: belongs to no API key
    assert not may_see(ctx, "pangolin-sso")  # a batch a browser user created


def test_a_plain_key_without_an_id_sees_nothing() -> None:
    assert not may_see(_ctx("api-key", "print", key=None), None)


@pytest.mark.parametrize(
    ("source", "scope"),
    [
        ("api-key", "admin"),
        ("session", "admin"),
        ("pangolin-sso", "admin"),
        ("pangolin-bypass", "read"),
        ("bootstrap", "admin"),
    ],
)
def test_admin_keys_sessions_and_sso_see_everything(source: str, scope: str) -> None:
    """Admin scope, or no key behind the caller (SSO, trusted header, bootstrap)."""
    key = KEY if scope == "admin" and source in ("api-key", "session") else None
    ctx = _ctx(source, scope, key=key)
    assert not owner_only(ctx)
    assert may_see(ctx, None) and may_see(ctx, uuid4())


def test_no_auth_context_is_not_restricted_here() -> None:
    """Routes without credentials are refused by the scope dependency, not by this helper."""
    assert not owner_only(None) and may_see(None, None)


def test_a_sheet_batch_owner_reads_as_the_key() -> None:
    """Fix round 2 (I-1): the write actor of a key is ``key:<uuid>``; both forms are the key."""
    from app.auth.ownership import key_actor, owner_key_of

    ctx = _ctx("api-key", "print")
    assert key_actor(KEY) == f"key:{KEY}"
    assert owner_key_of(f"key:{KEY}") == owner_key_of(str(KEY)) == owner_key_of(KEY) == str(KEY)
    assert may_see(ctx, f"key:{KEY}")
    assert not may_see(ctx, f"key:{uuid4()}")
    for not_a_key in ("alice", "pangolin-sso", "session", "key:", "key:not-a-uuid", "user:x"):
        assert owner_key_of(not_a_key) is None
        assert not may_see(ctx, not_a_key)


@pytest.mark.parametrize("name", [f"key:{KEY}", str(KEY), "system:seed"])
def test_a_user_name_cannot_pose_as_a_key_or_the_hub(name: str) -> None:
    """An SSO user whose name looks like a key actor (or the hub) is recorded as ``user:…``,
    so a batch they print never reads as that key's."""
    from app.api.routes.sheet_common import actor
    from app.auth.ownership import owner_key_of

    sso = AuthContext(
        source="pangolin-sso", scope="admin", api_key_id=None, ip="127.0.0.1", user=name
    )
    recorded = actor(sso)
    assert recorded == f"user:{name}"
    assert owner_key_of(recorded) is None


_LENIENT = [
    str(KEY).upper(),
    str(KEY).replace("-", ""),
    "{" + str(KEY) + "}",
    f"urn:uuid:{KEY}",
    f" {KEY}",
    f"{KEY} ",
    str(KEY).translate({ord(d): 0x0660 + int(d) for d in "0123456789"}),  # Arabic-Indic
    "KEY:" + str(KEY),
]


@pytest.mark.parametrize("variant", _LENIENT + [f"key:{v}" for v in _LENIENT[:7]])
def test_only_the_canonical_form_reads_as_a_key(variant: str) -> None:
    """Fix round 3 (N-1): ``UUID()`` accepts many spellings; a stored owner names a key only
    in the exact form the hub writes, so a legacy user name shaped like a key never passes."""
    from app.auth.ownership import owner_key_of

    assert owner_key_of(variant) is None
    assert not may_see(_ctx("api-key", "print"), variant)


def test_the_canonical_forms_read_as_the_key() -> None:
    from app.auth.ownership import owner_key_of

    assert owner_key_of(str(KEY)) == owner_key_of(f"key:{KEY}") == owner_key_of(KEY) == str(KEY)


@pytest.mark.parametrize("name", ["{" + str(KEY) + "}", f"urn:uuid:{KEY}", str(KEY).upper()])
def test_lenient_key_spellings_are_still_reserved_on_write(name: str) -> None:
    """The write side stays lenient (the safe direction): such a user name is stored as
    ``user:<name>``."""
    from app.api.routes.sheet_common import actor

    sso = AuthContext(
        source="pangolin-sso", scope="admin", api_key_id=None, ip="127.0.0.1", user=name
    )
    assert actor(sso) == f"user:{name}"
