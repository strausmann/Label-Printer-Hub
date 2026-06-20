"""Unit-Tests für /api/v1/admin/printers CRUD-Endpoints (Issue #124, Task 3.1).

TDD: Tests wurden vor der Implementation geschrieben.
Alle IPs aus RFC-5737 Bereich (192.0.2.x) — Repo-Konvention.

Auth wird über dependency_overrides gemockt — analog test_admin_api_keys_routes.py.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import app.models  # noqa: F401 — registriert alle Models mit SQLModel.metadata
import pytest
from app.api.routes.admin_printers_api import router as admin_printers_router
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_admin
from app.db.engine import _apply_pragmas
from app.db.session import get_session
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


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
    """Baut eine Test-FastAPI-App mit dem admin_printers_api-Router.

    Auth und Session werden über dependency_overrides gemockt.
    """
    app = FastAPI()
    app.include_router(admin_printers_router)

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override_session
    # Auth-Bypass für Unit-Tests — analog test_admin_api_keys_routes.py
    _fake_ctx = AuthContext(source="api-key", scope="admin", api_key_id=uuid4(), ip="192.0.2.1")
    app.dependency_overrides[require_admin] = lambda: _fake_ctx
    return app


def _printer_payload(
    *,
    name: str = "Test Drucker",
    slug: str = "test-drucker",
    model: str = "PT-P750W",
    backend: str = "ptouch",
    host: str = "192.0.2.10",
    port: int = 9100,
) -> dict:
    return {
        "name": name,
        "slug": slug,
        "model": model,
        "backend": backend,
        "connection": {"host": host, "port": port},
    }


# ---------------------------------------------------------------------------
# GET /api/v1/admin/printers — Listenendpunkt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_printers_empty_returns_empty_list(session):
    """Leere DB → leere Liste, Status 200."""
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get("/api/v1/admin/printers")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_printers_returns_existing_enabled_printer(session):
    """Ein aktivierter Drucker wird in der Liste zurückgegeben."""
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        # Erst anlegen
        create_resp = await c.post("/api/v1/admin/printers", json=_printer_payload())
        assert create_resp.status_code == 201

        # Dann listen
        resp = await c.get("/api/v1/admin/printers")
    assert resp.status_code == 200
    printers = resp.json()
    assert len(printers) == 1
    assert printers[0]["slug"] == "test-drucker"
    assert printers[0]["enabled"] is True


@pytest.mark.asyncio
async def test_list_printers_excludes_disabled_by_default(session):
    """Standard-Liste zeigt keine deaktivierten Drucker."""
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        # Anlegen und direkt deaktivieren
        await c.post("/api/v1/admin/printers", json=_printer_payload())
        await c.post("/api/v1/admin/printers/test-drucker/disable")

        resp = await c.get("/api/v1/admin/printers")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_printers_include_disabled_returns_disabled(session):
    """?include_disabled=true zeigt auch deaktivierte Drucker."""
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.post("/api/v1/admin/printers", json=_printer_payload())
        await c.post("/api/v1/admin/printers/test-drucker/disable")

        resp = await c.get("/api/v1/admin/printers?include_disabled=true")
    assert resp.status_code == 200
    printers = resp.json()
    assert len(printers) == 1
    assert printers[0]["enabled"] is False


# ---------------------------------------------------------------------------
# POST /api/v1/admin/printers — Erstellen
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_printer_returns_201_with_body(session):
    """POST liefert 201 + vollständigen Body zurück."""
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.post("/api/v1/admin/printers", json=_printer_payload())
    assert resp.status_code == 201
    body = resp.json()
    assert body["slug"] == "test-drucker"
    assert body["name"] == "Test Drucker"
    assert body["model"] == "PT-P750W"
    assert body["backend"] == "ptouch"
    assert body["enabled"] is True
    assert "id" in body
    assert "created_at" in body
    assert "updated_at" in body


@pytest.mark.asyncio
async def test_create_printer_duplicate_slug_returns_409(session):
    """Doppelter Slug → 409 Conflict."""
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.post("/api/v1/admin/printers", json=_printer_payload())
        # Selber Slug, anderer Name
        resp = await c.post(
            "/api/v1/admin/printers",
            json=_printer_payload(name="Anderer Name", host="192.0.2.11"),
        )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["error_code"] == "duplicate_slug"


@pytest.mark.asyncio
async def test_create_printer_duplicate_name_returns_409(session):
    """Doppelter Name → 409 Conflict."""
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.post("/api/v1/admin/printers", json=_printer_payload())
        # Selber Name, anderer Slug
        resp = await c.post(
            "/api/v1/admin/printers",
            json=_printer_payload(slug="anderer-slug", host="192.0.2.11"),
        )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["error_code"] == "duplicate_name"


# ---------------------------------------------------------------------------
# GET /api/v1/admin/printers/{slug} — Einzelner Drucker
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_printer_by_slug_returns_200_with_body(session):
    """Vorhandener Slug → 200 + vollständiger Body."""
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.post("/api/v1/admin/printers", json=_printer_payload())
        resp = await c.get("/api/v1/admin/printers/test-drucker")
    assert resp.status_code == 200
    body = resp.json()
    assert body["slug"] == "test-drucker"
    assert body["name"] == "Test Drucker"


@pytest.mark.asyncio
async def test_get_printer_by_slug_not_found_returns_404(session):
    """Unbekannter Slug → 404."""
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get("/api/v1/admin/printers/nicht-vorhanden")
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["error_code"] == "not_found"


# ---------------------------------------------------------------------------
# PUT /api/v1/admin/printers/{slug} — Aktualisieren
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_printer_updates_name_returns_200(session):
    """PUT mit geändertem Namen → 200 + aktualisierter Body."""
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.post("/api/v1/admin/printers", json=_printer_payload())
        resp = await c.put(
            "/api/v1/admin/printers/test-drucker",
            json={"name": "Umbenannter Drucker"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Umbenannter Drucker"
    assert body["slug"] == "test-drucker"  # Slug bleibt unverändert


@pytest.mark.asyncio
async def test_put_printer_not_found_returns_404(session):
    """PUT auf unbekannten Slug → 404."""
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.put(
            "/api/v1/admin/printers/nicht-vorhanden",
            json={"name": "Irrelevant"},
        )
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["error_code"] == "not_found"


# ---------------------------------------------------------------------------
# POST /api/v1/admin/printers/{slug}/disable — Deaktivieren
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disable_printer_returns_200_with_enabled_false(session):
    """Aktivierten Drucker deaktivieren → 200, enabled=false."""
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.post("/api/v1/admin/printers", json=_printer_payload())
        resp = await c.post("/api/v1/admin/printers/test-drucker/disable")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False


@pytest.mark.asyncio
async def test_disable_already_disabled_printer_returns_409(session):
    """Bereits deaktivierten Drucker nochmals deaktivieren → 409."""
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.post("/api/v1/admin/printers", json=_printer_payload())
        await c.post("/api/v1/admin/printers/test-drucker/disable")
        resp = await c.post("/api/v1/admin/printers/test-drucker/disable")
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["error_code"] == "already_disabled"


@pytest.mark.asyncio
async def test_disable_not_found_returns_404(session):
    """Deaktivieren eines nicht-existenten Druckers → 404."""
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.post("/api/v1/admin/printers/nicht-vorhanden/disable")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/admin/printers/{slug}/enable — Aktivieren
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enable_printer_after_disable_returns_200(session):
    """Deaktivierten Drucker aktivieren → 200, enabled=true."""
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.post("/api/v1/admin/printers", json=_printer_payload())
        await c.post("/api/v1/admin/printers/test-drucker/disable")
        resp = await c.post("/api/v1/admin/printers/test-drucker/enable")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True


@pytest.mark.asyncio
async def test_enable_already_enabled_printer_returns_409(session):
    """Bereits aktiven Drucker aktivieren → 409."""
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.post("/api/v1/admin/printers", json=_printer_payload())
        resp = await c.post("/api/v1/admin/printers/test-drucker/enable")
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["error_code"] == "already_enabled"


@pytest.mark.asyncio
async def test_enable_not_found_returns_404(session):
    """Aktivieren eines nicht-existenten Druckers → 404."""
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.post("/api/v1/admin/printers/nicht-vorhanden/enable")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Auth-Überprüfung — 401 ohne Credentials
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_printers_pangolin_bypass_uses_source_as_audit_user(session):
    """Pangolin-Bypass-Auth (api_key_id=None) erzeugt audit_user aus source:ip."""
    # Überschreibe require_admin mit einem Auth-Kontext ohne api_key_id
    from app.api.routes.admin_printers_api import router

    app = FastAPI()
    app.include_router(router)

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override_session
    # Kein api_key_id — simuliert Pangolin-SSO oder -Bypass
    _bypass_ctx = AuthContext(
        source="pangolin-bypass",
        scope="admin",
        api_key_id=None,
        ip="192.0.2.99",
    )
    app.dependency_overrides[require_admin] = lambda: _bypass_ctx

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.get("/api/v1/admin/printers")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_list_printers_without_auth_returns_401():
    """Endpunkt ohne Auth → 401 (keine dependency_overrides)."""
    from app.config import Settings, get_settings

    no_auth_app = FastAPI()
    no_auth_app.include_router(admin_printers_router)

    # Session-Override damit die DB-Verbindung nicht fehlt
    eng = _make_engine()
    async with eng.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False)
    session = factory()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with session as s:
            yield s

    no_auth_app.dependency_overrides[get_session] = _override_session
    # Settings mit deaktiviertem SSO-Trust-Token → Pangolin-SSO-Bypass geschlossen
    no_auth_app.dependency_overrides[get_settings] = lambda: Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        sso_trust_token="",
    )

    async with AsyncClient(transport=ASGITransport(app=no_auth_app), base_url="http://t") as c:
        resp = await c.get("/api/v1/admin/printers")
    await eng.dispose()
    assert resp.status_code == 401
