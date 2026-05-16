"""Fixtures for async DB tests.

Uses an in-memory SQLite database so tests are fast and isolated.
The pragma hook from engine.py is applied so FK + busy_timeout pragmas
are enforced. Note: WAL journal_mode is not supported on in-memory SQLite
(returns "memory") — tests that assert WAL use a temp file-based engine.
"""
from __future__ import annotations

import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import app.models  # noqa: F401 — registers all models with SQLModel.metadata

from app.db.engine import _apply_pragmas


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(eng.sync_engine, "connect", _apply_pragmas)
    async with eng.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
