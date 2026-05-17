"""Phase 7b Cluster 1c contract test — every datetime field in the API
response must include a timezone suffix (Z or +HH:MM)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
import pytest_asyncio
from app.main import create_app
from app.services.template_loader import TemplateLoader
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio

_SEED_DIR = Path(__file__).parents[3] / "app" / "seed" / "templates"


@pytest_asyncio.fixture
async def api_client_with_seed():
    """AsyncClient against the full app with lifespan (seeds templates into DB).

    The autouse _temp_db_engine fixture (in tests/integration/conftest.py) patches
    _engine_module and _main_module with a per-test SQLite engine. It does NOT
    patch app.db.session, so the get_session dependency used by GET /api/templates
    still holds the original engine binding.

    Strategy:
    1. Propagate the patched engine to app.db.session so the route handler
       uses the same temp DB as the lifespan seeder.
    2. Pre-load TemplateLoader._cache from the seed directory so seed_templates()
       inserts rows (it seeds from the in-memory cache).
    3. Manually seed the DB before the app starts so rows are visible to the
       route without relying on the lifespan's session transaction timing.
    """
    import app.db.engine as _engine_module
    import app.db.session as _session_module
    from app.db.lifespan import seed_templates

    # Propagate the temp engine to the session module so get_session() uses it.
    _session_module.async_session = _engine_module.async_session

    # Pre-load seed templates into the TemplateLoader cache.
    original_cache = dict(TemplateLoader._cache)
    TemplateLoader.load_dir(_SEED_DIR)
    try:
        # Seed the DB directly via the patched session so the route can read rows.
        async with _engine_module.async_session() as s:
            await seed_templates(s, TemplateLoader)

        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            yield c
    finally:
        TemplateLoader._cache = original_cache


def _has_tz_suffix(s: str) -> bool:
    """True if string ends with Z or contains an explicit +/- TZ offset (skip date dashes)."""
    return s.endswith("Z") or "+" in s or "-" in s[10:]


async def test_template_read_has_tz_suffix(api_client_with_seed):
    """GET /api/templates returns datetimes with TZ info that fromisoformat can parse."""
    resp = await api_client_with_seed.get("/api/templates")
    assert resp.status_code == 200
    body = resp.json()
    assert body, "expected at least one seeded template"
    for t in body:
        for field in ("created_at", "updated_at"):
            assert _has_tz_suffix(t[field]), (
                f"template {t.get('key', '?')}: {field}={t[field]!r} missing TZ suffix"
            )
            datetime.fromisoformat(t[field].replace("Z", "+00:00"))
