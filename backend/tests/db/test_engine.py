"""Tests that SQLite pragmas are applied via the engine connect hook.

WAL journal_mode requires a file-based database (not supported on :memory:),
so these tests spin up a temporary file-based engine with the same hook.
FK and busy_timeout work on both :memory: and file-based engines.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.engine import _apply_pragmas


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
