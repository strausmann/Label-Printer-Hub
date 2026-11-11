"""add the printer_identity table

Revision ID: 20261109b1
Revises: 20261109a1
Create Date: 2026-11-09 11:00:00.000000

One row per printer: the hardware identity (serial, IPP uuid or MAC) the status probes saw
behind its address, and the columns swap detection uses for a differing identity. All columns
but the key are nullable. Additive: no existing table changes, so a database upgrades without
data work and downgrades by dropping the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261109b1"
down_revision: str | Sequence[str] | None = "20261109a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "printer_identity",
        sa.Column("printer_id", sa.Uuid(), nullable=False),
        sa.Column("hardware_id", sa.String(), nullable=True),
        sa.Column("hardware_id_kind", sa.String(), nullable=True),
        sa.Column("hardware_id_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_id", sa.String(), nullable=True),
        sa.Column("observed_kind", sa.String(), nullable=True),
        sa.Column("mismatch_since", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["printer_id"], ["printers.id"]),
        sa.PrimaryKeyConstraint("printer_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("printer_identity")
