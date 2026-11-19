# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""who switched a sheet's code to the back side

Revision ID: 20261117a2
Revises: 20261117a1
Create Date: 2026-11-17 18:00:00.000000

#350 review M5: an unprinted ``margin`` or ``manual`` sheet can switch to ``back_side`` when someone
prints its code on the back. ``placement_changed_at`` and ``placement_changed_by`` record when and
by whom, like ``discarded_at``/``discarded_by``. Both stay ``NULL`` for every existing sheet.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261117a2"
down_revision: str | Sequence[str] | None = "20261117a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("sheets") as batch:
        batch.add_column(
            sa.Column("placement_changed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(sa.Column("placement_changed_by", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("sheets") as batch:
        batch.drop_column("placement_changed_by")
        batch.drop_column("placement_changed_at")
