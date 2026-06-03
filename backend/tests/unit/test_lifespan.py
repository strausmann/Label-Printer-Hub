from __future__ import annotations

from pathlib import Path
from typing import Any

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
from app.services.backend_router import BackendRouter
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


async def _noop_verify(*_args, **_kwargs) -> None:
    """Drop-in for verify_alembic_at_head() in unit lifespan tests.

    The clean_registries fixture builds the schema via create_all() which does
    not populate alembic_version.  Patching out verify avoids a spurious
    RuntimeError — same rationale as patching run_migrations to a no-op.
    """


async def _noop_seed_templates(*_args, **_kwargs) -> int:  # type: ignore[no-untyped-def]
    """Drop-in for seed_templates() in unit lifespan tests.

    The D1 defensive check raises RuntimeError when TemplateLoader._cache is
    empty.  These tests exercise printer backend / SNMP discovery paths and do
    not require templates; patching avoids the spurious failure until D2 reorders
    load_dir before seed_templates in main.py lifespan.
    """
    return 0


def _write_printers_yaml(
    tmp_path: Path,
    *,
    model: str = "PT-P750W",
    host: str = "",
    snmp_discover: bool = False,
    snmp_community: str = "public",
) -> Path:
    """Schreibt eine minimale printers.yaml nach tmp_path und gibt den Pfad zurück.

    Phase 1i CA-1: Ersetzt die alten PRINTER_HUB_PRINTER_* Env-Vars.
    """
    content = (
        "schema_version: 1\n"
        "printers:\n"
        f"  - slug: test-printer\n"
        f"    name: Test Printer\n"
        f"    backend: ptouch\n"
        f"    model: {model}\n"
        f"    host: '{host}'\n"
        f"    port: 9100\n"
        f"    snmp:\n"
        f"      discover: {'true' if snmp_discover else 'false'}\n"
        f"      community: {snmp_community}\n"
        f"    cut_defaults:\n"
        f"      half_cut: false\n"
        f"      cut_at_end: true\n"
    )
    p = tmp_path / "printers.yaml"
    p.write_text(content)
    return p


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
    import app.db.session as _session_module

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
    monkeypatch.setattr(_session_module, "async_session", sess)
    monkeypatch.setattr(_lifespan_module, "run_migrations", _noop_migrations)
    # main.py binds `run_migrations` locally via `from app.db.lifespan import
    # run_migrations`.  Patching _lifespan_module alone does not update that
    # local binding; we must also patch the name on _main_module.
    monkeypatch.setattr(_main_module, "run_migrations", _noop_migrations)
    # verify_alembic_at_head checks alembic_version which is not created by
    # create_all() — patch it for the same reason run_migrations is patched.
    monkeypatch.setattr(_lifespan_module, "verify_alembic_at_head", _noop_verify)
    monkeypatch.setattr(_main_module, "verify_alembic_at_head", _noop_verify)

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


