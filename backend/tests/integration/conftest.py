"""Pytest configuration for integration tests.

Integration tests run against the full FastAPI application (including the
lifespan) but without real hardware. We configure the app to use the in-memory
mock backend so that lifespan startup succeeds without a printer on the network.
"""

from __future__ import annotations

import app.db.engine as _engine_module
import app.db.lifespan as _lifespan_module
import app.main as _main_module
import app.models  # noqa: F401 — registers all models with SQLModel.metadata
import pytest
import pytest_asyncio
from app.config import get_settings
from app.db.engine import _apply_pragmas
from app.printer_backends import BackendRegistry
from app.printer_models.registry import ModelRegistry
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
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
    """
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
    # Alembic reads alembic.ini directly (sqlalchemy.url = ./data/hub.db),
    # bypassing the patched engine above.  Skip it — create_all() above is
    # the authoritative schema source for integration tests.
    monkeypatch.setattr(_lifespan_module, "run_migrations", _noop_migrations)
    # main.py does `from app.db.lifespan import run_migrations`, which creates a
    # local name binding in the main module that is NOT updated when the attribute
    # on _lifespan_module is patched.  The lifespan() function in main.py calls
    # its locally-bound `run_migrations` directly, so we must patch that name too.
    monkeypatch.setattr(_main_module, "run_migrations", _noop_migrations)
    yield
    await eng.dispose()


async def _noop_migrations() -> None:
    """Drop-in replacement for run_migrations() in integration test fixtures.

    The _temp_db_engine fixture already creates the full schema via
    SQLModel.metadata.create_all().  Alembic's run_migrations() would try to
    open alembic.ini's sqlalchemy.url (a ./data/hub.db relative path) which
    does not exist in CI, causing OperationalError.
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


@pytest.fixture(autouse=True)
def _mock_backend_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure integration tests use the mock backend and a known model.

    The FastAPI lifespan wires up printer infrastructure — without real hardware
    or this fixture, lifespan startup would fail and TestClient would raise before
    any test body executes.
    """
    monkeypatch.setenv("PRINTER_HUB_PRINTER_BACKEND", "mock")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_MODEL", "PT-P750W")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_DISCOVER_VIA_SNMP", "false")
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
