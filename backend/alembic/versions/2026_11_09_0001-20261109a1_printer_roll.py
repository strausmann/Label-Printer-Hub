# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""add the printer_roll table

Revision ID: 20261109a1
Revises: 20261108a1
Create Date: 2026-11-09 09:00:00.000000

One row per printer: the roll identity last seen (width, media text), the tape colour the
operator gave it, and whether the operator is still to be asked. Additive: no existing table
changes, so a 1.4.0 database upgrades without data work and downgrades by dropping the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261109a1"
down_revision: str | Sequence[str] | None = "20261108a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "printer_roll",
        sa.Column("printer_id", sa.Uuid(), nullable=False),
        sa.Column("width_mm", sa.Integer(), nullable=True),
        sa.Column("media_raw", sa.String(), nullable=True),
        sa.Column("colour", sa.String(), nullable=True),
        sa.Column("set_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("prompt_pending", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["printer_id"], ["printers.id"]),
        sa.PrimaryKeyConstraint("printer_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("printer_roll")
