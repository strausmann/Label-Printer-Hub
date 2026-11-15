# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Migration 20261110a1: ``printers.layout_defaults`` (#258). Additive; existing rows get ``{}``."""

from __future__ import annotations

import json
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

_ALEMBIC_INI = Path(__file__).parents[3] / "alembic.ini"
_REV = "20261110a1"
_PREV = "20261109b1"
_PRINTER = "22222222222222222222222222222222"


def _cfg(db_path: Path) -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    cfg.attributes["configure_logger"] = False
    return cfg


def _columns(db: Path) -> dict[str, dict[str, object]]:
    eng = create_engine(f"sqlite:///{db}")
    try:
        return {c["name"]: dict(c) for c in inspect(eng).get_columns("printers")}
    finally:
        eng.dispose()


def test_the_revision_is_the_single_head(tmp_path: Path) -> None:
    from alembic.script import ScriptDirectory

    assert ScriptDirectory.from_config(_cfg(tmp_path / "x.db")).get_heads() == [_REV]


def test_upgrade_adds_the_column_and_keeps_rows_downgrade_drops_it(tmp_path: Path) -> None:
    db = tmp_path / "populated.db"
    cfg = _cfg(db)
    command.upgrade(cfg, _PREV)
    assert "layout_defaults" not in _columns(db)
    eng = create_engine(f"sqlite:///{db}")
    with eng.begin() as c:
        c.execute(
            text(
                "INSERT INTO printers (id, name, slug, model, backend, connection, enabled, "
                "queue_timeout_s, cut_defaults_half_cut, created_at, updated_at) VALUES "
                f"('{_PRINTER}', 'ql', 'ql', 'QL-820NWB', 'brother_ql', '{{}}', 1, 30, 0, "
                "'2026-11-01 00:00:00', '2026-11-01 00:00:00')"
            )
        )

    command.upgrade(cfg, _REV)
    cols = _columns(db)
    assert cols["layout_defaults"]["nullable"] is False
    with eng.begin() as c:
        stored = c.execute(text("SELECT layout_defaults FROM printers")).scalar()
    assert json.loads(str(stored)) == {}

    command.downgrade(cfg, _PREV)
    assert "layout_defaults" not in _columns(db)
    with eng.begin() as c:
        assert c.execute(text("SELECT count(*) FROM printers")).scalar() == 1
    eng.dispose()
