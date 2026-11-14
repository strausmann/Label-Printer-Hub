# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""app_settings and ui_sessions tables for the web UI foundation.

Revision ID: 20261104a1
Revises: 42fbd015698d
Create Date: 2026-11-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261104a1"
down_revision = "42fbd015698d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String, primary_key=True),
        sa.Column("value_json", sa.String, nullable=True),
        sa.Column("secret_token", sa.String, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "ui_sessions",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("token_hash", sa.String, nullable=False),
        sa.Column("csrf_token", sa.String, nullable=False),
        sa.Column("source", sa.String, nullable=False),
        sa.Column("scope", sa.String, nullable=False),
        sa.Column("api_key_id", sa.Uuid, sa.ForeignKey("api_keys.id"), nullable=True),
        sa.Column("allowed_printer_ids", sa.JSON, nullable=False),
        sa.Column("user", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ui_sessions_token_hash", "ui_sessions", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_ui_sessions_token_hash", table_name="ui_sessions")
    op.drop_table("ui_sessions")
    op.drop_table("app_settings")
