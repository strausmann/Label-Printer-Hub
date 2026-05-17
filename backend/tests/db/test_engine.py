"""Tests that SQLite pragmas are applied via the engine connect hook.

WAL journal_mode requires a file-based database (not supported on :memory:),
so these tests spin up a temporary file-based engine with the same hook.
FK and busy_timeout work on both :memory: and file-based engines.

F2 tests: database URL must come from Settings (PRINTER_HUB_ prefix), and the
default URL must include the +aiosqlite async driver so create_async_engine
never raises "The asyncio extension requires an async driver".
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.db.engine import _apply_pragmas
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def file_engine(tmp_path: Path):
    db_path = tmp_path / "test.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    eng = create_async_engine(url, connect_args={"check_same_thread": False})
    event.listen(eng.sync_engine, "connect", _apply_pragmas)
    yield eng
    await eng.dispose()


@pytest.fixture
async def file_session(file_engine):
    factory = async_sessionmaker(file_engine, expire_on_commit=False)
    async with factory() as s:
        yield s


@pytest.mark.asyncio
async def test_pragmas_applied(file_session):
    journal = (await file_session.execute(text("PRAGMA journal_mode"))).scalar()
    assert journal == "wal"
    fk = (await file_session.execute(text("PRAGMA foreign_keys"))).scalar()
    assert fk == 1
    busy = (await file_session.execute(text("PRAGMA busy_timeout"))).scalar()
    assert busy == 5000


# ---------------------------------------------------------------------------
# F2 — DATABASE_URL must come from Settings (PRINTER_HUB_ prefix) and default
#      must include the +aiosqlite async driver. (Finding F2 from smoke-test.)
# ---------------------------------------------------------------------------


def test_settings_default_database_url_has_aiosqlite_driver() -> None:
    """Settings.database_url default must include +aiosqlite.

    Finding F2: the old default was 'sqlite:////data/printer-hub.db' (no
    async driver), which would cause "The asyncio extension requires an async
    driver" at runtime when engine.py creates the async engine from Settings.
    """
    from app.config import Settings

    s = Settings(_env_file=None)
    assert "+aiosqlite" in s.database_url, (
        f"Settings.database_url default {s.database_url!r} must contain '+aiosqlite'. "
        "create_async_engine requires an async driver specifier."
    )


def test_settings_respects_printer_hub_database_url_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """PRINTER_HUB_DATABASE_URL env var must control database_url.

    Finding F2: engine.py read the old LABEL_HUB_DATABASE_URL env var.
    After the fix, Settings (PRINTER_HUB_ prefix) is the single source of
    truth and must honour the correctly-prefixed env var.
    """
    from app.config import Settings

    custom_url = f"sqlite+aiosqlite:///{tmp_path}/custom.db"
    monkeypatch.setenv("PRINTER_HUB_DATABASE_URL", custom_url)
    s = Settings(_env_file=None)
    assert s.database_url == custom_url


def test_label_hub_database_url_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """LABEL_HUB_DATABASE_URL (old rename-relict) must NOT affect Settings.

    Finding F2: after the rename LABEL_HUB_* → PRINTER_HUB_*, setting the
    old var must have no effect. Settings uses env_prefix='PRINTER_HUB_' and
    extra='ignore', so unknown prefixes are silently dropped.
    """
    from app.config import Settings

    monkeypatch.setenv("LABEL_HUB_DATABASE_URL", "sqlite+aiosqlite:////tmp/old.db")
    # Do NOT set PRINTER_HUB_DATABASE_URL so we get the default.
    monkeypatch.delenv("PRINTER_HUB_DATABASE_URL", raising=False)
    s = Settings(_env_file=None)
    # Must fall back to the default, not the old env var.
    assert "old.db" not in s.database_url, (
        "LABEL_HUB_DATABASE_URL must be ignored; only PRINTER_HUB_DATABASE_URL is read."
    )
