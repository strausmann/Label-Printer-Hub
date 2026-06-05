"""Phase 7b — datetime data migration normalises naive rows to tz-aware UTC.

Phase 1k.1a (Task 25): test_migration_adds_tz_to_naive_template_row and
test_migration_does_not_touch_already_tz_aware_rows removed — the templates
table is dropped at head by migration 20260605a1b2c3d4.
Only the idempotency test (upgrade to head twice) is retained.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

_ALEMBIC_INI = Path(__file__).parents[3] / "alembic.ini"


def _alembic_config(db_path: Path) -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    # env.py uses async_engine_from_config, so the aiosqlite async driver is required.
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    # Prevent alembic from calling logging.config.fileConfig() which invokes
    # disable_existing_loggers=True and marks loggers such as `app.integrations`
    # as disabled.  When those loggers are disabled their records are silently
    # dropped, breaking pytest caplog assertions in tests that run AFTER these
    # migration tests.  The same guard is already present in app/db/lifespan.py
    # for the same reason.
    cfg.attributes["configure_logger"] = False
    return cfg


def test_migration_is_idempotent(tmp_path):
    db = tmp_path / "phase7b_idempotent.db"
    cfg = _alembic_config(db)
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")  # second run must be a no-op