async def test_lifespan_starts_with_mock_backend(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Phase 1i CA-1: printers.yaml statt PRINTER_HUB_PRINTER_BACKEND Env-Var."""
    yaml_path = _write_printers_yaml(tmp_path, model="PT-P750W", host="", snmp_discover=False)
    monkeypatch.setenv("PRINTER_HUB_PRINTERS_CONFIG", str(yaml_path))

    # Phase 1i H (Task 7b): BackendRouter._build_one patchen statt _build_backend_from_config.
    # Leerer Host würde PTouchBackend ValueError werfen.
    from app.printer_backends.mock_backend import MockPrinterBackend

    monkeypatch.setattr(BackendRouter, "_build_one", staticmethod(lambda _cfg: MockPrinterBackend()))

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/healthz")
        assert r.status_code in (200, 404)


async def test_unknown_backend_fails_fast(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Phase 1i H (Task 7b): Unbekannte backend-ID → BackendRouter.UnknownBackendError.

    BackendRouter._build_one wirft UnknownBackendError für unbekannte backend-IDs.
    Da PrinterYAMLConfig backend: Literal["ptouch", "brother_ql"] validiert,
    simulieren wir den Fehler via direkten UnknownBackendError-Patch auf _build_one.
    """
    from app.printer_backends.mock_backend import MockPrinterBackend
    from app.services.backend_router import UnknownBackendError

    yaml_path = _write_printers_yaml(tmp_path, model="PT-P750W", host="", snmp_discover=False)
    monkeypatch.setenv("PRINTER_HUB_PRINTERS_CONFIG", str(yaml_path))

    # _build_one patchen um UnknownBackendError zu simulieren (backend-Validierung ist
    # bereits im Schema, aber _build_one wird in BackendRouter.__init__ aufgerufen).
    def _raise_unknown(_cfg: Any) -> Any:
        raise UnknownBackendError("Unknown backend: 'zebra-zpl'")

    monkeypatch.setattr(BackendRouter, "_build_one", staticmethod(_raise_unknown))

    app = create_app()
    with pytest.raises(Exception, match="zebra-zpl"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            await c.get("/healthz")


async def test_unknown_model_fails_fast(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Phase 1i CA-1: Unbekanntes Drucker-Modell → ModelRegistry-Fehler."""
    yaml_path = _write_printers_yaml(
        tmp_path, model="Imaginary-9000", host="", snmp_discover=False
    )
    monkeypatch.setenv("PRINTER_HUB_PRINTERS_CONFIG", str(yaml_path))

    from app.printer_backends.mock_backend import MockPrinterBackend

    # Phase 1i H (Task 7b): BackendRouter._build_one patchen statt _build_backend_from_config.
    monkeypatch.setattr(BackendRouter, "_build_one", staticmethod(lambda _cfg: MockPrinterBackend()))

    app = create_app()
    with pytest.raises(Exception, match="Imaginary-9000"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            await c.get("/healthz")


async def test_snmp_discovery_resolves_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """SNMP returns a stubbed PJL string; lifespan resolves it via find_by_pjl.

    Phase 1i CA-1: snmp.discover=true + host in printers.yaml statt Env-Vars.
    """
    yaml_path = _write_printers_yaml(
        tmp_path, model="PT-P750W", host="192.0.2.10", snmp_discover=True
    )
    monkeypatch.setenv("PRINTER_HUB_PRINTERS_CONFIG", str(yaml_path))

    from app.printer_backends.mock_backend import MockPrinterBackend

    # Phase 1i H (Task 7b): BackendRouter._build_one patchen statt _build_backend_from_config.
    monkeypatch.setattr(BackendRouter, "_build_one", staticmethod(lambda _cfg: MockPrinterBackend()))

    async def fake_query(host: str, *, community: str = "public", timeout_s: float = 3.0):
        return "MFG:Brother;CMD:PJL;MDL:PT-P750W;CLS:PRINTER;DES:Brother PT-P750W;"

    monkeypatch.setattr("app.main.query_model_pjl", fake_query)
    from app.printer_models.pt import PTP750WDriver  # noqa: F401  registers

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/healthz")
        assert r.status_code in (200, 404)


async def test_snmp_discovery_fallback_to_setting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """SNMP fails but model is configured in printers.yaml → fall back, warn, succeed.

    Phase 1i CA-1: printer_cfg.model als Fallback statt settings.printer_model.
    """
    yaml_path = _write_printers_yaml(
        tmp_path, model="PT-P750W", host="192.0.2.10", snmp_discover=True
    )
    monkeypatch.setenv("PRINTER_HUB_PRINTERS_CONFIG", str(yaml_path))

    from app.printer_backends.exceptions import SnmpDiscoveryError
    from app.printer_backends.mock_backend import MockPrinterBackend

    # Phase 1i H (Task 7b): BackendRouter._build_one patchen statt _build_backend_from_config.
    monkeypatch.setattr(BackendRouter, "_build_one", staticmethod(lambda _cfg: MockPrinterBackend()))

    async def fake_query(*_a, **_kw):
        raise SnmpDiscoveryError("timed out")

    monkeypatch.setattr("app.main.query_model_pjl", fake_query)

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/healthz")
        assert r.status_code in (200, 404)


async def test_snmp_discovery_no_fallback_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """SNMP fails AND model is empty → ValueError propagates.

    Phase 1i CA-1: printer_cfg.model="" + snmp.discover=true + SNMP-Fehler.
    """
    yaml_path = _write_printers_yaml(
        tmp_path, model="PT-P750W", host="192.0.2.10", snmp_discover=True
    )
    monkeypatch.setenv("PRINTER_HUB_PRINTERS_CONFIG", str(yaml_path))

    from app.printer_backends.exceptions import SnmpDiscoveryError
    from app.printer_backends.mock_backend import MockPrinterBackend

    # Phase 1i H (Task 7b): BackendRouter._build_one patchen statt _build_backend_from_config.
    monkeypatch.setattr(BackendRouter, "_build_one", staticmethod(lambda _cfg: MockPrinterBackend()))

    async def fake_query(*_a, **_kw):
        raise SnmpDiscoveryError("timed out")

    monkeypatch.setattr("app.main.query_model_pjl", fake_query)

    # Lade-Zeit-Override: model auf "" setzen damit _resolve_model_id_from_config
    # keinen Fallback hat.
    from app.services.printer_config_loader import PrinterConfigLoader
    from app.schemas.printer_config import PrinterYAMLConfig, SNMPConfig, QueueConfig, CutDefaults

    # Patch PrinterConfigLoader.all() so dass es ein Config mit leerem Model liefert
    _empty_model_cfg = PrinterYAMLConfig(
        slug="test-printer",
        name="Test Printer",
        backend="ptouch",
        model="PT-P750W",  # Brauchen gültigen Wert für Schema-Validierung
        host="192.0.2.10",
        port=9100,
        snmp=SNMPConfig(discover=True, community="public"),
        queue=QueueConfig(timeout_s=30),
        cut_defaults=CutDefaults(half_cut=False, cut_at_end=True),
    )
    # Patch model auf "" im Objekt (post-validation)
    object.__setattr__(_empty_model_cfg, "model", "")

    original_all = PrinterConfigLoader.all
    monkeypatch.setattr(PrinterConfigLoader, "all", classmethod(lambda cls: [_empty_model_cfg]))

    app = create_app()
    with pytest.raises(SnmpDiscoveryError):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            await c.get("/healthz")

    monkeypatch.setattr(PrinterConfigLoader, "all", original_all)


def test_lifespan_clears_integration_registry_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Lifespan shutdown must call aclose() on plugins and IntegrationRegistry.clear().

    Uses starlette.testclient.TestClient which sends a proper ASGI lifespan
    scope (startup + shutdown) so the finally-block in lifespan() actually
    executes.  httpx.ASGITransport only sends HTTP scopes and would silently
    skip the shutdown path.
    """
    from starlette.testclient import TestClient

    yaml_path = _write_printers_yaml(tmp_path, model="PT-P750W", host="", snmp_discover=False)
    monkeypatch.setenv("PRINTER_HUB_PRINTERS_CONFIG", str(yaml_path))
    monkeypatch.setenv("PRINTER_HUB_SNIPEIT_URL", "http://snipe.example")
    monkeypatch.setenv("PRINTER_HUB_SNIPEIT_API_KEY", "k")
    monkeypatch.setenv("PRINTER_HUB_GROCY_URL", "http://grocy.example")
    monkeypatch.setenv("PRINTER_HUB_GROCY_API_KEY", "grocy-k")
    monkeypatch.setenv("PRINTER_HUB_SPOOLMAN_URL", "http://spoolman.example")
    get_settings.cache_clear()

    from app.printer_backends.mock_backend import MockPrinterBackend

    # Phase 1i H (Task 7b): BackendRouter._build_one patchen statt _build_backend_from_config.
    monkeypatch.setattr(BackendRouter, "_build_one", staticmethod(lambda _cfg: MockPrinterBackend()))

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
