"""index the sheet of a page job

Revision ID: 20261108a1
Revises: 20261107a1
Create Date: 2026-11-08 08:00:00.000000

The in-flight rules of a reservation look up the page jobs of one sheet while the sheet write
lock is held. Without an index they read every queued payload of the hub (megabytes), so the
time under the lock grew with the queue (run-11 R11-1). An index on the sheet expression lets
SQLite find the few jobs of one sheet. Building it parses each stored payload once.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261108a1"
down_revision: str | Sequence[str] | None = "20261107a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Must equal app.repositories.sheets.PAGE_SHEET_EXPR.
_EXPR = "json_extract(payload, '$.detail.sheet_id')"


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_jobs_page_sheet ON jobs ({_EXPR})")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_jobs_page_sheet")
