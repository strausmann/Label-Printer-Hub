"""Fixtures for DB-level integration tests (tests/integration/db/).

Provides ``async_session_empty`` — an AsyncSession against a fresh SQLite DB
migrated to alembic head.  This is intentionally independent of the
integration-level autouse fixtures (which monkeypatch the engine in main.py)
so that DB-helper tests can run in isolation.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

_ALEMBIC_INI = Path(__file__).parents[3] / "alembic.ini"


@pytest_asyncio.fixture
async def async_session_empty(tmp_path):
    """AsyncSession backed by a fresh per-test SQLite DB at alembic head.

    Phase 7b B6 learning: set ``configure_logger = False`` so alembic's
    fileConfig does not call ``disable_existing_loggers`` and break caplog
    assertions in subsequently-run tests.

    alembic's env.py calls ``asyncio.run()`` internally; to avoid the
    "cannot be called from a running event loop" error, we run the upgrade
    in a thread via asyncio.to_thread (same technique as
    ``app.db.lifespan.run_migrations``).
    """
    db = tmp_path / "phase7b_c2.db"

    def _upgrade() -> None:
        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db}")
        cfg.attributes["configure_logger"] = False
        command.upgrade(cfg, "head")

    await asyncio.to_thread(_upgrade)

    engine = create_async_engine(f"sqlite+aiosqlite:///{db}", echo=False)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()
