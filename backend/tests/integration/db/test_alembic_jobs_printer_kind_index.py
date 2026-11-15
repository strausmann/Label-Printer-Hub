# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Migration 20261115a1: the index on a printer's page jobs by kind and creation time (#344)."""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from app.repositories.jobs import last_page_trays
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session

_ALEMBIC_INI = Path(__file__).parents[3] / "alembic.ini"
_REV = "20261115a1"
_PREV = "20261110a1"
_INDEX = "ix_jobs_printer_kind_created"


def _cfg(db_path: Path) -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    cfg.attributes["configure_logger"] = False
    return cfg


def _index_names(db: Path) -> set[str]:
    eng = create_engine(f"sqlite:///{db}")
    try:
        with eng.connect() as c:
            rows = c.execute(text("SELECT name FROM sqlite_master WHERE type='index'")).all()
        return {r[0] for r in rows}
    finally:
        eng.dispose()


def test_upgrade_creates_and_downgrade_drops_the_index(tmp_path: Path) -> None:
    db = tmp_path / "idx.db"
    cfg = _cfg(db)
    command.upgrade(cfg, _PREV)
    assert _INDEX not in _index_names(db)

    command.upgrade(cfg, _REV)
    assert _INDEX in _index_names(db)

    command.downgrade(cfg, _PREV)
    assert _INDEX not in _index_names(db)


def test_the_status_query_uses_the_index(tmp_path: Path) -> None:
    """Both index columns are used (printer and kind), and nothing sorts.

    The index name alone would also appear when the planner uses only the ``printer_id``
    prefix (a query built with another JSON text); the constraint part tells the two apart.
    """
    import asyncio

    db = tmp_path / "plan.db"
    command.upgrade(_cfg(db), "head")
    captured: list[str] = []

    async def _run() -> None:
        from sqlalchemy import event

        engine = create_async_engine(f"sqlite+aiosqlite:///{db}")

        def _grab(conn, cursor, statement, parameters, context, executemany):
            if "FROM jobs" in statement:
                captured.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", _grab)
        try:
            from sqlalchemy.ext.asyncio import AsyncSession

            async with AsyncSession(engine) as session:
                await last_page_trays(session, uuid4())
        finally:
            await engine.dispose()

    asyncio.run(_run())
    assert len(captured) == 1
    # Inline the bind values (hex of the printer id as stored) so the plan sees constants.
    sql = re.sub(r"\?", "'x'", captured[0])
    eng = create_engine(f"sqlite:///{db}")
    try:
        with Session(eng) as s:
            plan = [str(r) for r in s.execute(text(f"EXPLAIN QUERY PLAN {sql}")).all()]
    finally:
        eng.dispose()

    searches = [row for row in plan if f"USING INDEX {_INDEX}" in row]
    assert len(searches) >= 3, plan  # sheet, calibration tray, calibration time
    for row in searches:
        assert "printer_id=? AND" in row and "=?" in row.split("AND", 1)[1], row
    assert not any("TEMP B-TREE" in row for row in plan), plan
