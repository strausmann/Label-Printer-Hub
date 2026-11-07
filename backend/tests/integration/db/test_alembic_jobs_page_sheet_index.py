"""Migration 20261108a1: the index on a page job's sheet (run-11 R11-1)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from app.repositories.sheets import PAGE_SHEET_EXPR
from sqlalchemy import create_engine, text

_ALEMBIC_INI = Path(__file__).parents[3] / "alembic.ini"
_REV = "20261108a1"
_PREV = "20261107a1"


def _cfg(db_path: Path) -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    cfg.attributes["configure_logger"] = False
    return cfg


def _index_names(db: Path) -> set[str]:
    eng = create_engine(f"sqlite:///{db}")
    try:
        with eng.connect() as c:  # the inspector skips expression indexes
            rows = c.execute(text("SELECT name FROM sqlite_master WHERE type='index'")).all()
        return {r[0] for r in rows}
    finally:
        eng.dispose()


def test_upgrade_creates_and_downgrade_drops_the_index(tmp_path: Path) -> None:
    db = tmp_path / "idx.db"
    cfg = _cfg(db)
    command.upgrade(cfg, _PREV)
    assert "ix_jobs_page_sheet" not in _index_names(db)

    command.upgrade(cfg, _REV)
    assert "ix_jobs_page_sheet" in _index_names(db)

    command.downgrade(cfg, _PREV)
    assert "ix_jobs_page_sheet" not in _index_names(db)


def test_a_sheets_jobs_are_found_by_the_index(tmp_path: Path) -> None:
    """The query text must match the index text, or SQLite scans (and parses) every payload."""
    db = tmp_path / "plan.db"
    command.upgrade(_cfg(db), "head")
    eng = create_engine(f"sqlite:///{db}")
    try:
        with eng.connect() as c:
            plan = c.execute(
                text(f"EXPLAIN QUERY PLAN SELECT payload FROM jobs WHERE {PAGE_SHEET_EXPR} = 'x'")
            ).all()
    finally:
        eng.dispose()
    assert any("ix_jobs_page_sheet" in str(row) for row in plan), plan
