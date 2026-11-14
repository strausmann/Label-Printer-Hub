# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Migration 20261105a1 creates and removes the sheet archive tables."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

_ALEMBIC_INI = Path(__file__).parents[3] / "alembic.ini"
_REV = "20261105a1"
_PREV = "20261104a3"
_TABLES = {
    "sheet_types",
    "sheet_type_versions",
    "sheet_id_counters",
    "sheets",
    "sheet_cells",
    "sheet_write_lock",
}


def _cfg(db_path):
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    cfg.attributes["configure_logger"] = False
    return cfg


def _tables(db) -> set[str]:
    eng = create_engine(f"sqlite:///{db}")
    try:
        return set(inspect(eng).get_table_names())
    finally:
        eng.dispose()


def test_write_lock_row_present_after_migration(tmp_path):
    db = tmp_path / "sheets.db"
    command.upgrade(_cfg(db), "head")
    assert _tables(db) >= _TABLES
    eng = create_engine(f"sqlite:///{db}")
    with eng.connect() as c:
        rows = c.execute(text("SELECT id, seq FROM sheet_write_lock")).all()
        idx = {i["name"] for t in ("sheets", "sheet_cells") for i in inspect(c).get_indexes(t)}
    eng.dispose()
    assert [tuple(r) for r in rows] == [(1, 0)]
    assert {"ix_sheet_cells_source_ref", "ix_sheets_type_state", "ix_sheet_cells_job_id"} <= idx


def test_downgrade_removes_all_tables_and_upgrade_again_works(tmp_path):
    db = tmp_path / "sheets_down.db"
    cfg = _cfg(db)
    command.upgrade(cfg, _REV)
    command.downgrade(cfg, _PREV)
    assert not (_TABLES & _tables(db))
    command.upgrade(cfg, _REV)
    assert _tables(db) >= _TABLES


# ---------------------------------------------------------------- 20261107a1 feed mark (5c)

_MARK_REV = "20261107a1"
_MARK_PREV = "20261105b1"


def _sheet_columns(db) -> dict[str, dict]:
    eng = create_engine(f"sqlite:///{db}")
    try:
        return {c["name"]: c for c in inspect(eng).get_columns("sheets")}
    finally:
        eng.dispose()


def test_feed_mark_column_added_with_false_for_existing_rows_and_removed_again(tmp_path):
    db = tmp_path / "mark.db"
    cfg = _cfg(db)
    command.upgrade(cfg, _MARK_PREV)
    assert "feed_mark_printed" not in _sheet_columns(db)
    eng = create_engine(f"sqlite:///{db}")
    with eng.begin() as c:
        c.execute(
            text(
                "INSERT INTO sheets (id, code, type_id, type_version_id, state, id_placement, "
                "id_printed, created_at) VALUES "
                "('00000000000000000000000000000001', 'S-1', "
                "'00000000000000000000000000000002', '00000000000000000000000000000003', "
                "'active', 'margin', 1, '2026-11-07 00:00:00')"
            )
        )
    eng.dispose()

    command.upgrade(cfg, _MARK_REV)

    col = _sheet_columns(db)["feed_mark_printed"]
    assert col["nullable"] is False
    eng = create_engine(f"sqlite:///{db}")
    with eng.connect() as c:
        assert c.execute(text("SELECT feed_mark_printed FROM sheets")).scalar_one() == 0
    eng.dispose()

    command.downgrade(cfg, _MARK_PREV)
    assert "feed_mark_printed" not in _sheet_columns(db)
    command.upgrade(cfg, _MARK_REV)
    assert "feed_mark_printed" in _sheet_columns(db)
