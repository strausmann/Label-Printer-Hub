# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""how a tape printer confirms its prints

Revision ID: 20261118a2
Revises: 20261118a1
Create Date: 2026-11-18 12:00:00.000000

#393: a tape printer's test print finds out whether the printer confirms a print over IPP (job
state) or with its label counter, and stores it here: ``{"confirm_transport": "ipp"|"raw",
"label_counter": bool, "confirmed_at": iso}``. ``NULL`` for every existing printer: the hub then
probes IPP at runtime until the next test print.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261118a2"
down_revision: str | Sequence[str] | None = "20261118a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("printers") as batch:
        batch.add_column(sa.Column("print_confirmation", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("printers") as batch:
        batch.drop_column("print_confirmation")
