"""Phase 7b Cluster 1e — fixtures for readiness builder unit tests.

Provides:
  async_session_empty            — fresh migrated SQLite DB (no rows)
  async_session_with_one_template — same but with one seed Template row
  settings_at_head               — Settings pointing at the migrated DB
  runtime_printer_id             — stable UUID literal for printer_runtime check
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

import pytest_asyncio
from alembic import command
from alembic.config import Config
from app.config import Settings
from app.models.template import Template
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

_ALEMBIC_INI = Path(__file__).parents[3] / "alembic.ini"

# Stable test UUID — any UUID is fine for printer_runtime (no DB validation).
_TEST_PRINTER_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


def _make_db_url(tmp_path, name: str) -> str:
    db = tmp_path / name
    return f"sqlite+aiosqlite:///{db}"


def _run_migrations(db_url: str) -> None:
    """Run alembic upgrade head in a thread (avoids event-loop nesting)."""
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


@pytest_asyncio.fixture
async def async_session_empty(tmp_path):
    """AsyncSession backed by a fresh per-test SQLite DB at alembic head (no rows)."""
    url = _make_db_url(tmp_path, "readiness_empty.db")
    await asyncio.to_thread(_run_migrations, url)
    engine = create_async_engine(url, echo=False)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def async_session_with_one_template(tmp_path):
    """AsyncSession backed by a fresh DB with one seed Template row."""
    url = _make_db_url(tmp_path, "readiness_one_tpl.db")
    await asyncio.to_thread(_run_migrations, url)
    engine = create_async_engine(url, echo=False)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        tpl = Template(
            key="test-label",
            name="Test Label",
            printer_model="pt-series",
            tape_width_mm=12,
            definition={},
            source="seed",
        )
        session.add(tpl)
        await session.commit()
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def settings_at_head(tmp_path):
    """Settings whose database_url points at a migrated SQLite DB.

    verify_alembic_at_head() uses Settings.database_url to open the DB via a
    sync engine.  We need the DB to actually be at head so the check passes.
    """
    db_path = tmp_path / "readiness_settings.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    await asyncio.to_thread(_run_migrations, url)
    return Settings(_env_file=None, database_url=url)


@pytest_asyncio.fixture
def runtime_printer_id() -> UUID:
    """Stable UUID used as app.state.printer_id in printer_runtime check tests."""
    return _TEST_PRINTER_ID
