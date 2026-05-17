from __future__ import annotations

import app.db.engine as _engine_module
import app.db.lifespan as _lifespan_module
import app.main as _main_module
import app.models  # noqa: F401 — registers all models with SQLModel.metadata
import pytest
import pytest_asyncio
from app.config import get_settings
from app.db.engine import _apply_pragmas
from app.integrations.registry import IntegrationRegistry
from app.main import create_app
from app.printer_backends import BackendRegistry
from app.printer_models.registry import ModelRegistry
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel


async def _noop_migrations() -> None:
    """Drop-in for run_migrations() in unit lifespan tests.

    The clean_registries fixture already creates the full schema via
    SQLModel.metadata.create_all().  Alembic's run_migrations() would try to
    open alembic.ini's sqlalchemy.url (a ./data/hub.db relative path) which
    does not exist in CI, causing OperationalError.
    """


@pytest_asyncio.fixture(autouse=True)
async def clean_registries(monkeypatch: pytest.MonkeyPatch, tmp_path):  # type: ignore[misc]
    """Reset registries and swap the module-level engine for a temp DB.

    Finding F2: engine.py now reads Settings.database_url at module load,
    which defaults to the absolute container path /data/printer-hub.db.
    Swapping engine + async_session in BOTH the engine module AND main.py
    (which imports them by name at module level) keeps lifespan tests
    isolated and prevents OperationalError when the path doesn't exist.

    run_migrations() is also patched to a no-op: it calls Alembic directly
    using alembic.ini's sqlalchemy.url (sqlite+aiosqlite:///./data/hub.db),
    a relative path that does not exist in CI.  The schema is already present
    via create_all() above, so skipping migrations is correct here.
    """
    db_path = tmp_path / "lifespan_test.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    eng = create_async_engine(url, echo=False, connect_args={"check_same_thread": False})
    event.listen(eng.sync_engine, "connect", _apply_pragmas)
    async with eng.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    sess = async_sessionmaker(bind=eng, expire_on_commit=False)
    # Patch both the origin module and the names imported into main.py.
    # `from X import y` creates a local binding; patching X.y alone would not
    # affect the already-resolved main.y reference.
    monkeypatch.setattr(_engine_module, "engine", eng)
    monkeypatch.setattr(_engine_module, "async_session", sess)
    monkeypatch.setattr(_main_module, "engine", eng)
    monkeypatch.setattr(_main_module, "async_session", sess)
    monkeypatch.setattr(_lifespan_module, "run_migrations", _noop_migrations)
    # main.py binds `run_migrations` locally via `from app.db.lifespan import
    # run_migrations`.  Patching _lifespan_module alone does not update that
    # local binding; we must also patch the name on _main_module.
    monkeypatch.setattr(_main_module, "run_migrations", _noop_migrations)

    BackendRegistry._factories.clear()
    BackendRegistry._discovered = False
    ModelRegistry._models.clear()
    ModelRegistry._discovered = False
    get_settings.cache_clear()
    yield
    BackendRegistry._factories.clear()
    BackendRegistry._discovered = False
    ModelRegistry._models.clear()
    ModelRegistry._discovered = False
    get_settings.cache_clear()
    await eng.dispose()


async def test_lifespan_starts_with_mock_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRINTER_HUB_PRINTER_BACKEND", "mock")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_MODEL", "PT-P750W")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_DISCOVER_VIA_SNMP", "false")
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/healthz")
        assert r.status_code in (200, 404)


async def test_unknown_backend_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRINTER_HUB_PRINTER_BACKEND", "zebra-zpl")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_MODEL", "PT-P750W")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_DISCOVER_VIA_SNMP", "false")
    app = create_app()
    with pytest.raises(Exception, match="zebra-zpl"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            await c.get("/healthz")


async def test_unknown_model_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRINTER_HUB_PRINTER_BACKEND", "mock")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_MODEL", "Imaginary-9000")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_DISCOVER_VIA_SNMP", "false")
    app = create_app()
    with pytest.raises(Exception, match="Imaginary-9000"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            await c.get("/healthz")


async def test_snmp_discovery_resolves_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """SNMP returns a stubbed PJL string; lifespan resolves it via find_by_pjl."""
    monkeypatch.setenv("PRINTER_HUB_PRINTER_BACKEND", "mock")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_DISCOVER_VIA_SNMP", "true")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_MODEL", "")
    monkeypatch.setenv("PRINTER_HUB_PT750W_HOST", "192.0.2.10")

    async def fake_query(host: str, *, community: str = "public", timeout_s: float = 3.0):
        return "MFG:Brother;CMD:PJL;MDL:PT-P750W;CLS:PRINTER;DES:Brother PT-P750W;"

    monkeypatch.setattr("app.main.query_model_pjl", fake_query)
    from app.printer_models.pt import PTP750WDriver  # noqa: F401  registers

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/healthz")
        assert r.status_code in (200, 404)


