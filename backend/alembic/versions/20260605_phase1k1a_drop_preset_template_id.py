"""Phase 1k.1a: drop presets.template_id column and templates table

The Template model and TemplateLoader were removed in Phase 1k.1a (layout
engine replaces template-based rendering). This migration:
  1. Drops the presets.template_id column (includes its FK to templates.id)
  2. Drops the templates table (no longer managed by any SQLModel class)

SQLite note: SQLite does not support named FK constraints. Alembic batch
mode handles FK removal implicitly when the column is dropped — no explicit
drop_constraint call is needed.

Revision ID: 20260605a1b2c3d4
Revises: a0516c04278c
Create Date: 2026-06-05 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260605a1b2c3d4"
down_revision: str | Sequence[str] | None = "a0516c04278c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop template_id from presets, then drop templates table."""
    # Batch mode recreates the table without the dropped column, which
    # also removes the FK constraint in SQLite (no explicit drop_constraint).
    with op.batch_alter_table("presets", schema=None) as batch_op:
        batch_op.drop_column("template_id")

    # Drop the templates table — no Python model references it any more.
    op.drop_table("templates")


def downgrade() -> None:
    """Recreate templates table and restore template_id column on presets."""
    # Recreate the minimal templates table schema from migration 54f963fdb994.
    op.create_table(
        "templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("app", sa.String(), nullable=True),
        sa.Column("printer_model", sa.String(), nullable=True),
        sa.Column("tape_width_mm", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("definition", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(), nullable=False, server_default="seed"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    with op.batch_alter_table("presets", schema=None) as batch_op:
        batch_op.add_column(sa.Column("template_id", sa.Uuid(), nullable=True))
        # SQLite does not support named FK constraints and alembic batch mode
        # requires a name for create_foreign_key. FK is omitted in downgrade
        # (column is re-added without FK constraint — acceptable for rollback).
