# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Migration 20261109a1: the printer_roll table (#229). Additive; 1.4.0 rows are kept."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

_ALEMBIC_INI = Path(__file__).parents[3] / "alembic.ini"
_REV = "20261109a1"
_PREV = "20261108a1"
_PRINTER = "11111111111111111111111111111111"


def _cfg(db_path: Path) -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    cfg.attributes["configure_logger"] = False
    return cfg


def _tables(db: Path) -> set[str]:
    eng = create_engine(f"sqlite:///{db}")
    try:
        return set(inspect(eng).get_table_names())
    finally:
        eng.dispose()


def test_upgrade_and_downgrade_on_an_empty_database(tmp_path: Path) -> None:
    db = tmp_path / "empty.db"
    cfg = _cfg(db)
    command.upgrade(cfg, _PREV)
    assert "printer_roll" not in _tables(db)
    command.upgrade(cfg, _REV)
    assert "printer_roll" in _tables(db)
    eng = create_engine(f"sqlite:///{db}")
    try:
        cols = {c["name"]: c for c in inspect(eng).get_columns("printer_roll")}
    finally:
        eng.dispose()
    assert set(cols) == {
        "printer_id",
        "width_mm",
        "media_raw",
        "colour",
        "set_at",
        "prompt_pending",
        "changed_at",
    }
    assert cols["prompt_pending"]["nullable"] is False
    command.downgrade(cfg, _PREV)
    assert "printer_roll" not in _tables(db)


def test_a_populated_1_4_0_database_keeps_its_rows_both_ways(tmp_path: Path) -> None:
    db = tmp_path / "populated.db"
    cfg = _cfg(db)
    command.upgrade(cfg, _PREV)
    eng = create_engine(f"sqlite:///{db}")
    with eng.begin() as c:
        c.execute(
            text(
                "INSERT INTO printers (id, name, slug, model, backend, connection, enabled, "
                "queue_timeout_s, cut_defaults_half_cut, created_at, updated_at) VALUES "
                f"('{_PRINTER}', 'p', 'p', 'PT-P750W', 'ptouch', '{{}}', 1, 30, 0, "
                "'2026-11-01 00:00:00', '2026-11-01 00:00:00')"
            )
        )
        c.execute(
            text(
                "INSERT INTO printer_status_cache (printer_id, parsed, updated_at) VALUES "
                f"('{_PRINTER}', '{{\"loaded_tape_mm\": 12}}', '2026-11-01 00:00:00')"
            )
        )
    command.upgrade(cfg, "head")
    with eng.begin() as c:
        assert c.execute(text("SELECT count(*) FROM printers")).scalar() == 1
        assert c.execute(text("SELECT count(*) FROM printer_status_cache")).scalar() == 1
        assert c.execute(text("SELECT count(*) FROM printer_roll")).scalar() == 0
        c.execute(
            text(
                "INSERT INTO printer_roll (printer_id, width_mm, changed_at) VALUES "
                f"('{_PRINTER}', 12, '2026-11-09 00:00:00')"
            )
        )
        flag = c.execute(text("SELECT prompt_pending FROM printer_roll")).scalar()
    assert flag == 0
    command.downgrade(cfg, _PREV)
    with eng.begin() as c:
        assert c.execute(text("SELECT count(*) FROM printers")).scalar() == 1
        assert c.execute(text("SELECT count(*) FROM printer_status_cache")).scalar() == 1
    eng.dispose()
    assert "printer_roll" not in _tables(db)
