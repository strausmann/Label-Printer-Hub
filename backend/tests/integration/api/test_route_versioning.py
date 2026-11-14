# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Every API route lives under ``/api/v1`` (#226).

The app is built with the ``dist`` fixture so the SPA catch-all exists and the walk sees the
full route table. The walk helper recurses into included routers; a naive ``app.routes`` loop
sees almost nothing and would let the guard pass vacuously, so the first test pins the walk.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import app.models  # noqa: F401
import pytest
from app.config import get_settings
from httpx import AsyncClient

from tests.helpers.routes import iter_routes
from tests.helpers.spa import INDEX_HTML

ALLOWED_UNVERSIONED = frozenset(
    {
        "/healthz",
        "/readiness",
        "/openapi.json",
        "/docs",
        "/docs/scalar.js",
        "/loc/{entity_id}",
        "/asset/{entity_id}",
        "/spool/{entity_id}",
        "/product/{entity_id}",
        "/{full_path:path}",
    }
)
FAKE_BOOTSTRAP_KEY = "fake-bootstrap-key-for-tests-0123456789ab"


def _walk(spa: AsyncClient) -> list[tuple[str, str]]:
    """``(path, methods)`` for every route of the real app, routers flattened."""
    inner = spa.app._app  # type: ignore[attr-defined]
    return [
        (str(route.path), ",".join(sorted(getattr(route, "methods", None) or [])))
        for route in iter_routes(inner.routes)
    ]


def test_route_walk_is_not_vacuous(spa: AsyncClient) -> None:
    paths = [path for path, _ in _walk(spa)]
    assert "/api/v1/admin/printers" in paths
    assert len(paths) >= 80


def test_walk_helper_beats_the_naive_walk(spa: AsyncClient) -> None:
    """Counter-test: the naive ``app.routes`` loop sees too few routes for the walk test."""
    inner = spa.app._app  # type: ignore[attr-defined]
    naive = [str(getattr(route, "path", "")) for route in inner.routes]
    assert "/api/v1/admin/printers" not in naive
    assert len(naive) < 80


def test_every_api_route_is_versioned(spa: AsyncClient) -> None:
    offenders = [
        f"{methods} {path}"
        for path, methods in _walk(spa)
        if not path.startswith("/api/v1/") and path not in ALLOWED_UNVERSIONED
    ]
    assert offenders == [], "routes outside /api/v1:\n" + "\n".join(sorted(offenders))


def test_allow_list_has_no_dead_entries(spa: AsyncClient) -> None:
    present = {path for path, _ in _walk(spa)}
    dead = sorted(ALLOWED_UNVERSIONED - present)
    assert dead == [], f"allow-list entries that are no route: {dead}"


@pytest.mark.parametrize("accept", ["*/*", "application/json", "text/html"])
async def test_spa_owns_former_legacy_job_path(spa: AsyncClient, accept: str) -> None:
    resp = await spa.get("/jobs/123", headers={"Accept": accept})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert resp.text == INDEX_HTML


async def test_bootstrap_session_creates_first_key_on_v1_path(
    spa: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LABELYARD_BOOTSTRAP_ADMIN_KEY", FAKE_BOOTSTRAP_KEY)
    get_settings.cache_clear()
    signed_in = await spa.post("/api/v1/auth/session", json={"key": FAKE_BOOTSTRAP_KEY})
    assert signed_in.status_code == 204, signed_in.text
    future = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    resp = await spa.post(
        "/api/v1/admin/api-keys",
        json={"name": "first-admin", "scopes": ["admin"], "expires_at": future},
        headers={"X-CSRF-Token": spa.cookies.get("lph_csrf")},
    )
    assert resp.status_code == 201, resp.text


async def test_sheet_print_validation_does_not_echo_input(spa: AsyncClient) -> None:
    """A stale ``_SHEET_PRINT_PATH`` would let FastAPI echo the rejected input back."""
    from app.api.dependencies.webhook_auth import require_webhook_key
    from app.auth.dependencies import AuthContext
    from app.auth.scope_deps import require_admin, require_print, require_read

    fake = AuthContext(source="api-key", scope="admin", api_key_id=None, ip="192.0.2.1")
    overrides = spa.app._app.dependency_overrides  # type: ignore[attr-defined]
    for dep in (require_read, require_print, require_admin):
        overrides[dep] = lambda _c=fake: _c
    overrides[require_webhook_key] = lambda: None
    secret = "echo-me-0123456789ab"
    try:
        sheet = await spa.post("/api/v1/print/some-printer/sheet", json={"items": secret})
        assert sheet.status_code == 422, sheet.text
        assert secret not in sheet.text
        preview = await spa.post("/api/v1/print/some-printer/sheet/preview", json={"items": secret})
        assert preview.status_code == 422, preview.text
        assert secret not in preview.text
        hook = await spa.post("/api/v1/webhook/grocy", json={"product_id": "1", "quantity": secret})
        assert hook.status_code == 422, hook.text
        assert secret not in hook.text
    finally:
        overrides.clear()
