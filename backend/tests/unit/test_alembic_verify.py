"""Phase 7b Cluster 1d — verify_alembic_at_head fails fast on revision drift."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.config import Settings
from app.db.lifespan import verify_alembic_at_head

pytestmark = pytest.mark.asyncio


_ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def _alembic_cfg(db_url_async: str) -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", db_url_async)
    cfg.attributes["configure_logger"] = False  # Phase 7b B6 learning
    return cfg


def _settings(db_url_async: str) -> Settings:
    return Settings(
        database_url=db_url_async,
        printer_backend="mock",
        _env_file=None,  # type: ignore[call-arg]
    )


async def test_verify_passes_when_db_at_head(tmp_path: Path) -> None:
    db = tmp_path / "atomic_e1_head.db"
    async_url = f"sqlite+aiosqlite:///{db}"
    # command.upgrade calls asyncio.run() via env.py — must run in a thread
    # to avoid "asyncio.run() cannot be called from a running event loop".
    await asyncio.to_thread(command.upgrade, _alembic_cfg(async_url), "head")
    settings = _settings(async_url)
    # Should not raise
    await verify_alembic_at_head(settings)


async def test_verify_raises_on_stale_db(tmp_path: Path) -> None:
    db = tmp_path / "atomic_e1_stale.db"
    async_url = f"sqlite+aiosqlite:///{db}"
    cfg = _alembic_cfg(async_url)
    # Both alembic commands call asyncio.run() in env.py — run in threads.
    await asyncio.to_thread(command.upgrade, cfg, "head")
    await asyncio.to_thread(command.downgrade, cfg, "-1")

    settings = _settings(async_url)
    with pytest.raises(RuntimeError, match="drift"):
        await verify_alembic_at_head(settings)


async def test_verify_raises_on_empty_db(tmp_path: Path) -> None:
    """Brand-new DB with no alembic_version table → not at head → must raise."""
    db = tmp_path / "atomic_e1_empty.db"
    async_url = f"sqlite+aiosqlite:///{db}"
    # NO alembic upgrade — DB is completely empty
    settings = _settings(async_url)
    with pytest.raises(RuntimeError, match="drift"):
        await verify_alembic_at_head(settings)
