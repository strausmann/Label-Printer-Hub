"""Fixtures für Unit-Tests der Repository-Schicht.

Stellt eine per-Test in-memory SQLite DB mit db_session-Fixture bereit.
FK-Enforcement bewusst NICHT aktiviert — Phase-2-Tests nutzen uuid4()
als printer_id ohne echte Printer-Rows anzulegen (Unit-Scope).
"""

from __future__ import annotations

import app.models  # noqa: F401 — registriert alle Models mit SQLModel.metadata
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel


@pytest_asyncio.fixture
async def _engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db_session(_engine):
    factory = async_sessionmaker(_engine, expire_on_commit=False)
    async with factory() as s:
        yield s
