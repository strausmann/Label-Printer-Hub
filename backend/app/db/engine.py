"""Async SQLAlchemy engine with SQLite pragma enforcement."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

# Single source of truth: Settings.database_url (env var PRINTER_HUB_DATABASE_URL).
# The previous code read the old LABEL_HUB_DATABASE_URL env var which was a
# rename relict — see Finding F2 in docs/decisions/.
DATABASE_URL = get_settings().database_url


def _apply_pragmas(dbapi_connection: Any, _connection_record: object) -> None:
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA journal_mode = WAL")
    cur.execute("PRAGMA synchronous = NORMAL")
    cur.execute("PRAGMA foreign_keys = ON")
    cur.execute("PRAGMA busy_timeout = 5000")
    cur.close()


def _ensure_data_dir(url: str) -> None:
    """Best-effort creation of the SQLite database parent directory.

    Silently skips when the directory cannot be created (e.g. the absolute
    production path ``/data`` does not exist in local dev, or the process
    lacks permission).  A missing directory will produce a clearer error at
    connection time than a PermissionError at import time.
    """
    if url.startswith("sqlite+aiosqlite:///"):
        path = url.removeprefix("sqlite+aiosqlite:///")
        if path and path != ":memory:":
            with contextlib.suppress(PermissionError, OSError):
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
