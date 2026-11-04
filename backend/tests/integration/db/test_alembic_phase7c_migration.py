"""Phase 7c — migration creates api_keys table + extends jobs table."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

_ALEMBIC_INI = Path(__file__).parents[3] / "alembic.ini"
_PHASE_7C_REV = "20260517_phase7c_api_keys"


def _cfg(db_path):
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    cfg.attributes["configure_logger"] = False
    return cfg


def test_upgrade_creates_api_keys_table(tmp_path):
    db = tmp_path / "p7c_schema.db"
    command.upgrade(_cfg(db), _PHASE_7C_REV)
    eng = create_engine(f"sqlite:///{db}")
    assert "api_keys" in inspect(eng).get_table_names()
    col_names = {c["name"] for c in inspect(eng).get_columns("api_keys")}
    assert {
        "id",
        "name",
        "key_hash",
        "key_prefix",
        "scopes",
        "allowed_printer_ids",
        "rate_limit_per_minute",
        "enabled",
        "created_at",
        "last_used_at",
        "last_used_ip",
        "expires_at",
        "notes",
    }.issubset(col_names)
    eng.dispose()


def test_upgrade_adds_audit_columns_to_jobs(tmp_path):
    db = tmp_path / "p7c_jobs.db"
    command.upgrade(_cfg(db), _PHASE_7C_REV)
    eng = create_engine(f"sqlite:///{db}")
    cols = {c["name"] for c in inspect(eng).get_columns("jobs")}
    assert "api_key_id" in cols and "source_ip" in cols
    eng.dispose()


def test_upgrade_seeds_no_api_key_and_prints_none(tmp_path, capfd):
    """D7: the bootstrap key and `printer-hub admin create-key` replace the old seed.

    The migration used to insert an enabled admin key and print its plaintext to
    stdout; that made the bootstrap key unusable and put a key in the container log.
    """
    db = tmp_path / "p7c_seed.db"
    command.upgrade(_cfg(db), _PHASE_7C_REV)
    out, err = capfd.readouterr()
    assert "lh_" not in out + err
    eng = create_engine(f"sqlite:///{db}")
    with eng.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM api_keys")).scalar()
    assert count == 0
    eng.dispose()


def test_upgrade_keeps_existing_key_rows(tmp_path):
    """Existing installs keep their rows: re-running upgrade never touches api_keys."""
    db = tmp_path / "p7c_keep.db"
    command.upgrade(_cfg(db), _PHASE_7C_REV)
    eng = create_engine(f"sqlite:///{db}")
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO api_keys (id, name, key_hash, key_prefix, scopes,"
                " allowed_printer_ids, rate_limit_per_minute, enabled, created_at)"
                " VALUES ('cccccccc-cccc-cccc-cccc-cccccccccccc', 'kept', 'fake-hash',"
                " 'lh_pat_fakepref', '[\"admin\"]', '[]', 60, 1, '2026-05-17T12:00:00+00:00')"
            )
        )
    eng.dispose()
    command.upgrade(_cfg(db), "head")
    eng2 = create_engine(f"sqlite:///{db}")
    with eng2.connect() as conn:
        names = [r[0] for r in conn.execute(text("SELECT name FROM api_keys")).fetchall()]
    assert names == ["kept"]
    eng2.dispose()


def test_downgrade_removes_api_keys_table(tmp_path):
    db = tmp_path / "p7c_down.db"
    command.upgrade(_cfg(db), _PHASE_7C_REV)
    command.downgrade(_cfg(db), "-1")
    eng = create_engine(f"sqlite:///{db}")
    assert "api_keys" not in inspect(eng).get_table_names()
    eng.dispose()


def test_existing_jobs_survive_downgrade(tmp_path):
    db = tmp_path / "p7c_survive.db"
    command.upgrade(_cfg(db), _PHASE_7C_REV)
    eng = create_engine(f"sqlite:///{db}")
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO printers"
                " (id, name, model, backend, connection, enabled, created_at, updated_at)"
                " VALUES ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'test', 'pt', 'mock', '{}', 1,"
                " '2026-05-17T12:00:00+00:00', '2026-05-17T12:00:00+00:00')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO jobs"
                " (id, printer_id, template_key, state, payload, created_at, updated_at)"
                " VALUES ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',"
                " 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',"
                " 'label-v1', 'done', '{}',"
                " '2026-05-17T12:00:00+00:00', '2026-05-17T12:00:00+00:00')"
            )
        )
    eng.dispose()
    command.downgrade(_cfg(db), "-1")
    eng2 = create_engine(f"sqlite:///{db}")
    with eng2.connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM jobs WHERE id='bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'")
        ).scalar()
    assert count == 1
    eng2.dispose()
