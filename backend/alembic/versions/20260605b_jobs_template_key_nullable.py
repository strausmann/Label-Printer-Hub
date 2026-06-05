"""Phase 1k.1a: make jobs.template_key nullable to match SQLModel definition

The Job model defines template_key as Optional[str] (nullable=True) but the
initial jobs migration (e0d573b37f5b) created it as NOT NULL. This migration
corrects the nullable mismatch so alembic check passes.

Revision ID: 20260605b2c3d4e5
Revises: 20260605a1b2c3d4
Create Date: 2026-06-05 00:01:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260605b2c3d4e5"
down_revision: str | Sequence[str] | None = "20260605a1b2c3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Make jobs.template_key nullable (SQLite batch mode)."""
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.alter_column(
            "template_key",
            existing_type=sa.String(),
            nullable=True,
        )


def downgrade() -> None:
    """Restore jobs.template_key to NOT NULL."""
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.alter_column(
            "template_key",
            existing_type=sa.String(),
            nullable=False,
        )
