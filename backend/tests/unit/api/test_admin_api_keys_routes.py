"""Unit tests for /api/admin/api-keys CRUD endpoints — Phase 7c Step 8."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import app.models  # noqa: F401
import bcrypt
import pytest
from app.api.routes.admin_api_keys import router
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_admin
from app.db.engine import _apply_pragmas
from app.db.session import get_session
from app.models.api_key import ApiKey
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel


def _make_engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(eng.sync_engine, "connect", _apply_pragmas)
    return eng


@pytest.fixture
async def session():
    eng = _make_engine()
    async with eng.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False)
    async with factory() as s:
        yield s
    await eng.dispose()


def _build_app(session: AsyncSession) -> FastAPI:
    app = FastAPI()
    app.include_router(router)

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override_session
    # Bypass auth for unit tests
    _fake_ctx = AuthContext(source="api-key", scope="admin", api_key_id=uuid4(), ip="127.0.0.1")
    app.dependency_overrides[require_admin] = lambda: _fake_ctx
    return app


@pytest.mark.asyncio
async def test_list_api_keys_empty_returns_empty_list(session):
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get("/api/admin/api-keys")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_api_keys_returns_existing_keys(session):
    key = ApiKey(
        name="existing-key", key_hash="fakehash", key_prefix="lh_existing",
        scopes=["read"], allowed_printer_ids=[], enabled=True,
    )
    session.add(key)
    await session.commit()

    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get("/api/admin/api-keys")
    assert resp.status_code == 200
    keys = resp.json()
    assert len(keys) == 1
    assert keys[0]["name"] == "existing-key"
    assert "key_hash" not in keys[0]  # hash must not be exposed
    assert "plaintext" not in keys[0]  # plaintext must not be exposed


@pytest.mark.asyncio
async def test_create_api_key_returns_plaintext_once(session):
    """POST /api/admin/api-keys creates a key and returns plaintext in the response."""
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.post("/api/admin/api-keys", json={
            "name": "new-key",
            "scopes": ["read", "print"],
            "allowed_printer_ids": [],
            "rate_limit_per_minute": 60,
        })
    assert resp.status_code == 201
    body = resp.json()
    assert "plaintext" in body, "plaintext must be returned ONCE on creation"
    assert body["plaintext"].startswith("lh_")
    assert "prefix" in body
    assert "key_id" in body


@pytest.mark.asyncio
async def test_create_api_key_does_not_store_plaintext(session):
    """The DB stores only the hash, not the plaintext."""
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.post("/api/admin/api-keys", json={
            "name": "hash-test",
            "scopes": ["read"],
            "allowed_printer_ids": [],
            "rate_limit_per_minute": 60,
        })
    assert resp.status_code == 201
    plaintext = resp.json()["plaintext"]

    # Fetch the key directly from DB and verify hash
    from sqlalchemy import select
    from app.models.api_key import ApiKey as ApiKeyModel
    result = await session.execute(select(ApiKeyModel).where(ApiKeyModel.name == "hash-test"))
    db_key = result.scalar_one_or_none()
    assert db_key is not None
    assert bcrypt.checkpw(plaintext.encode(), db_key.key_hash.encode())


@pytest.mark.asyncio
async def test_get_api_key_detail_returns_metadata(session):
    key = ApiKey(
        name="detail-key", key_hash="fakehash", key_prefix="lh_detail",
        scopes=["print"], allowed_printer_ids=[], enabled=True,
    )
    session.add(key)
    await session.commit()

    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get(f"/api/admin/api-keys/{key.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "detail-key"
    assert "key_hash" not in body
    assert "plaintext" not in body


@pytest.mark.asyncio
async def test_get_api_key_not_found_returns_404(session):
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get(f"/api/admin/api-keys/{uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_api_key_updates_fields(session):
    key = ApiKey(
        name="to-patch", key_hash="fakehash", key_prefix="lh_topatch",
        scopes=["read"], allowed_printer_ids=[], enabled=True,
        rate_limit_per_minute=60,
    )
    session.add(key)
    await session.commit()

    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.patch(f"/api/admin/api-keys/{key.id}", json={
            "enabled": False,
            "rate_limit_per_minute": 120,
            "notes": "Patched!",
        })
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["rate_limit_per_minute"] == 120
    assert body["notes"] == "Patched!"


@pytest.mark.asyncio
async def test_delete_api_key_revokes_it(session):
    key = ApiKey(
        name="to-delete", key_hash="fakehash", key_prefix="lh_todelete",
        scopes=["read"], allowed_printer_ids=[], enabled=True,
    )
    session.add(key)
    await session.commit()

    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.delete(f"/api/admin/api-keys/{key.id}")
    assert resp.status_code == 204

    # Key should now be disabled in DB
    await session.refresh(key)
    assert key.enabled is False
