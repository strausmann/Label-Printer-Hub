"""Phase 7b — normalise existing datetime rows to timezone-aware ISO strings.

Existing rows from Phase 5 inserts contain naive datetimes (no TZ suffix)
that break the Go frontend's RFC3339 parser. This migration appends
`+00:00` to any value that does NOT already contain `+` or end with `Z`.
SQLite is dynamically typed so no ALTER TABLE is required — the new column
type from B4 only affects new inserts via the SQLAlchemy layer.

Revision ID: 20260517_phase7b_datetime_tz
Revises: b2668b6e8845
Create Date: 2026-05-17
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260517_phase7b_datetime_tz"
down_revision = "b2668b6e8845"
branch_labels = None
depends_on = None


_TABLES_DT = [
    ("templates", ["created_at", "updated_at"]),
    ("printers", ["created_at", "updated_at"]),
    ("jobs", ["created_at", "updated_at", "started_at", "finished_at"]),
    ("presets", ["created_at", "updated_at"]),
    ("printer_state", ["updated_at"]),
    ("printer_status_cache", ["captured_at", "updated_at"]),
]


def upgrade() -> None:
    for table, cols in _TABLES_DT:
        for col in cols:
            op.execute(
                f"UPDATE {table} SET {col} = {col} || '+00:00' "
                f"WHERE {col} IS NOT NULL "
                f"AND {col} NOT LIKE '%+%' "
                f"AND {col} NOT LIKE '%Z'"
            )


def downgrade() -> None:
    # The naive-datetime state being reverted to is exactly the bug we
    # are fixing. Downgrade is intentionally a no-op.
    pass
