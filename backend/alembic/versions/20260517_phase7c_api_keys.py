"""Phase 7c — api_keys table + audit columns on jobs.

D7: this migration used to seed an enabled ``bootstrap-admin`` key and print its
plaintext to stdout. That is removed: the first admin key now comes from the
one-time ``LABELYARD_BOOTSTRAP_ADMIN_KEY`` sign-in or from
``labelyard admin create-key``. Existing installs keep their rows.

Revision ID: 20260517_phase7c_api_keys
Revises: 20260517_phase7b_datetime_tz
Create Date: 2026-05-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260517_phase7c_api_keys"
down_revision = "20260517_phase7b_datetime_tz"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("key_hash", sa.String, nullable=False),
        sa.Column("key_prefix", sa.String, nullable=False),
        sa.Column("scopes", sa.JSON, nullable=False),
        sa.Column("allowed_printer_ids", sa.JSON, nullable=False),
        sa.Column("rate_limit_per_minute", sa.Integer, nullable=False, server_default="60"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_ip", sa.String, nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.String, nullable=True),
    )
    op.create_index("ix_api_keys_name", "api_keys", ["name"])
    op.create_index("ix_api_keys_key_prefix", "api_keys", ["key_prefix"])

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(sa.Column("api_key_id", sa.Uuid, nullable=True))
        batch_op.add_column(sa.Column("source_ip", sa.String, nullable=True))
    op.create_index("ix_jobs_api_key_id", "jobs", ["api_key_id"])


def downgrade() -> None:
    op.drop_index("ix_jobs_api_key_id", table_name="jobs")
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("source_ip")
        batch_op.drop_column("api_key_id")
    op.drop_index("ix_api_keys_key_prefix", table_name="api_keys")
    op.drop_index("ix_api_keys_name", table_name="api_keys")
    op.drop_table("api_keys")
