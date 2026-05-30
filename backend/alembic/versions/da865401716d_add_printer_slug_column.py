"""add printer slug column

Revision ID: da865401716d
Revises: 20260518_phase7c_pat_prefix
Create Date: 2026-05-30 15:03:06.420359

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "da865401716d"
down_revision: str | Sequence[str] | None = "20260518_phase7c_pat_prefix"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "printers",
        sa.Column(
            "slug",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            server_default="",
        ),
    )
    # Backfill aus name: existierende Drucker erhalten einen slug
    op.execute("UPDATE printers SET slug = LOWER(REPLACE(name, ' ', '-')) WHERE slug = ''")
    op.create_index(op.f("ix_printers_slug"), "printers", ["slug"], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_printers_slug"), table_name="printers")
    op.drop_column("printers", "slug")
