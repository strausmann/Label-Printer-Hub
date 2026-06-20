"""Testet dass die SQLite Engine mit SERIALIZABLE Isolation Level konfiguriert ist.

Zwei Aspekte werden geprüft:

1. Das Modul app.db.engine übergibt isolation_level='SERIALIZABLE' explizit
   an create_async_engine(). Prüfung über dialect._on_connect_isolation_level,
   das nur dann gesetzt ist wenn der Parameter explizit übergeben wurde —
   SQLite-Default wäre None, während conn.get_isolation_level() grundsätzlich
   'SERIALIZABLE' liefert und damit kein geeignetes Unterscheidungsmerkmal ist.

2. isolation_level='SERIALIZABLE' und der _apply_pragmas-Hook (WAL + foreign_keys)
   koexistieren korrekt ohne einen zweiten Listener zu benötigen.

Task 1.1 von Issue #124: SQLite Engine SERIALIZABLE.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine

# ---------------------------------------------------------------------------
# Test 1 — Produktions-Engine: isolation_level='SERIALIZABLE' explizit gesetzt
# ---------------------------------------------------------------------------


def test_engine_has_explicit_serializable_isolation_level() -> None:
    """app.db.engine muss isolation_level='SERIALIZABLE' explizit setzen.

    dialect._on_connect_isolation_level ist None wenn kein Wert übergeben wurde,
    und 'SERIALIZABLE' wenn isolation_level='SERIALIZABLE' als Kwarg an
    create_async_engine() übergeben wurde. Das Attribut wird bei der
    Engine-Erstellung gesetzt — kein Connect nötig, daher kein Problem mit
    dem Produktions-DB-Pfad (/data/printer-hub.db).

    Hinweis: conn.get_isolation_level() liefert bei SQLite IMMER 'SERIALIZABLE'
    (SQLite-Default), daher ist dieses Attribut das einzig robuste Prüfkriterium
    für die explizite Konfiguration.
    """
    from app.db.engine import engine

    dialect = engine.sync_engine.dialect
    isolation_level_kwarg = dialect._on_connect_isolation_level

    assert isolation_level_kwarg == "SERIALIZABLE", (
        f"Erwartet dialect._on_connect_isolation_level='SERIALIZABLE', "
        f"erhalten: {isolation_level_kwarg!r}. "
        "Bitte isolation_level='SERIALIZABLE' als Argument an create_async_engine() "
        "in app/db/engine.py übergeben."
    )


# ---------------------------------------------------------------------------
# Test 2 — SERIALIZABLE + WAL-Pragma + foreign_keys koexistieren korrekt
# ---------------------------------------------------------------------------


@pytest.fixture
async def file_engine_serializable(tmp_path: Path):
    """Engine mit isolation_level='SERIALIZABLE' und _apply_pragmas-Listener.

    WAL journal_mode erfordert eine dateibasierte SQLite-Datenbank — daher
    tmp_path statt :memory:.
    """
    from app.db.engine import _apply_pragmas

    db_path = tmp_path / "test_wal_serial.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    eng = create_async_engine(
        url,
        echo=False,
        isolation_level="SERIALIZABLE",
        connect_args={"check_same_thread": False},
    )
    event.listen(eng.sync_engine, "connect", _apply_pragmas)
    yield eng
    await eng.dispose()


@pytest.mark.asyncio
async def test_serializable_and_wal_pragmas_coexist(file_engine_serializable) -> None:
    """SERIALIZABLE Isolation und WAL + foreign_keys Pragmas müssen gleichzeitig gelten.

    Stellt sicher dass isolation_level='SERIALIZABLE' den bestehenden
    _apply_pragmas-Listener nicht beeinträchtigt — kein zweiter Listener nötig,
    keine Konflikte zwischen Isolation Level und PRAGMA-Einstellungen.
    """
    async with file_engine_serializable.connect() as conn:
        level = await conn.get_isolation_level()
        journal = (await conn.execute(text("PRAGMA journal_mode"))).scalar()
        fk = (await conn.execute(text("PRAGMA foreign_keys"))).scalar()

    assert level == "SERIALIZABLE", f"Erwartet isolation_level='SERIALIZABLE', erhalten: {level!r}"
    assert journal == "wal", f"Erwartet journal_mode='wal' (WAL-Modus), erhalten: {journal!r}"
    assert fk == 1, f"Erwartet foreign_keys=1 (FK ON), erhalten: {fk!r}"
