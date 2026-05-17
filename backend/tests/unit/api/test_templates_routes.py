"""Unit tests for app.api.routes.templates — 1 endpoint, 2 scenarios (Phase 6a Task 2).

Test mapping:
    1. GET /api/templates (unfiltered)  → returns all templates
    2. GET /api/templates?app=snipeit   → returns only templates with app='snipeit'
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import app.models  # noqa: F401 — registers all SQLModel tables with metadata
import pytest
import pytest_asyncio
from app.api.routes.templates import render_router, router
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
    app.include_router(render_router)

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session_override

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
    preview_sample: dict[str, object] | None = None,
) -> Template:
    definition: dict[str, object] = {"elements": []}
    if preview_sample is not None:
        definition["preview_sample"] = preview_sample
    tpl = Template(
        key=key,
        name=name,
        app=app_name,
        printer_model="PT-P750W",
        tape_width_mm=12,
        source=source,
        definition=definition,
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

    result = await list_templates(session=session, app=None)

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

    result = await list_templates(session=session, app="snipeit")

    assert len(result) == 1
    assert result[0].key == "snipeit/asset"
    assert result[0].app == "snipeit"


@pytest.mark.asyncio
async def test_template_preview_returns_png(session) -> None:
    """POST /api/render/preview?key=<key> renders a sample label as PNG bytes.

    Regression for Bug 3 — the backend had no preview endpoint.
    The frontend template detail page fell back to preview-placeholder.svg
    because POST /api/render/preview always returned 404.
    """
    await _make_template(
        session,
        "snipeit/asset",
        "Asset Label",
        app_name="snipeit",
        preview_sample={
            "primary_id": "ASSET-2024-001",
            "title": "Dell Latitude 7430",
            "qr_payload": "https://snipeit.example.com/hardware/123",
        },
    )

    app = _build_app(session)
    client = TestClient(app, raise_server_exceptions=True)
    r = client.post("/api/render/preview?key=snipeit%2Fasset")

    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic number


@pytest.mark.asyncio
async def test_template_preview_unknown_key_returns_404(session) -> None:
    """POST /api/render/preview?key=<unknown> returns 404 for a missing template."""
    app = _build_app(session)
    client = TestClient(app, raise_server_exceptions=True)
    r = client.post("/api/render/preview?key=no-such-key")

    assert r.status_code == 404


@pytest.mark.asyncio
async def test_template_preview_uses_preview_sample_from_definition(session) -> None:
    """The preview endpoint reads sample values from template.definition.preview_sample.

    Regression for Commit 4 refactor — sample data must live in the template
    definition, not be hardcoded per-app in the route. A template without
    preview_sample must return 422; a template WITH preview_sample renders.
    """
    await _make_template(
        session,
        "custom/key",
        "Custom Template",
        app_name=None,  # no integration app — only works because preview_sample is on the template
        preview_sample={
            "primary_id": "CUSTOM-1",
            "title": "User-defined preview",
            "qr_payload": "https://example.com/custom/1",
        },
    )

    app = _build_app(session)
    client = TestClient(app, raise_server_exceptions=True)
    r = client.post("/api/render/preview?key=custom%2Fkey")

    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.asyncio
async def test_template_preview_renders_seed_template_via_loader_pipeline(session) -> None:
    """End-to-end: a real seed YAML survives the TemplateLoader → seed_db pipeline
    with its preview_sample intact, and the preview endpoint renders it.

    This guards against silent loss of preview_sample if a future refactor
    breaks the schema_dump → DB → schema_construct round-trip.
    """
    from pathlib import Path

    from app.integrations import _discover_plugins
    from app.integrations.registry import IntegrationRegistry
    from app.services.template_loader import TemplateLoader

    # IntegrationRegistry is a class-level singleton that other tests may have
    # cleared. The seed-template loader validates `app` against the registry,
    # so re-discover plugins here to make the test hermetic regardless of
    # test ordering in the full suite.
    if not IntegrationRegistry.names():
        _discover_plugins()

    seed_dir = Path(__file__).resolve().parents[3] / "app" / "seed" / "templates"
    # The loader caches at the class level — clear first so the test is hermetic.
    TemplateLoader._cache.clear()
    TemplateLoader.load_dir(seed_dir)
    await TemplateLoader.seed_db(session)

    app = _build_app(session)
    client = TestClient(app, raise_server_exceptions=True)
    r = client.post("/api/render/preview?key=snipeit-12mm")

    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.asyncio
async def test_template_preview_fails_when_template_lacks_preview_sample(session) -> None:
    """Templates without preview_sample return 422 with a clear error message.

    The previous implementation guessed sample data per-app — wrong responsibility
    locality. Templates must declare their own preview values; the route no
    longer fabricates fallbacks.
    """
    await _make_template(
        session,
        "incomplete/template",
        "No Preview Sample",
        app_name="snipeit",
        preview_sample=None,  # explicit: definition has no preview_sample block
    )

    app = _build_app(session)
    client = TestClient(app, raise_server_exceptions=True)
    r = client.post("/api/render/preview?key=incomplete%2Ftemplate")

    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "preview_sample" in detail
    assert "incomplete/template" in detail


@pytest.mark.asyncio
async def test_list_templates_direct_filter_no_match_returns_empty(session) -> None:
    """list_templates with ?app= that matches nothing returns an empty list.

    Exercises line 53 (filter comprehension with no matches) in the async loop.
    """
    from app.api.routes.templates import list_templates

    await _make_template(session, "snipeit/asset", "Asset Label", app_name="snipeit")

    result = await list_templates(session=session, app="spoolman")

    assert result == []
