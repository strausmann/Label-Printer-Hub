"""Integrations and the webhook key follow the runtime settings store (D4/D5)."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from app.api.dependencies.webhook_auth import require_webhook_key
from app.api.error_handlers import register_error_handlers
from app.api.routes.lookup import router as lookup_router
from app.auth.scope_deps import require_read
from app.config import get_settings
from app.integrations.grocy.plugin import GrocyPlugin
from app.integrations.registry import IntegrationRegistry
from app.integrations.spoolman.plugin import SpoolmanPlugin
from app.security.secret_box import SecretBox
from app.services.cleanup_task import CleanupTask
from app.settings_store import SettingsStore
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

KEY = b"test-secret-key-0123456789abcdef"
HOST_A = "https://spoolman-a.example.invalid"
HOST_B = "https://spoolman-b.example.invalid"
FAKE_KEY = "fake-webhook-key-0123456789abcdef"
SPOOL = {
    "id": 1,
    "filament": {"vendor": {"name": "V"}, "name": "PLA", "color_hex": "000000"},
    "remaining_weight": 100,
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch):
    for name in (
        "PRINTER_HUB_SPOOLMAN_URL",
        "PRINTER_HUB_GROCY_URL",
        "PRINTER_HUB_GROCY_API_KEY",
        "PRINTER_HUB_WEBHOOK_API_KEY",
        "PRINTER_HUB_JOB_RETENTION_DAYS",
    ):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def store() -> SettingsStore:
    return SettingsStore(SecretBox(KEY))


async def _set(factory, store: SettingsStore, values: dict) -> None:
    async with factory() as session:
        await store.set_many(session, values)


def test_discovery_still_constructs_without_args() -> None:
    plugin = SpoolmanPlugin()
    assert plugin.is_configured() is False  # not bound yet


async def test_bound_but_empty_store_is_not_configured(store) -> None:
    plugin = GrocyPlugin()
    plugin.bind(store)
    assert plugin.is_configured() is False


async def test_configured_needs_url_and_key(store, async_session_factory) -> None:
    plugin = GrocyPlugin()
    plugin.bind(store)
    await _set(
        async_session_factory,
        store,
        {"integrations.grocy.url": HOST_A, "integrations.grocy.api_key": "fake-api-key"},
    )
    assert plugin.is_configured() is True


@respx.mock
async def test_url_change_applies_without_restart(store, async_session_factory) -> None:
    route_a = respx.get(f"{HOST_A}/api/v1/spool/1").mock(
        return_value=httpx.Response(200, json=SPOOL)
    )
    route_b = respx.get(f"{HOST_B}/api/v1/spool/1").mock(
        return_value=httpx.Response(200, json=SPOOL)
    )
    plugin = SpoolmanPlugin()
    plugin.bind(store)

    await _set(async_session_factory, store, {"integrations.spoolman.url": HOST_A})
    await plugin.lookup("1")
    assert route_a.call_count == 1 and route_b.call_count == 0

    await _set(async_session_factory, store, {"integrations.spoolman.url": HOST_B})
    await plugin.lookup("1")
    assert route_a.call_count == 1 and route_b.call_count == 1


async def test_timeout_change_recreates_client(store, async_session_factory) -> None:
    plugin = SpoolmanPlugin()
    plugin.bind(store)
    old = plugin._client
    await _set(async_session_factory, store, {"integrations.spoolman.timeout": 17.0})
    assert plugin._client is not old
    assert plugin._client.timeout.read == 17.0
    await plugin.reconfigure()
    assert plugin._client.timeout.read == 17.0
    await plugin.aclose()


def test_unconfigured_lookup_returns_503_problem(store) -> None:
    IntegrationRegistry.clear()
    plugin = GrocyPlugin()
    plugin.bind(store)
    IntegrationRegistry.register(plugin)
    try:
        app = FastAPI()
        app.include_router(lookup_router)
        app.dependency_overrides[require_read] = lambda: None
        register_error_handlers(app)
        r = TestClient(app, raise_server_exceptions=False).get("/api/lookup/grocy/1")
    finally:
        IntegrationRegistry.clear()
    assert r.status_code == 503
    assert r.json()["type"] == "integration_not_configured"


async def test_retention_change_applies_on_next_cleanup_run(store, async_session_factory) -> None:
    jobs = AsyncMock()
    jobs.evict_terminal_older_than.return_value = 0
    task = CleanupTask(store=jobs, retention_days=lambda: int(store.get("jobs.retention_days")))

    await task._run_once()
    await _set(async_session_factory, store, {"jobs.retention_days": 7})
    await task._run_once()

    got = [c.args[0] for c in jobs.evict_terminal_older_than.await_args_list]
    assert got == [timedelta(days=30), timedelta(days=7)]


def _webhook_app(store: SettingsStore) -> TestClient:
    app = FastAPI()
    app.state.settings_store = store

    @app.get("/guarded", dependencies=[Depends(require_webhook_key)])
    async def guarded() -> dict[str, str]:
        return {"ok": "true"}

    return TestClient(app, raise_server_exceptions=False)


async def test_webhook_key_from_store(store, async_session_factory) -> None:
    client = _webhook_app(store)
    assert client.get("/guarded", headers={"X-API-Key": FAKE_KEY}).status_code == 503

    await _set(async_session_factory, store, {"access.webhook_api_key": FAKE_KEY})
    assert client.get("/guarded", headers={"X-API-Key": FAKE_KEY}).status_code == 200
    assert client.get("/guarded", headers={"X-API-Key": "x" * 32}).status_code == 401


@respx.mock
async def test_in_flight_lookup_survives_client_swap(store, async_session_factory) -> None:
    import asyncio

    gate = asyncio.Event()
    started = asyncio.Event()

    async def slow(request: httpx.Request) -> httpx.Response:
        started.set()
        await gate.wait()
        return httpx.Response(200, json=SPOOL)

    respx.get(f"{HOST_A}/api/v1/spool/1").mock(side_effect=slow)
    plugin = SpoolmanPlugin()
    plugin.bind(store)
    await _set(async_session_factory, store, {"integrations.spoolman.url": HOST_A})

    old = plugin._client
    task = asyncio.create_task(plugin.lookup("1"))
    await started.wait()

    # URL and timeout change while the request is in flight.
    await _set(
        async_session_factory,
        store,
        {"integrations.spoolman.url": HOST_B, "integrations.spoolman.timeout": 17.0},
    )
    assert plugin._client is not old
    await asyncio.sleep(0)
    assert old.is_closed is False  # still serving the in-flight request

    gate.set()
    data = await task
    assert data.qr_payload == f"{HOST_A}/spool/show/1"  # snapshot the lookup started with
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert old.is_closed is True  # retired client closed once the last user is done
    await plugin.aclose()


async def test_store_rejects_short_webhook_key_without_echo(store, async_session_factory) -> None:
    from app.settings_store import InvalidSettingValueError

    short = "short-key-" + "q" * 10
    for value in (short, "  " + "a" * 31 + "  "):
        with pytest.raises(InvalidSettingValueError) as exc:
            await _set(async_session_factory, store, {"access.webhook_api_key": value})
        assert value not in str(exc.value)
    await _set(async_session_factory, store, {"access.webhook_api_key": FAKE_KEY})  # >= 32 ok


def test_short_expected_webhook_key_is_not_configured() -> None:
    class _Short:
        def get(self, _key: str) -> str:
            return "x" * 20

    app = FastAPI()
    app.state.settings_store = _Short()

    @app.get("/guarded", dependencies=[Depends(require_webhook_key)])
    async def guarded() -> dict[str, str]:
        return {"ok": "true"}

    r = TestClient(app, raise_server_exceptions=False).get(
        "/guarded", headers={"X-API-Key": "x" * 20}
    )
    assert r.status_code == 503
