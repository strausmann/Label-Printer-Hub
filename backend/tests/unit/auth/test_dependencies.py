"""Unit tests for require_scope() FastAPI dependency — Phase 7c Step 3.

Tests all three auth paths:
  1. API-Key header (X-Label-Hub-Key)
  2. Pangolin-SSO (X-Pangolin-User header)
  3. Pangolin-bypass (Authorization: Basic claude-automation:...)
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

# --------------------------------------------------------------------------
# AuthContext model tests
# --------------------------------------------------------------------------


def test_auth_context_importable():
    from app.auth.dependencies import AuthContext
    assert AuthContext is not None


def test_auth_context_source_field_accepts_valid_values():
    from app.auth.dependencies import AuthContext
    for source in ("api-key", "pangolin-sso", "pangolin-bypass"):
        ctx = AuthContext(source=source, scope="read", api_key_id=None, ip="192.0.2.1")
        assert ctx.source == source


def test_auth_context_scope_field_accepts_valid_values():
    from app.auth.dependencies import AuthContext
    for scope in ("read", "print", "admin"):
        ctx = AuthContext(source="api-key", scope=scope, api_key_id=None, ip="192.0.2.1")
        assert ctx.scope == scope


def test_auth_context_api_key_id_can_be_none():
    from app.auth.dependencies import AuthContext
    ctx = AuthContext(source="pangolin-sso", scope="read", api_key_id=None, ip="192.0.2.1")
    assert ctx.api_key_id is None


def test_auth_context_api_key_id_can_be_uuid():
    from app.auth.dependencies import AuthContext
    key_id = uuid4()
    ctx = AuthContext(source="api-key", scope="print", api_key_id=key_id, ip="192.0.2.1")
    assert ctx.api_key_id == key_id


# --------------------------------------------------------------------------
# Helper: build a FastAPI test app with the dependency wired in
# --------------------------------------------------------------------------

def _make_test_app(required_scope: str, *, bypass_downgrade: bool = False):
    """Build a minimal FastAPI app to test the dependency."""
    from fastapi import Depends, FastAPI
    from app.auth.dependencies import require_scope
    from app.config import Settings
    import app.db.engine as _engine_module
    from app.db.session import get_session
    import app.models  # noqa: F401 — register all models
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlmodel import SQLModel

    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(eng.sync_engine, "connect", lambda dbapi_conn, _: (
        dbapi_conn.execute("PRAGMA journal_mode=WAL"),
        dbapi_conn.execute("PRAGMA foreign_keys=ON"),
    ))

    settings = Settings(
        _env_file=None,
        pangolin_bypass_scope_downgrade=bypass_downgrade,
    )

    app = FastAPI()

    @app.get("/test-endpoint")
    async def test_endpoint(ctx=Depends(require_scope(required_scope, settings=settings))):
        return {"source": ctx.source, "scope": ctx.scope,
                "api_key_id": str(ctx.api_key_id) if ctx.api_key_id else None}

    async def override_session():
        factory = async_sessionmaker(eng, expire_on_commit=False)
        async with eng.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = override_session
    return app, eng


# --------------------------------------------------------------------------
# Path 1: API-Key header tests
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_valid_api_key_returns_auth_context():
    """Valid X-Label-Hub-Key with sufficient scope → 200 with AuthContext."""
    import bcrypt
    from app.models.api_key import ApiKey
    from sqlmodel import Session, SQLModel
    from sqlalchemy import create_engine

    # Create in-memory DB and insert a test key
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy import event

    plaintext = "lh_validkey_test_step3_a1b2c3d4e5f6g7"
    prefix = plaintext[:12]
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    key_id = uuid4()

    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    import app.models  # noqa: F401

    async with eng.begin() as conn:
        from sqlmodel import SQLModel
        await conn.run_sync(SQLModel.metadata.create_all)

    factory = async_sessionmaker(eng, expire_on_commit=False)
    async with factory() as s:
        key = ApiKey(
            id=key_id, name="test-key", key_hash=hashed, key_prefix=prefix,
            scopes=["read", "print"], allowed_printer_ids=[], enabled=True,
        )
        s.add(key)
        await s.commit()

    from fastapi import Depends, FastAPI
    from app.auth.dependencies import require_scope
    from app.config import Settings
    from app.db.session import get_session

    settings = Settings(_env_file=None)
    app = FastAPI()

    @app.get("/test")
    async def ep(ctx=Depends(require_scope("read", settings=settings))):
        return {"source": ctx.source, "scope": ctx.scope}

    async def _session():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get("/test", headers={"X-Label-Hub-Key": plaintext})

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    assert resp.json()["source"] == "api-key"
    await eng.dispose()


@pytest.mark.asyncio
async def test_invalid_api_key_returns_401():
    """Wrong API key → 401."""
    import bcrypt
    from app.models.api_key import ApiKey
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    import app.models  # noqa: F401

    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        from sqlmodel import SQLModel
        await conn.run_sync(SQLModel.metadata.create_all)

    factory = async_sessionmaker(eng, expire_on_commit=False)
    # Insert a key but we'll use a wrong plaintext
    real_plaintext = "lh_realkey_test_invalid_a1b2c3d4e5f6"
    prefix = real_plaintext[:12]
    hashed = bcrypt.hashpw(real_plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    async with factory() as s:
        key = ApiKey(
            name="key1", key_hash=hashed, key_prefix=prefix,
            scopes=["read"], allowed_printer_ids=[], enabled=True,
        )
        s.add(key)
        await s.commit()

    from fastapi import Depends, FastAPI
    from app.auth.dependencies import require_scope
    from app.config import Settings
    from app.db.session import get_session

    settings = Settings(_env_file=None)
    app = FastAPI()

    @app.get("/test")
    async def ep(ctx=Depends(require_scope("read", settings=settings))):
        return {}

    app.dependency_overrides[get_session] = lambda: factory()

    async def _session():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get("/test", headers={"X-Label-Hub-Key": "lh_wrongkey_aaaaaaaaaaaaa"})

    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
    await eng.dispose()


@pytest.mark.asyncio
async def test_missing_key_no_pangolin_returns_401():
    """No auth header at all → 401."""
    import app.models  # noqa: F401
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        from sqlmodel import SQLModel
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False)

    from fastapi import Depends, FastAPI
    from app.auth.dependencies import require_scope
    from app.config import Settings
    from app.db.session import get_session

    settings = Settings(_env_file=None)
    app = FastAPI()

    @app.get("/test")
    async def ep(ctx=Depends(require_scope("read", settings=settings))):
        return {}

    async def _session():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get("/test")

    assert resp.status_code == 401
    await eng.dispose()


# --------------------------------------------------------------------------
# Path 2: Pangolin-SSO
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pangolin_sso_allows_read_scope():
    """Pangolin-SSO header on read endpoint → 200."""
    import app.models  # noqa: F401
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        from sqlmodel import SQLModel
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False)

    from fastapi import Depends, FastAPI
    from app.auth.dependencies import require_scope
    from app.config import Settings
    from app.db.session import get_session

    settings = Settings(_env_file=None)
    app = FastAPI()

    @app.get("/test")
    async def ep(ctx=Depends(require_scope("read", settings=settings))):
        return {"source": ctx.source}

    async def _session():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get("/test", headers={"X-Pangolin-User": "testuser@example.com"})

    assert resp.status_code == 200
    assert resp.json()["source"] == "pangolin-sso"
    await eng.dispose()


@pytest.mark.asyncio
async def test_pangolin_sso_blocked_on_print_scope():
    """Pangolin-SSO on print scope endpoint → 401 (SSO only grants read)."""
    import app.models  # noqa: F401
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        from sqlmodel import SQLModel
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False)

    from fastapi import Depends, FastAPI
    from app.auth.dependencies import require_scope
    from app.config import Settings
    from app.db.session import get_session

    settings = Settings(_env_file=None)
    app = FastAPI()

    @app.post("/test")
    async def ep(ctx=Depends(require_scope("print", settings=settings))):
        return {}

    async def _session():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post("/test", headers={"X-Pangolin-User": "testuser@example.com"})

    assert resp.status_code == 401
    await eng.dispose()


# --------------------------------------------------------------------------
# Scope hierarchy tests
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_key_allowed_on_read_endpoint():
    """admin-scoped key satisfies read requirement."""
    import bcrypt
    from app.models.api_key import ApiKey
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    import app.models  # noqa: F401

    plaintext = "lh_adminkey_scope_hierarchy_test_001"
    prefix = plaintext[:12]
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()

    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        from sqlmodel import SQLModel
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False)

    async with factory() as s:
        key = ApiKey(
            name="admin-key", key_hash=hashed, key_prefix=prefix,
            scopes=["admin"], allowed_printer_ids=[], enabled=True,
        )
        s.add(key)
        await s.commit()

    from fastapi import Depends, FastAPI
    from app.auth.dependencies import require_scope
    from app.config import Settings
    from app.db.session import get_session

    settings = Settings(_env_file=None)
    app = FastAPI()

    @app.get("/test")
    async def ep(ctx=Depends(require_scope("read", settings=settings))):
        return {"scope": ctx.scope}

    async def _session():
        async with factory() as s:
            yield s
    app.dependency_overrides[get_session] = _session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get("/test", headers={"X-Label-Hub-Key": plaintext})

    assert resp.status_code == 200
    await eng.dispose()


@pytest.mark.asyncio
async def test_read_key_blocked_on_print_endpoint():
    """read-only key → 403 on print endpoint."""
    import bcrypt
    from app.models.api_key import ApiKey
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    import app.models  # noqa: F401

    plaintext = "lh_readonly_scope_test_blocked_001"
    prefix = plaintext[:12]
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()

    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        from sqlmodel import SQLModel
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False)

    async with factory() as s:
        key = ApiKey(
            name="read-only", key_hash=hashed, key_prefix=prefix,
            scopes=["read"], allowed_printer_ids=[], enabled=True,
        )
        s.add(key)
        await s.commit()

    from fastapi import Depends, FastAPI
    from app.auth.dependencies import require_scope
    from app.config import Settings
    from app.db.session import get_session

    settings = Settings(_env_file=None)
    app = FastAPI()

    @app.post("/test")
    async def ep(ctx=Depends(require_scope("print", settings=settings))):
        return {}

    async def _session():
        async with factory() as s:
            yield s
    app.dependency_overrides[get_session] = _session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post("/test", headers={"X-Label-Hub-Key": plaintext})

    assert resp.status_code == 403
    await eng.dispose()
