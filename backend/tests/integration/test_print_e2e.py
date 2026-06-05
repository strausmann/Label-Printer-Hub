"""End-to-end integration tests for POST /print → GET /jobs/{id}.

Phase 1k.1a (Task 25): Adapted from template_id-based to content_type-based API.
test_template_not_found_synchronous_404 removed (TemplateNotFoundError gone).
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_print, require_read
from app.config import get_settings
from app.main import create_app
from app.printer_backends import BackendRegistry
from app.printer_models.registry import ModelRegistry
from app.services.backend_router import BackendRouter
from httpx import ASGITransport, AsyncClient

_FAKE_AUTH = AuthContext(source="api-key", scope="admin", api_key_id=uuid4(), ip="127.0.0.1")


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch: pytest.MonkeyPatch):
    # Phase 1i CA-1: Die alten Env-Vars sind entfernt.
    # _mock_backend_env (autouse, conftest.py) setzt bereits PRINTER_HUB_PRINTERS_CONFIG
    # und patcht _build_backend_from_config auf MockPrinterBackend.
    # Hier nur Registry-Reset + cache clear.
    BackendRegistry._factories.clear()
    BackendRegistry._discovered = False
    ModelRegistry._models.clear()
    ModelRegistry._discovered = False
    get_settings.cache_clear()
    yield
    BackendRegistry._factories.clear()
    ModelRegistry._models.clear()
    get_settings.cache_clear()


async def _poll_until(c: AsyncClient, job_id: str, *, target: str, timeout_s: float = 5.0) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout_s
    body: dict = {}
    while asyncio.get_event_loop().time() < deadline:
        r = await c.get(f"/jobs/{job_id}")
        assert r.status_code == 200, f"GET /jobs/{job_id} returned {r.status_code}"
        body = r.json()
        if body["status"] == target:
            return body
        if body["status"] == "failed":
            return body
        await asyncio.sleep(0.05)
    raise AssertionError(f"job {job_id} never reached status {target!r}; last={body.get('status')}")


async def test_happy_path_raw_data() -> None:
    """POST /print → 202 + job_id → poll → completed."""
    app = create_app()
    _inner = app._app
    for _dep in (require_read, require_print):
        _inner.dependency_overrides[_dep] = lambda _c=_FAKE_AUTH: _c
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/print",
            json={
                "content_type": "qr_two_lines",
                "data": {"title": "Smoke", "primary_id": "S-1", "qr_payload": "https://e.x"},
            },
        )
        assert r.status_code == 202, r.text
        job_id = r.json()["job_id"]

        body = await _poll_until(c, job_id, target="completed")
        assert body["status"] == "completed"
        assert body["error_code"] is None


# Failure-mode tests — override the "mock" factory before lifespan starts


def _factory_with(**mock_kwargs):
    """Build a 'mock' factory class that returns a configured MockPrinterBackend."""
    from app.printer_backends.mock_backend import MockPrinterBackend

    class _Patched:
        backend_id = "mock"

        @classmethod
        def from_settings(cls, _settings):
            return MockPrinterBackend(**mock_kwargs)

    return _Patched


@pytest.fixture
def offline_mock_backend(monkeypatch):
    BackendRegistry._factories.clear()
    BackendRegistry._discovered = True
    BackendRegistry.register("mock", _factory_with(offline=True))
    # Phase 1i H (Task 7b): BackendRouter._build_one patchen statt _build_backend_from_config.
    real_factory = _factory_with(offline=True)
    monkeypatch.setattr(
        BackendRouter, "_build_one", staticmethod(lambda _cfg: real_factory.from_settings(None))
    )
    yield


async def test_offline_synchronous_503(offline_mock_backend) -> None:
    """Printer offline now triggers synchronous 503 via preflight (no job created)."""
    app = create_app()
    _inner = app._app
    for _dep in (require_read, require_print):
        _inner.dependency_overrides[_dep] = lambda _c=_FAKE_AUTH: _c
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/print",
            json={
                "content_type": "qr_two_lines",
                "data": {"title": "X", "primary_id": "1", "qr_payload": "u"},
            },
        )
        assert r.status_code == 503
        body = r.json()
        assert body["error_code"] == "printer_offline"
