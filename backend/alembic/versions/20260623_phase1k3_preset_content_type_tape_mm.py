"""Phase 1k.3: content_type + tape_mm auf presets-Tabelle (Refs #104)

Revision ID: 20260623_phase1k3_preset_layout
Revises: 42fbd015698d
Create Date: 2026-06-23

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260623_phase1k3_preset_layout"
down_revision: str | Sequence[str] | None = "42fbd015698d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Zwei neue Spalten auf presets: content_type (Default qr_three_lines) und tape_mm (Default 12)."""
    op.add_column(
        "presets",
        sa.Column(
            "content_type",
            sa.String(),
            nullable=False,
            server_default="qr_three_lines",
        ),
    )
    op.add_column(
        "presets",
        sa.Column(
            "tape_mm",
            sa.Integer(),
            nullable=False,
            server_default="12",
        ),
    )


def downgrade() -> None:
    """Spalten content_type und tape_mm von presets entfernen."""
    op.drop_column("presets", "tape_mm")
    op.drop_column("presets", "content_type")
