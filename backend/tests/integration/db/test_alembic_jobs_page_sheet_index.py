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


_INSERT = (
    "INSERT INTO jobs (id, printer_id, state, payload, created_at, updated_at) "
    "VALUES (:id, 'p', 'queued', :payload, '2026-11-08', '2026-11-08')"
)
_NAN_TEXT = '{"kind": "sheet_page", "detail": {"sheet_id": "S1", "quantity": NaN}}'


def test_sqlite_calls_a_literal_nan_invalid_json() -> None:
    """The guard rests on this: ``json_valid`` is 0 for the text (on the dev SQLite as well as on
    the 3.40 of the production image, where the json functions raise on it instead)."""
    eng = create_engine("sqlite://")
    try:
        with eng.connect() as c:
            valid = c.execute(text("SELECT json_valid(:t)"), {"t": _NAN_TEXT}).scalar()
    finally:
        eng.dispose()
    assert valid == 0


def test_an_invalid_payload_breaks_neither_the_migration_nor_the_index(tmp_path: Path) -> None:
    """R12-1: a stored ``NaN`` made SQLite 3.40 fail the index build ("malformed JSON") and every
    later insert, so the hub did not start. The index expression is guarded by ``json_valid``."""
    db = tmp_path / "nan.db"
    cfg = _cfg(db)
    command.upgrade(cfg, _PREV)
    eng = create_engine(f"sqlite:///{db}")
    try:
        with eng.begin() as c:
            c.execute(text(_INSERT), {"id": "bad-1", "payload": _NAN_TEXT})
            c.execute(
                text(_INSERT),
                {"id": "ok-1", "payload": '{"kind":"sheet_page","detail":{"sheet_id":"S1"}}'},
            )

        command.upgrade(cfg, _REV)  # builds the index over both rows

        with eng.begin() as c:  # inserts into the indexed table still work
            c.execute(text(_INSERT), {"id": "bad-2", "payload": _NAN_TEXT})
            c.execute(
                text(_INSERT),
                {"id": "ok-2", "payload": '{"kind":"sheet_page","detail":{"sheet_id":"S1"}}'},
            )
        with eng.connect() as c:
            found = sorted(
                r[0] for r in c.execute(text(f"SELECT id FROM jobs WHERE {PAGE_SHEET_EXPR} = 'S1'"))
            )
            plan = c.execute(
                text(f"EXPLAIN QUERY PLAN SELECT id FROM jobs WHERE {PAGE_SHEET_EXPR} = 'S1'")
            ).all()
        assert found == ["ok-1", "ok-2"]  # the invalid payloads belong to no sheet
        assert any("ix_jobs_page_sheet" in str(row) for row in plan), plan

        command.downgrade(cfg, _PREV)
        assert "ix_jobs_page_sheet" not in _index_names(db)
    finally:
        eng.dispose()
