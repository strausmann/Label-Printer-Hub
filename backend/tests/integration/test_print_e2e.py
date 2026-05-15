"""End-to-end integration tests for POST /print → GET /jobs/{id}."""

from __future__ import annotations

import asyncio

import pytest
from app.config import get_settings
from app.main import create_app
from app.printer_backends import BackendRegistry
from app.printer_models.registry import ModelRegistry
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PRINTER_HUB_PRINTER_BACKEND", "mock")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_MODEL", "PT-P750W")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_DISCOVER_VIA_SNMP", "false")
    monkeypatch.setenv("PRINTER_HUB_PT750W_HOST", "")
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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/print",
            json={
                "template_id": "qr-only-24mm",
                "data": {"title": "Smoke", "primary_id": "S-1", "qr_payload": "https://e.x"},
            },
        )
        assert r.status_code == 202, r.text
        job_id = r.json()["job_id"]

        body = await _poll_until(c, job_id, target="completed")
        assert body["status"] == "completed"
        assert body["error_code"] is None


async def test_template_not_found_synchronous_404() -> None:
    """Unknown template_id → synchronous 404, no job record."""
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/print",
            json={
                "template_id": "does-not-exist",
                "data": {"title": "X", "primary_id": "1", "qr_payload": "u"},
            },
        )
        assert r.status_code == 404
        assert r.json()["error_code"] == "template_not_found"


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
def mismatched_mock_backend():
    BackendRegistry._factories.clear()
    BackendRegistry._discovered = True
    BackendRegistry.register("mock", _factory_with(loaded_tape_mm=12))
    yield


async def test_tape_mismatch_ends_failed(mismatched_mock_backend) -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/print",
            json={
                "template_id": "qr-only-24mm",
                "data": {"title": "X", "primary_id": "1", "qr_payload": "u"},
            },
        )
        assert r.status_code == 202
        body = await _poll_until(c, r.json()["job_id"], target="failed")
        assert body["error_code"] == "tape_mismatch"
        assert body["error_detail"] == {"expected_mm": 24, "loaded_mm": 12}


@pytest.fixture
def offline_mock_backend():
    BackendRegistry._factories.clear()
    BackendRegistry._discovered = True
    BackendRegistry.register("mock", _factory_with(offline=True))
    yield


async def test_offline_ends_failed_after_retries(offline_mock_backend) -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/print",
            json={
                "template_id": "qr-only-24mm",
                "data": {"title": "X", "primary_id": "1", "qr_payload": "u"},
            },
        )
        assert r.status_code == 202
        body = await _poll_until(c, r.json()["job_id"], target="failed", timeout_s=10.0)
        assert body["error_code"] == "printer_offline"
