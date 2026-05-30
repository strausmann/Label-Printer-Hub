"""Phase 7c — update key_prefix to VARCHAR(16) for lh_pat_ format.

Revision ID: 20260518_phase7c_pat_prefix
Revises: 20260517_phase7c_api_keys
Create Date: 2026-05-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260518_phase7c_pat_prefix"
down_revision = "20260517_phase7c_api_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite via batch_alter_table supports column type changes.
    # For PostgreSQL the String type without length is unlimited, so this
    # migration is a no-op in production but makes the intent explicit.
    with op.batch_alter_table("api_keys") as batch_op:
        batch_op.alter_column(
            "key_prefix",
            existing_type=sa.String(),
            type_=sa.String(16),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("api_keys") as batch_op:
        batch_op.alter_column(
            "key_prefix",
            existing_type=sa.String(16),
            type_=sa.String(12),
            nullable=False,
        )
