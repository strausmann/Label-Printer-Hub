# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""add printers.layout_defaults

Revision ID: 20261110a1
Revises: 20261109b1
Create Date: 2026-11-10 12:00:00.000000

The stored QL layout default per printer and tape width (#258): a JSON object keyed by the
tape width in mm, e.g. ``{"62": {"orientation": "across", "preset": "compact"}}``. Additive:
existing rows get ``{}`` (the built-in tape default applies); downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261110a1"
down_revision: str | Sequence[str] | None = "20261109b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("printers") as batch:
        batch.add_column(
            sa.Column("layout_defaults", sa.JSON(), nullable=False, server_default="{}")
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("printers") as batch:
        batch.drop_column("layout_defaults")
