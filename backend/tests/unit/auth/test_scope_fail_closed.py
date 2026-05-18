"""Unit tests for scope fail-closed behavior — Phase 7c Fixes B and C.

Fix B: _scope_satisfies must raise ValueError for unknown scopes (not silently
       fall back to granting access).

Fix C: A key with scopes=[] must return 401 — not get implicit 'read' access
       from a defaulted effective_scope.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

# --------------------------------------------------------------------------
# Fix B: _scope_satisfies must be fail-closed for unknown scopes
# --------------------------------------------------------------------------


def test_scope_satisfies_raises_for_unknown_scope():
    """_scope_satisfies raises ValueError for an unknown key_scope (Fix B).

    Previously returned a fallback that could grant implicit access.
    Now it must raise ValueError so the caller gets a 403/401 response.
    """
    from app.auth.dependencies import _scope_satisfies

    with pytest.raises(ValueError, match="Unknown scope"):
        _scope_satisfies("unknown_scope_xyz", "read")


def test_scope_satisfies_raises_for_empty_string_scope():
    """Empty string is not a valid scope — must raise ValueError (Fix B)."""
    from app.auth.dependencies import _scope_satisfies

    with pytest.raises(ValueError, match="Unknown scope"):
        _scope_satisfies("", "read")


def test_scope_satisfies_known_scopes_still_work():
    """Known scope values continue to work correctly after Fix B."""
    from app.auth.dependencies import _scope_satisfies

    assert _scope_satisfies("admin", "read") is True
    assert _scope_satisfies("admin", "print") is True
    assert _scope_satisfies("admin", "admin") is True
    assert _scope_satisfies("print", "read") is True
    assert _scope_satisfies("print", "print") is True
    assert _scope_satisfies("print", "admin") is False
    assert _scope_satisfies("read", "read") is True
    assert _scope_satisfies("read", "print") is False
    assert _scope_satisfies("read", "admin") is False


# --------------------------------------------------------------------------
# Fix C: key with empty scopes list must return 401, not implicit read
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_key_with_empty_scopes_returns_401():
    """An API key with scopes=[] must be rejected with 401 (Fix C).

    Previously, effective_scope defaulted to 'read', granting implicit
    read access to keys that have no scopes assigned. Now it must 401.
    """
    import bcrypt
    from app.models.api_key import ApiKey
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlmodel import SQLModel

    plaintext = "lh_pat_empty_scopes_test_c_001aa"
    prefix = plaintext[:16]
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()

    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False)

    async with factory() as s:
        key = ApiKey(
            name="no-scopes",
            key_hash=hashed,
            key_prefix=prefix,
            scopes=[],  # explicitly empty — no access
            allowed_printer_ids=[],
            enabled=True,
        )
        s.add(key)
        await s.commit()

    from app.auth.dependencies import require_scope
    from app.config import Settings
    from app.db.session import get_session
    from fastapi import Depends, FastAPI

    settings = Settings(_env_file=None)
    app_t = FastAPI()

    @app_t.get("/test")
    async def ep(ctx=Depends(require_scope("read", settings=settings))):
        return {"scope": ctx.scope}

    async def _session():
        async with factory() as s:
            yield s

    app_t.dependency_overrides[get_session] = _session

    async with AsyncClient(transport=ASGITransport(app=app_t), base_url="http://t") as client:
        resp = await client.get("/test", headers={"X-Label-Hub-Key": plaintext})

    # Must be 401 (or 403) — NOT 200 with implicit read scope
    assert resp.status_code in (401, 403), (
        f"Expected 401/403 for key with empty scopes, got {resp.status_code}"
    )
    await eng.dispose()
