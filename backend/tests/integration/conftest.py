"""Pytest configuration for integration tests.

Integration tests run against the full FastAPI application (including the
lifespan) but without real hardware. We configure the app to use the in-memory
mock backend so that lifespan startup succeeds without a printer on the network.
"""

from __future__ import annotations

import app.db.engine as _engine_module
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
    yield
    await eng.dispose()


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
