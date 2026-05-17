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
    assert {"id","name","key_hash","key_prefix","scopes","allowed_printer_ids",
            "rate_limit_per_minute","enabled","created_at","last_used_at",
            "last_used_ip","expires_at","notes"}.issubset(col_names)
    eng.dispose()


def test_upgrade_adds_audit_columns_to_jobs(tmp_path):
    db = tmp_path / "p7c_jobs.db"
    command.upgrade(_cfg(db), _PHASE_7C_REV)
    eng = create_engine(f"sqlite:///{db}")
    cols = {c["name"] for c in inspect(eng).get_columns("jobs")}
    assert "api_key_id" in cols and "source_ip" in cols
    eng.dispose()


def test_upgrade_seeds_bootstrap_admin_key(tmp_path):
    import json
    db = tmp_path / "p7c_seed.db"
    command.upgrade(_cfg(db), _PHASE_7C_REV)
    eng = create_engine(f"sqlite:///{db}")
    with eng.connect() as conn:
        rows = conn.execute(text("SELECT name, scopes, enabled FROM api_keys")).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "bootstrap-admin"
    assert "admin" in json.loads(rows[0][1])
    assert rows[0][2] == 1
    eng.dispose()


def test_upgrade_idempotent_no_duplicate_seed(tmp_path):
    db = tmp_path / "p7c_idem.db"
    command.upgrade(_cfg(db), _PHASE_7C_REV)
    command.upgrade(_cfg(db), _PHASE_7C_REV)
    eng = create_engine(f"sqlite:///{db}")
    with eng.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM api_keys WHERE name='bootstrap-admin'")).scalar()
    assert count == 1
    eng.dispose()


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
        conn.execute(text(
            "INSERT INTO printers (id, name, model, backend, connection, enabled, created_at, updated_at) "
            "VALUES ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'test', 'pt', 'mock', '{}', 1, "
            "'2026-05-17T12:00:00+00:00', '2026-05-17T12:00:00+00:00')"
        ))
        conn.execute(text(
            "INSERT INTO jobs (id, printer_id, template_key, state, payload, created_at, updated_at) "
            "VALUES ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', "
            "'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', "
            "'label-v1', 'done', '{}', '2026-05-17T12:00:00+00:00', '2026-05-17T12:00:00+00:00')"
        ))
    eng.dispose()
    command.downgrade(_cfg(db), "-1")
    eng2 = create_engine(f"sqlite:///{db}")
    with eng2.connect() as conn:
        count = conn.execute(text(
            "SELECT COUNT(*) FROM jobs WHERE id='bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'"
        )).scalar()
    assert count == 1
    eng2.dispose()
