"""Sheet feed-direction mark: ``sheets.feed_mark_printed``.

Revision ID: 20261107a1
Revises: 20261105b1
Create Date: 2026-11-07

The first job of a sheet prints a small orientation mark at the top edge (spec 10.2a). The mark
has its own flag: ``id_printed`` is never set on ``manual`` sheets and may stay false on a
``margin`` sheet whose ID did not fit. Existing sheets get false: the next job onto them prints
the mark.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261107a1"
down_revision = "20261105b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sheets") as batch:
        batch.add_column(
            sa.Column(
                "feed_mark_printed",
                sa.Boolean,
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("sheets") as batch:
        batch.drop_column("feed_mark_printed")
