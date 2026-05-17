"""Phase 7b — datetime data migration normalises naive rows to tz-aware UTC.

The migration must be idempotent: running it twice on the same row must NOT
result in `2026-05-17T12:00:00+00:00+00:00`.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

_ALEMBIC_INI = Path(__file__).parents[3] / "alembic.ini"


def _alembic_config(db_path: Path) -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    # env.py uses async_engine_from_config, so the aiosqlite async driver is required.
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    return cfg


def test_migration_adds_tz_to_naive_template_row(tmp_path):
    db = tmp_path / "phase7b_data.db"
    sync_url = f"sqlite:///{db}"
    cfg = _alembic_config(db)

    # Walk schema forward to head (gives us tables with the new column types).
    command.upgrade(cfg, "head")

    # Roll back to the migration BEFORE this one so we can simulate a legacy
    # DB with naive datetime rows, then upgrade forward and check the result.
    command.downgrade(cfg, "-1")

    sync_engine = create_engine(sync_url)
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO templates (id, key, name, app, printer_model, "
                "tape_width_mm, schema_version, definition, source, "
                "created_at, updated_at) "
                "VALUES ('11111111-1111-1111-1111-111111111111', 'k', 'n', NULL, "
                "'pt-series', 12, 1, '{}', 'seed', "
                "'2026-05-17T12:00:00', '2026-05-17T12:00:00')"
            )
        )

    command.upgrade(cfg, "head")

    with sync_engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT created_at, updated_at FROM templates "
                "WHERE id = '11111111-1111-1111-1111-111111111111'"
            )
        ).first()
        assert row is not None
        for value in row:
            assert value.endswith("+00:00") or value.endswith("Z"), (
                f"datetime not normalised: {value!r}"
            )

    sync_engine.dispose()


def test_migration_is_idempotent(tmp_path):
    db = tmp_path / "phase7b_idempotent.db"
    cfg = _alembic_config(db)
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")  # second run must be a no-op


def test_migration_does_not_touch_already_tz_aware_rows(tmp_path):
    db = tmp_path / "phase7b_already_tz.db"
    sync_url = f"sqlite:///{db}"
    cfg = _alembic_config(db)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "-1")

    sync_engine = create_engine(sync_url)
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO templates (id, key, name, app, printer_model, "
                "tape_width_mm, schema_version, definition, source, "
                "created_at, updated_at) "
                "VALUES ('22222222-2222-2222-2222-222222222222', 'k2', 'n', NULL, "
                "'pt-series', 12, 1, '{}', 'seed', "
                "'2026-05-17T12:00:00+00:00', '2026-05-17T12:00:00+00:00')"
            )
        )

    command.upgrade(cfg, "head")

    with sync_engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT created_at FROM templates WHERE id = '22222222-2222-2222-2222-222222222222'"
            )
        ).first()
        # Must not be '2026-05-17T12:00:00+00:00+00:00'
        assert row[0].count("+00:00") == 1, f"double-suffix detected: {row[0]!r}"

    sync_engine.dispose()
