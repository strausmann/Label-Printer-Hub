"""Unit-Tests für /api/v1/presets CRUD (Phase 1k.3, Refs #104).

Auth über dependency_overrides — analog test_admin_printers_api.py.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import app.models  # noqa: F401
import pytest
from app.api.routes.presets_api import router as presets_router
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_print, require_read
from app.db.engine import _apply_pragmas
from app.db.session import get_session
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


def _build_app(session: AsyncSession, *, with_write: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(presets_router)

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override_session
    read_ctx = AuthContext(source="api-key", scope="read", api_key_id=uuid4(), ip="192.0.2.1")
    app.dependency_overrides[require_read] = lambda: read_ctx
    if with_write:
        print_ctx = AuthContext(source="api-key", scope="print", api_key_id=uuid4(), ip="192.0.2.1")
        app.dependency_overrides[require_print] = lambda: print_ctx
    return app


def _payload(name: str = "Schublade A") -> dict:
    return {
        "name": name,
        "content_type": "qr_three_lines",
        "tape_mm": 12,
        "field_values": {
            "primary_id": "A1",
            "title": "Schrauben",
            "qr_payload": "https://x",
            "secondary": ["M3"],
        },
    }


@pytest.mark.asyncio
async def test_create_then_get(session):
    app = _build_app(session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post("/api/v1/presets", json=_payload())
        assert r.status_code == 201
        pid = r.json()["id"]
        g = await ac.get(f"/api/v1/presets/{pid}")
        assert g.status_code == 200
        assert g.json()["content_type"] == "qr_three_lines"


@pytest.mark.asyncio
async def test_list_returns_created(session):
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        await ac.post("/api/v1/presets", json=_payload())
        r = await ac.get("/api/v1/presets")
        assert r.status_code == 200
        assert len(r.json()) == 1


@pytest.mark.asyncio
async def test_create_duplicate_name_returns_409(session):
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        await ac.post("/api/v1/presets", json=_payload())
        r = await ac.post("/api/v1/presets", json=_payload(name="schublade a"))
        assert r.status_code == 409


@pytest.mark.asyncio
async def test_create_unsupported_tape_returns_422(session):
    app = _build_app(session)
    bad = _payload()
    bad["tape_mm"] = 999
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/api/v1/presets", json=bad)
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_missing_fields_returns_422(session):
    app = _build_app(session)
    bad = _payload()
    bad["field_values"] = {"primary_id": "A1"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/api/v1/presets", json=bad)
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_get_missing_returns_404(session):
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(f"/api/v1/presets/{uuid4()}")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_update_patches(session):
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        pid = (await ac.post("/api/v1/presets", json=_payload())).json()["id"]
        r = await ac.put(f"/api/v1/presets/{pid}", json={"name": "Neu"})
        assert r.status_code == 200
        assert r.json()["name"] == "Neu"


@pytest.mark.asyncio
async def test_delete_returns_204_then_404(session):
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        pid = (await ac.post("/api/v1/presets", json=_payload())).json()["id"]
        d = await ac.delete(f"/api/v1/presets/{pid}")
        assert d.status_code == 204
        assert (await ac.delete(f"/api/v1/presets/{pid}")).status_code == 404


@pytest.mark.asyncio
async def test_write_requires_print_scope(session):
    # Ohne require_print-Override greift die echte Scope-Dependency → 401/403.
    app = _build_app(session, with_write=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/api/v1/presets", json=_payload())
        assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_update_unsupported_tape_returns_422(session):
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        pid = (await ac.post("/api/v1/presets", json=_payload())).json()["id"]
        r = await ac.put(f"/api/v1/presets/{pid}", json={"tape_mm": 999})
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_update_duplicate_name_returns_409(session):
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        await ac.post("/api/v1/presets", json=_payload(name="Erstes"))
        pid2 = (await ac.post("/api/v1/presets", json=_payload(name="Zweites"))).json()["id"]
        r = await ac.put(f"/api/v1/presets/{pid2}", json={"name": "erstes"})
        assert r.status_code == 409


@pytest.mark.asyncio
async def test_preview_png_ok(session):
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        pid = (await ac.post("/api/v1/presets", json=_payload())).json()["id"]
        r = await ac.get(f"/api/v1/presets/{pid}/preview.png")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.asyncio
async def test_preview_png_missing_returns_404(session):
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(f"/api/v1/presets/{uuid4()}/preview.png")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_create_qr_with_listing_returns_422(session):
    """POST mit qr_with_listing muss 422 liefern — nicht 500 (Fix 1)."""
    app = _build_app(session)
    payload = {
        "name": "Listing Preset",
        "content_type": "qr_with_listing",
        "tape_mm": 12,
        "field_values": {"qr_payload": "x", "primary_id": "A1", "items": ["item1"]},
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/api/v1/presets", json=payload)
        assert r.status_code == 422


def test_presets_router_registered_in_app():
    """Smoke-Test: presets-Router ist in der echten App registriert.

    create_app() liefert einen _LifespanManager-Wrapper; die FastAPI-Instanz
    liegt in ._app (Unwrap-Muster aus tests/api/test_openapi_completeness.py).
    """
    from app.main import create_app

    # _LifespanManager-Wrapper aufschalten → innere FastAPI-Instanz
    inner_app = create_app()._app  # type: ignore[attr-defined]
    paths = {r.path for r in inner_app.routes}
    assert "/api/v1/presets" in paths
    assert "/api/v1/presets/{preset_id}/preview.png" in paths
