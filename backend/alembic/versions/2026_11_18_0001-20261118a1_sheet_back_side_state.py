# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""an extra code on the back of a sheet

Revision ID: 20261118a1
Revises: 20261117a2
Create Date: 2026-11-18 06:00:00.000000

1.7.0 acceptance: a ``margin``, ``manual`` or ``cell`` sheet whose code is printed can get its
code on the back of the liner as well. ``back_side_state`` is ``NULL`` (never asked for),
``pending`` (queued, not confirmed) or ``confirmed``; the placement does not change. It stays
``NULL`` for every existing sheet.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261118a1"
down_revision: str | Sequence[str] | None = "20261117a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("sheets") as batch:
        batch.add_column(sa.Column("back_side_state", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("sheets") as batch:
        batch.drop_column("back_side_state")
