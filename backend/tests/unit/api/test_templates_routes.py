"""Unit tests for app.api.routes.templates — 1 endpoint, 2 scenarios (Phase 6a Task 2).

Test mapping:
    1. GET /api/templates (unfiltered)  → returns all templates
    2. GET /api/templates?app=snipeit   → returns only templates with app='snipeit'
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4 as _uuid4

import app.models  # noqa: F401 — registers all SQLModel tables with metadata
import pytest
import pytest_asyncio
from app.api.routes.templates import router
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_read
from app.db.engine import _apply_pragmas
from app.db.session import get_session
from app.models.template import Template
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

# ---------------------------------------------------------------------------
# In-memory DB fixtures (same pattern as test_printers_routes.py)
# ---------------------------------------------------------------------------


def _make_engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(eng.sync_engine, "connect", _apply_pragmas)
    return eng


@pytest_asyncio.fixture
async def engine():
    eng = _make_engine()
    async with eng.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s


# ---------------------------------------------------------------------------
# App factory with DB override
# ---------------------------------------------------------------------------


def _build_app(session_override: AsyncSession) -> FastAPI:
    """Return a FastAPI app with the templates router and the DB overridden."""
    app = FastAPI()
    app.include_router(router)

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session_override

    _fake_auth_ctx = AuthContext(
        source="api-key", scope="admin", api_key_id=_uuid4(), ip="127.0.0.1"
    )
    app.dependency_overrides[require_read] = lambda _c=_fake_auth_ctx: _c
    app.dependency_overrides[get_session] = _override_session
    return app


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _make_template(
    session: AsyncSession,
    key: str,
    name: str,
    app_name: str | None = None,
    source: str = "seed",
) -> Template:
    tpl = Template(
        key=key,
        name=name,
        app=app_name,
        printer_model="PT-P750W",
        tape_width_mm=12,
        source=source,
        definition={"elements": []},
    )
    session.add(tpl)
    await session.commit()
    await session.refresh(tpl)
    return tpl


# ---------------------------------------------------------------------------
# Test 1: GET /api/templates — unfiltered, returns all templates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_templates_unfiltered_returns_all(session) -> None:
    """list_templates without ?app= returns every template in the DB."""
    await _make_template(session, "snipeit/asset", "Asset Label", app_name="snipeit")
    await _make_template(session, "grocy/product", "Product Label", app_name="grocy")
    await _make_template(session, "generic/qr", "Generic QR", app_name=None)

    app = _build_app(session)
    client = TestClient(app, raise_server_exceptions=True)
    r = client.get("/api/templates")

    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 3
    keys = {item["key"] for item in body}
    assert keys == {"snipeit/asset", "grocy/product", "generic/qr"}
    # Spot-check required fields
    first = next(item for item in body if item["key"] == "snipeit/asset")
    assert first["name"] == "Asset Label"
    assert first["app"] == "snipeit"
    assert first["tape_width_mm"] == 12
    assert "id" in first
    assert "created_at" in first
    assert "updated_at" in first


# ---------------------------------------------------------------------------
# Test 2: GET /api/templates?app=snipeit — filtered by app
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_templates_filtered_by_app_returns_only_matching(session) -> None:
    """list_templates with ?app=snipeit returns only templates whose app='snipeit'."""
    await _make_template(session, "snipeit/asset", "Asset Label", app_name="snipeit")
    await _make_template(session, "snipeit/location", "Location Label", app_name="snipeit")
    await _make_template(session, "grocy/product", "Product Label", app_name="grocy")

    app = _build_app(session)
    client = TestClient(app, raise_server_exceptions=True)
    r = client.get("/api/templates?app=snipeit")

    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 2
    for item in body:
        assert item["app"] == "snipeit"
    keys = {item["key"] for item in body}
    assert keys == {"snipeit/asset", "snipeit/location"}


# ---------------------------------------------------------------------------
# Direct async tests — bypass TestClient thread to capture coverage correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_templates_direct_no_filter(session) -> None:
    """list_templates called directly (no ?app=) returns all templates.

    Directly exercises lines 51-54 of templates.py in the pytest async loop
    where coverage.py instruments correctly (bypasses TestClient threading).
    """
    from app.api.routes.templates import list_templates

    await _make_template(session, "snipeit/asset", "Asset Label", app_name="snipeit")
    await _make_template(session, "grocy/product", "Product Label", app_name="grocy")

    result = await list_templates(session=session, app=None, _auth=None)

    assert len(result) == 2
    keys = {r.key for r in result}
    assert keys == {"snipeit/asset", "grocy/product"}


@pytest.mark.asyncio
async def test_list_templates_direct_with_app_filter(session) -> None:
    """list_templates called directly with app='snipeit' returns filtered list.

    Exercises lines 52-53 (the ``if app is not None:`` True branch) of
    templates.py in the pytest async loop.
    """
    from app.api.routes.templates import list_templates

    await _make_template(session, "snipeit/asset", "Asset Label", app_name="snipeit")
    await _make_template(session, "grocy/product", "Product Label", app_name="grocy")

    result = await list_templates(session=session, app="snipeit", _auth=None)

    assert len(result) == 1
    assert result[0].key == "snipeit/asset"
    assert result[0].app == "snipeit"


@pytest.mark.asyncio
async def test_list_templates_direct_filter_no_match_returns_empty(session) -> None:
    """list_templates with ?app= that matches nothing returns an empty list.

    Exercises line 53 (filter comprehension with no matches) in the async loop.
    """
    from app.api.routes.templates import list_templates

    await _make_template(session, "snipeit/asset", "Asset Label", app_name="snipeit")

    result = await list_templates(session=session, app="spoolman", _auth=None)

    assert result == []
