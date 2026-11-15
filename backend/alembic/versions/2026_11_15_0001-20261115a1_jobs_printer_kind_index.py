# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""index a printer's page jobs by kind and creation time

Revision ID: 20261115a1
Revises: 20261110a1
Create Date: 2026-11-15 08:00:00.000000

The printer status names the tray the newest sheet page and the newest calibration page job
used (#344): per printer and kind the latest job by ``created_at``. Without an index that read
every payload of the printer's jobs on each status call. The index over (printer, kind,
creation time) answers it with one seek and no sort. Building it parses each stored payload once.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261115a1"
down_revision: str | Sequence[str] | None = "20261110a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Must equal app.models.job.PAGE_KIND_EXPR (a test asks SQLite whether the status query's text
# uses this index). Guarded by json_valid like ix_jobs_page_sheet: an invalid payload gets NULL.
_EXPR = "CASE WHEN json_valid(payload) THEN json_extract(payload, '$.kind') END"


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_jobs_printer_kind_created "
        f"ON jobs (printer_id, ({_EXPR}), created_at)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_jobs_printer_kind_created")
