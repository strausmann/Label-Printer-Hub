# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Sheet writes under contention on a real SQLite file in WAL mode (Review Focus 3, 4).

In-memory SQLite has no WAL and no second connection, so it cannot show ``database is
locked``; these tests use a temp file, the production pragmas and one engine with several
sessions racing through ``asyncio.gather``.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from collections.abc import AsyncIterator
from typing import Any

import app.models  # noqa: F401 — registers all models with SQLModel.metadata
import pytest
import pytest_asyncio
from app.db.engine import _apply_pragmas
from app.models.sheet import SheetCell
from app.sheets import sheet_service as ss
from app.sheets import type_service as ts
from app.sheets.errors import CellsTakenError
from app.sheets.geometry import Geometry
from app.sheets.locking import (
    acquire_sheet_write_lock,
    install_statement_counter,
    uninstall_statement_counter,
)
from app.sheets.sheet_service import MarkedCell
from sqlalchemy import Engine, event, func, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlmodel import SQLModel

G48 = Geometry(
    page_size="A4",
    page_w=21000,
    page_h=29700,
    label_w=4570,
    label_h=2120,
    cols=4,
    rows=12,
    pitch_x=4850,
    pitch_y=2120,
    margin_top=2150,
    margin_left=840,
    corner_radius=None,
    shape="rectangle",
)
FIELDS = ts.TypeFields(
    key="avery-l4736rev",
    prefix="L4736",
    vendor="Avery",
    product_codes=["L4736REV-25"],
    description=None,
    allow_qr=None,
)


@pytest_asyncio.fixture
async def factory(tmp_path: pathlib.Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine: AsyncEngine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'hub.db'}")
    event.listen(engine.sync_engine, "connect", _apply_pragmas)  # WAL + busy_timeout
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        assert (await s.execute(text("PRAGMA journal_mode"))).scalar() == "wal"
        await ts.create_type(s, FIELDS, G48, actor="tester")
    yield maker
    await engine.dispose()


