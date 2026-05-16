"""Async SQLAlchemy engine with SQLite pragma enforcement."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.getenv(
    "LABEL_HUB_DATABASE_URL",
    "sqlite+aiosqlite:///./data/hub.db",
)


def _apply_pragmas(dbapi_connection: Any, _connection_record: object) -> None:
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA journal_mode = WAL")
    cur.execute("PRAGMA synchronous = NORMAL")
    cur.execute("PRAGMA foreign_keys = ON")
    cur.execute("PRAGMA busy_timeout = 5000")
    cur.close()


def _ensure_data_dir(url: str) -> None:
    if url.startswith("sqlite+aiosqlite:///"):
        path = url.removeprefix("sqlite+aiosqlite:///")
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)


_ensure_data_dir(DATABASE_URL)

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)

# Register the pragma hook on the underlying SQLAlchemy engine.
event.listen(engine.sync_engine, "connect", _apply_pragmas)

async_session = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
