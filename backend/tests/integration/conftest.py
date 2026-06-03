"""Pytest configuration for integration tests.

Integration tests run against the full FastAPI application (including the
lifespan) but without real hardware. We configure the app to use the in-memory
mock backend so that lifespan startup succeeds without a printer on the network.
"""

from __future__ import annotations

from uuid import uuid4

import app.db.engine as _engine_module
import app.db.lifespan as _lifespan_module
import app.main as _main_module
import app.models  # noqa: F401 — registers all models with SQLModel.metadata
import pytest
import pytest_asyncio
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_admin, require_print, require_read
from app.config import get_settings
from app.db.engine import _apply_pragmas
from app.main import create_app
from app.printer_backends import BackendRegistry
from app.printer_models.registry import ModelRegistry
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel


@pytest_asyncio.fixture(autouse=True)
async def _temp_db_engine(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # type: ignore[misc]
    """Swap the module-level async engine for a per-test temp-file SQLite DB.

    Finding F2: after the fix, engine.py reads Settings.database_url at module
    load time, which defaults to the absolute container path
    sqlite+aiosqlite:////data/printer-hub.db. That path is not writable in
    the test environment, so every integration test that exercises the lifespan
    (which calls async_session()) would fail with OperationalError.

    We replace both the origin module's engine/async_session AND the names
    already imported into main.py — `from X import y` creates a local binding
    in main.py that is not updated when X.y is patched alone.

    run_migrations() is patched to a no-op because it invokes Alembic directly
    using the URL from alembic.ini (sqlite+aiosqlite:///./data/hub.db), which
    is a relative path that does not exist in CI.  The temp engine already has
    the full schema via SQLModel.metadata.create_all(), so migrations are
    redundant here.

    Phase 2 (Task 8): app.db.session imports async_session at module-load time
    via `from app.db.engine import async_session`. This creates a local binding
    in session.py that is NOT updated when _engine_module.async_session is
    patched. Routes using get_session() need the patched session factory, so we
    patch app.db.session.async_session here too.
    """
    import app.db.session as _session_module

    db_path = tmp_path / "integ_test.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    eng = create_async_engine(url, echo=False, connect_args={"check_same_thread": False})
    event.listen(eng.sync_engine, "connect", _apply_pragmas)
    async with eng.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    sess = async_sessionmaker(bind=eng, expire_on_commit=False)
    monkeypatch.setattr(_engine_module, "engine", eng)
    monkeypatch.setattr(_engine_module, "async_session", sess)
    monkeypatch.setattr(_main_module, "engine", eng)
    monkeypatch.setattr(_main_module, "async_session", sess)
    monkeypatch.setattr(_session_module, "async_session", sess)
    # Alembic reads alembic.ini directly (sqlalchemy.url = ./data/hub.db),
    # bypassing the patched engine above.  Skip it — create_all() above is
    # the authoritative schema source for integration tests.
    monkeypatch.setattr(_lifespan_module, "run_migrations", _noop_migrations)
    # main.py does `from app.db.lifespan import run_migrations`, which creates a
    # local name binding in the main module that is NOT updated when the attribute
    # on _lifespan_module is patched.  The lifespan() function in main.py calls
    # its locally-bound `run_migrations` directly, so we must patch that name too.
    monkeypatch.setattr(_main_module, "run_migrations", _noop_migrations)
    # verify_alembic_at_head checks the alembic_version table which does not
    # exist in the create_all() schema (only Alembic populates it).  Patch it
    # to a no-op for the same reason run_migrations is patched above.
    monkeypatch.setattr(_lifespan_module, "verify_alembic_at_head", _noop_verify)
    monkeypatch.setattr(_main_module, "verify_alembic_at_head", _noop_verify)
    yield
    await eng.dispose()


async def _noop_migrations() -> None:
    """Drop-in replacement for run_migrations() in integration test fixtures.

    The _temp_db_engine fixture already creates the full schema via
    SQLModel.metadata.create_all().  Alembic's run_migrations() would try to
    open alembic.ini's sqlalchemy.url (a ./data/hub.db relative path) which
    does not exist in CI, causing OperationalError.
    """


async def _noop_verify(*_args, **_kwargs) -> None:
    """Drop-in replacement for verify_alembic_at_head() in integration fixtures.

    The _temp_db_engine fixture builds the schema via SQLModel.metadata.create_all()
    which does not populate the alembic_version table.  Patching out the verify
    step avoids a spurious RuntimeError ("drift detected") — the same rationale
    as patching run_migrations to a no-op.
    """


async def _noop_seed_templates(*_args, **_kwargs) -> int:  # type: ignore[no-untyped-def]
    """Drop-in replacement for seed_templates() in integration test fixtures.

    The D1 defensive check raises RuntimeError when TemplateLoader._cache is
    empty.  Integration tests exercise the lifespan for other purposes (printer
    startup, SSE, healthz) and do not need templates seeded.  Patching this
    no-op avoids a spurious failure until D2 fixes the load_dir ordering in
    main.py lifespan.
    """
    return 0


@pytest_asyncio.fixture
async def api_client_with_broken_db(tmp_path):
    """AsyncClient whose DB has never been alembic-upgraded.

    The alembic_version table is absent, so _check_alembic() returns fail
    which makes build_readiness_response() return status=not-ready.
    /readiness should therefore respond 503.

    /healthz MUST still respond 200 — it never touches the DB.
    """

    import app.db.engine as _eng
    import app.db.session as _sess
    from app.main import create_app
    from httpx import ASGITransport, AsyncClient

    # Point at an empty SQLite file — create_all() gives it the schema
    # tables but NOT the alembic_version row, so verify_alembic_at_head fails.
    db_path = tmp_path / "broken.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    eng = create_async_engine(url, echo=False, connect_args={"check_same_thread": False})
    event.listen(eng.sync_engine, "connect", _apply_pragmas)
    async with eng.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    sess = async_sessionmaker(bind=eng, expire_on_commit=False)

    # Patch the session but do NOT patch verify_alembic_at_head — we want
    # that check to fail so the readiness probe returns not-ready.
    _sess.async_session = sess

    # Patch engine references so create_app() finds the right session.
    from unittest.mock import patch

    with (
        patch.object(_eng, "engine", eng),
        patch.object(_eng, "async_session", sess),
        patch.object(_main_module, "engine", eng),
        patch.object(_main_module, "async_session", sess),
        # run_migrations uses alembic.ini URL — patch to no-op so lifespan
        # doesn't crash before the readiness endpoint is called.
        patch.object(_lifespan_module, "run_migrations", _noop_migrations),
        patch.object(_main_module, "run_migrations", _noop_migrations),
        # seed_templates needs at least one cached template; patch to no-op
        # since we only test /readiness and /healthz here.
        patch.object(_lifespan_module, "seed_templates", _noop_seed_templates),
        patch.object(_main_module, "seed_templates", _noop_seed_templates),
    ):
        from app.integrations import (  # type: ignore[attr-defined]
            IntegrationRegistry,
            _discover_plugins,
        )

        if not IntegrationRegistry.names():
            _discover_plugins()

        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            yield c

    await eng.dispose()


# Minimale printers.yaml-Konfiguration für Integration-Tests.
# Wird als _PrinterConfigLoaderResult in _mock_backend_env gepatcht.
_INTEGRATION_TEST_PRINTER_CONFIG_YAML = """\
schema_version: 1
printers:
  - slug: mock-pt-p750w
    name: Mock PT-P750W
    backend: ptouch
    model: PT-P750W
    host: ''
    port: 9100
    snmp:
      discover: false
      community: public
    cut_defaults:
      half_cut: false
      cut_at_end: true
"""


@pytest.fixture(autouse=True)
def _mock_backend_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Ensure integration tests use the mock backend and a known model.

    Phase 1i H (Task 7b): _build_backend_from_config wurde entfernt.
    BackendRouter._build_one() wird jetzt gepatcht um MockPrinterBackend
    zurückzugeben — leerem Host würde PTouchBackend ValueError werfen.

    Eine minimale printers.yaml wird in tmp_path geschrieben und
    PRINTER_HUB_PRINTERS_CONFIG darauf gesetzt.
    """
    from app.printer_backends.mock_backend import MockPrinterBackend
    from app.services.backend_router import BackendRouter

    # printers.yaml in tmp_path schreiben
    _mock_printers_yaml = tmp_path / "printers.yaml"
    _mock_printers_yaml.write_text(_INTEGRATION_TEST_PRINTER_CONFIG_YAML)
    monkeypatch.setenv("PRINTER_HUB_PRINTERS_CONFIG", str(_mock_printers_yaml))

    # BackendRouter._build_one auf Mock-Backend patchen (leerem Host
    # würde PTouchBackend ValueError werfen).
    monkeypatch.setattr(
        BackendRouter, "_build_one", staticmethod(lambda _cfg: MockPrinterBackend())
    )

    get_settings.cache_clear()
    # Reset registry state so each test gets a clean discovery cycle.
    BackendRegistry._factories.clear()
    BackendRegistry._discovered = False
    ModelRegistry._models.clear()
    ModelRegistry._discovered = False
    yield
    get_settings.cache_clear()
    BackendRegistry._factories.clear()
    BackendRegistry._discovered = False
    ModelRegistry._models.clear()
    ModelRegistry._discovered = False


@pytest_asyncio.fixture
async def app_with_fake_auth():
    """FastAPI-App mit gefakter Auth (dependency_overrides für require_*).

    Pattern verifiziert gegen tests/integration/test_print_e2e.py:50-70.
    Gibt den _LifespanManager zurück — den nutzt der AsyncClient mit
    ASGITransport. dependency_overrides werden auf der inneren FastAPI-Instanz
    gesetzt (app._app), nicht auf dem Wrapper.
    """
    app = create_app()
    inner = app._app  # FastAPI hinter _LifespanManager (main.py:517+612)
    fake = AuthContext(
        source="api-key",
        scope="admin",
        api_key_id=uuid4(),
        ip="127.0.0.1",
    )
    for dep in (require_read, require_print, require_admin):
        inner.dependency_overrides[dep] = lambda _c=fake: _c
    return app  # _LifespanManager — wichtig für ASGITransport!


@pytest_asyncio.fixture
async def client(app_with_fake_auth):
    """ASGI-Test-Client gegen die App mit gefakter Auth.

    `_temp_db_engine` (autouse) hat bereits eine Per-Test-SQLite-DB
    vorbereitet und in app.db.engine + app.main gepatcht. Diese Fixture
    setzt nur Auth-Overrides und einen httpx-Client darüber.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app_with_fake_auth),
        base_url="http://t",
    ) as c:
        yield c


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """DB-Session gegen die per-test temp-Engine aus `_temp_db_engine`.

    Liest async_session dynamisch aus dem Engine-Modul, damit der
    monkeypatch.setattr aus _temp_db_engine wirksam ist.
    """
    import app.db.engine as eng_mod

    async with eng_mod.async_session() as s:
        yield s


@pytest.fixture
def print_auth_headers() -> dict:
    """Leere Dict — Auth ist via dependency_overrides gefakt."""
    return {}


@pytest.fixture
def read_auth_headers() -> dict:
    """Leere Dict — siehe print_auth_headers."""
    return {}