async def test_parallel_create_gives_distinct_codes(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async def one(i: int) -> str:
        async with factory() as s:
            sheet = await ss.create_sheet(
                s,
                type_key="avery-l4736rev",
                version=None,
                id_placement="manual",
                used_cells=[MarkedCell(1)],
                note=None,
                actor=f"client-{i}",
            )
            return sheet.code

    codes = await asyncio.gather(*(one(i) for i in range(10)))  # an error would raise here
    assert sorted(codes) == [f"L4736-{n:04d}" for n in range(1, 11)]
    async with factory() as s:
        assert await ss.peek_next_code(s, "avery-l4736rev") == "L4736-0011"
        rows = (await s.execute(select(func.count()).select_from(SheetCell))).scalar_one()
        assert rows == 10


async def test_parallel_mark_same_cell_one_conflict(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as s:
        code = (
            await ss.create_sheet(
                s,
                type_key="avery-l4736rev",
                version=None,
                id_placement="manual",
                used_cells=[],
                note=None,
                actor="tester",
            )
        ).code

    async def one(purpose: str) -> Any:
        async with factory() as s:
            try:
                return await ss.mark_cells(s, code, [MarkedCell(7, purpose)], actor=purpose)
            except CellsTakenError as exc:
                return exc

    # Two contenders is the case the plan names; more of them make the race reliable.
    for contenders in (2, 8):
        async with factory() as s:
            await s.execute(text("DELETE FROM sheet_cells"))
            await s.commit()
        results = await asyncio.gather(*(one(f"client-{i}") for i in range(contenders)))
        errors = [r for r in results if isinstance(r, CellsTakenError)]
        successes = [r for r in results if not isinstance(r, Exception)]
        assert len(successes) == 1 and len(errors) == contenders - 1, results
        assert all(e.detail == {"cells": [7]} for e in errors)
    async with factory() as s:
        detail = await ss.get_sheet(s, code)
        assert [c.cell_no for c in detail.cells] == [7]
        assert detail.cells[0].purpose == successes[0].cells[0].purpose


async def test_parallel_mark_many_overlapping_never_half_written(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as s:
        code = (
            await ss.create_sheet(
                s,
                type_key="avery-l4736rev",
                version=None,
                id_placement="manual",
                used_cells=[],
                note=None,
                actor="tester",
            )
        ).code

    # Every request wants cell 1 plus one cell of its own: exactly one may win, and the
    # losers must not leave their own cell behind.
    async def one(i: int) -> bool:
        async with factory() as s:
            try:
                await ss.mark_cells(s, code, [MarkedCell(1), MarkedCell(10 + i)], actor="x")
                return True
            except CellsTakenError:
                return False

    results = await asyncio.gather(*(one(i) for i in range(8)))
    assert results.count(True) == 1
    async with factory() as s:
        assert len((await ss.get_sheet(s, code)).cells) == 2


# --- the lock on the migrated schema ----------------------------------------------------

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[2]


def _alembic_upgrade_to_head(db_path: pathlib.Path) -> None:
    alembic_bin = pathlib.Path(sys.executable).parent / "alembic"
    with tempfile.TemporaryDirectory() as tmp:
        sandbox = pathlib.Path(tmp)
        shutil.copy2(BACKEND_DIR / "alembic.ini", sandbox / "alembic.ini")
        shutil.copytree(BACKEND_DIR / "alembic", sandbox / "alembic")
        ini = (sandbox / "alembic.ini").read_text()
        ini = ini.replace("sqlite+aiosqlite:///./data/hub.db", f"sqlite+aiosqlite:///{db_path}")
        (sandbox / "alembic.ini").write_text(ini)
        env = os.environ.copy()
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{BACKEND_DIR}{os.pathsep}{existing}" if existing else str(BACKEND_DIR)
        result = subprocess.run(
            [str(alembic_bin), "upgrade", "head"],
            cwd=sandbox,
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_write_lock_on_migrated_schema(tmp_path: pathlib.Path) -> None:
    """The migration seeds the lock row with seq 0; the upsert must bump it, not insert."""
    db_path = tmp_path / "migrated.db"
    _alembic_upgrade_to_head(db_path)
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    event.listen(engine.sync_engine, "connect", _apply_pragmas)
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as s:
            rows = (await s.execute(text("SELECT id, seq FROM sheet_write_lock"))).all()
            assert [tuple(r) for r in rows] == [(1, 0)]
            await s.commit()  # the lock is the first statement of its transaction (264-01)
            await acquire_sheet_write_lock(s)
            await s.commit()
            rows = (await s.execute(text("SELECT id, seq FROM sheet_write_lock"))).all()
            assert [tuple(r) for r in rows] == [(1, 1)]
            # and a whole sheet write runs on the migrated schema too
            await ts.create_type(s, FIELDS, G48, actor="tester")
            sheet = await ss.create_sheet(
                s,
                type_key="avery-l4736rev",
                version=None,
                id_placement="margin",
                used_cells=[MarkedCell(3)],
                note=None,
                actor="tester",
            )
            assert sheet.code == "L4736-0001"
            seq = (await s.execute(text("SELECT seq FROM sheet_write_lock"))).scalar()
            assert seq == 3
    finally:
        await engine.dispose()


# --- the lock must be the first statement (264-01) --------------------------------------


async def _lock_seq(maker: async_sessionmaker[AsyncSession]) -> int:
    async with maker() as s:
        return int((await s.execute(text("SELECT seq FROM sheet_write_lock"))).scalar_one())


async def test_lock_as_first_statement_passes(factory: async_sessionmaker[AsyncSession]) -> None:
    before = await _lock_seq(factory)
    async with factory() as s:
        await acquire_sheet_write_lock(s)
        await s.commit()
    assert await _lock_seq(factory) == before + 1


async def test_lock_after_read_raises(factory: async_sessionmaker[AsyncSession]) -> None:
    before = await _lock_seq(factory)
    async with factory() as s:
        await s.execute(select(func.count()).select_from(SheetCell))
        with pytest.raises(RuntimeError, match="must be the first statement"):
            await acquire_sheet_write_lock(s)
        await s.rollback()
        # A new transaction starts at zero again: the guard counts per transaction.
        await acquire_sheet_write_lock(s)
        await s.commit()
    assert await _lock_seq(factory) == before + 1


async def test_lock_without_counter_refuses(tmp_path: pathlib.Path) -> None:
    """An engine without the counter must not pass as "no statement yet"."""
    uninstall_statement_counter(Engine)  # the test engine factory installs it on the class
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'bare.db'}")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as s:
            with pytest.raises(RuntimeError, match="statement counter not installed"):
                await acquire_sheet_write_lock(s)
    finally:
        await engine.dispose()
        install_statement_counter(Engine)


async def test_read_then_foreign_write_then_lock(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """The case the order rule exists for: A reads, B commits a write, then A asks for the lock.

    Without the guard SQLite answers A's upgrade from a stale read snapshot with
    ``database is locked`` (SQLITE_BUSY_SNAPSHOT); with it A is refused before SQLite is asked,
    and B's write stands.
    """
    async with factory() as a:
        # The driver opens no SQLite transaction for a bare SELECT (legacy transaction control),
        # so the read snapshot is opened explicitly, as an earlier write in the transaction would.
        await a.execute(text("BEGIN"))
        await a.execute(select(func.count()).select_from(SheetCell))
        async with factory() as b:
            await acquire_sheet_write_lock(b)
            await b.commit()
        seq = await _lock_seq(factory)
        with pytest.raises(RuntimeError, match="must be the first statement"):
            await acquire_sheet_write_lock(a)
        await a.rollback()
    assert await _lock_seq(factory) == seq
