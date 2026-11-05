"""The author recorded for a sheet or sheet type write (shared by both routers)."""

from __future__ import annotations

from uuid import uuid4

from app.api.routes.sheet_common import actor
from app.auth.dependencies import AuthContext


def _ctx(**kw: object) -> AuthContext:
    base: dict[str, object] = {
        "source": "api-key",
        "scope": "print",
        "api_key_id": None,
        "ip": "192.0.2.1",
    }
    base.update(kw)
    return AuthContext(**base)  # type: ignore[arg-type]


def test_actor_prefers_the_user() -> None:
    ctx = _ctx(source="pangolin-sso", user="alex@example.invalid", api_key_id=uuid4())
    assert actor(ctx) == "alex@example.invalid"


def test_actor_is_the_key_id_without_a_user() -> None:
    key_id = uuid4()
    assert actor(_ctx(api_key_id=key_id)) == f"key:{key_id}"


def test_actor_falls_back_to_the_source() -> None:
    assert actor(_ctx(source="pangolin-bypass", scope="read")) == "pangolin-bypass"