async def test_snmp_discovery_fallback_to_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    """SNMP fails but printer_model is configured → fall back, warn, succeed."""
    monkeypatch.setenv("PRINTER_HUB_PRINTER_BACKEND", "mock")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_DISCOVER_VIA_SNMP", "true")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_MODEL", "PT-P750W")
    monkeypatch.setenv("PRINTER_HUB_PT750W_HOST", "192.0.2.10")

    from app.printer_backends.exceptions import SnmpDiscoveryError

    async def fake_query(*_a, **_kw):
        raise SnmpDiscoveryError("timed out")

    monkeypatch.setattr("app.main.query_model_pjl", fake_query)

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/healthz")
        assert r.status_code in (200, 404)


async def test_snmp_discovery_no_fallback_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """SNMP fails AND printer_model is empty → SnmpDiscoveryError propagates."""
    monkeypatch.setenv("PRINTER_HUB_PRINTER_BACKEND", "mock")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_DISCOVER_VIA_SNMP", "true")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_MODEL", "")
    monkeypatch.setenv("PRINTER_HUB_PT750W_HOST", "192.0.2.10")

    from app.printer_backends.exceptions import SnmpDiscoveryError

    async def fake_query(*_a, **_kw):
        raise SnmpDiscoveryError("timed out")

    monkeypatch.setattr("app.main.query_model_pjl", fake_query)

    app = create_app()
    with pytest.raises(SnmpDiscoveryError):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            await c.get("/healthz")


def test_lifespan_clears_integration_registry_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lifespan shutdown must call aclose() on plugins and IntegrationRegistry.clear().

    Uses starlette.testclient.TestClient which sends a proper ASGI lifespan
    scope (startup + shutdown) so the finally-block in lifespan() actually
    executes.  httpx.ASGITransport only sends HTTP scopes and would silently
    skip the shutdown path.
    """
    from starlette.testclient import TestClient

    monkeypatch.setenv("PRINTER_HUB_PRINTER_BACKEND", "mock")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_MODEL", "PT-P750W")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_DISCOVER_VIA_SNMP", "false")
    monkeypatch.setenv("PRINTER_HUB_SNIPEIT_URL", "http://snipe.example")
    monkeypatch.setenv("PRINTER_HUB_SNIPEIT_API_KEY", "k")
    monkeypatch.setenv("PRINTER_HUB_GROCY_URL", "http://grocy.example")
    monkeypatch.setenv("PRINTER_HUB_GROCY_API_KEY", "grocy-k")
    monkeypatch.setenv("PRINTER_HUB_SPOOLMAN_URL", "http://spoolman.example")
    get_settings.cache_clear()

    from app.integrations.grocy.plugin import GrocyPlugin
    from app.integrations.snipeit.plugin import SnipeITPlugin
    from app.integrations.spoolman.plugin import SpoolmanPlugin

    captured_snipeit: list[SnipeITPlugin] = []

    def capturing_discover() -> None:
        """Register all three built-in plugins, tracking SnipeIT for inspection."""
        snipeit = SnipeITPlugin()
        captured_snipeit.append(snipeit)
        IntegrationRegistry.register(snipeit)
        IntegrationRegistry.register(GrocyPlugin())
        IntegrationRegistry.register(SpoolmanPlugin())

    # Patch the discovery function that lifespan calls.
    monkeypatch.setattr("app.integrations._discover_plugins", capturing_discover)
    monkeypatch.setattr("app.main._integrations_init._discover_plugins", capturing_discover)

    # Clear the real plugins that were registered at import time so the lifespan
    # sees an empty registry and calls our capturing_discover on startup.
    IntegrationRegistry.clear()

    # --- First lifespan run ---
    app1 = create_app()
    with TestClient(app1) as c:
        c.get("/healthz")
    # Proper shutdown ran: aclose() called on plugin, registry cleared.
    assert len(captured_snipeit) >= 1
    plugin1 = captured_snipeit[0]
    assert plugin1._client.is_closed, "plugin's httpx client must be closed on shutdown"
    assert IntegrationRegistry.names() == [], "registry must be cleared on shutdown"

    # --- Second lifespan run must succeed (no 'already registered' ValueError) ---
    BackendRegistry._factories.clear()
    BackendRegistry._discovered = False
    ModelRegistry._models.clear()
    ModelRegistry._discovered = False
    get_settings.cache_clear()

    app2 = create_app()
    with TestClient(app2) as c:
        r = c.get("/healthz")
        assert r.status_code == 200
    assert len(captured_snipeit) >= 2
    plugin2 = captured_snipeit[1]
    assert plugin1 is not plugin2, "second lifespan must create a new plugin instance"
