"""Phase 7c — api_keys table + audit columns on jobs + bootstrap-admin seed.

Revision ID: 20260517_phase7c_api_keys
Revises: 20260517_phase7b_datetime_tz
Create Date: 2026-05-17
"""

from __future__ import annotations

import json
import secrets

import bcrypt
import sqlalchemy as sa
from alembic import op

revision = "20260517_phase7c_api_keys"
down_revision = "20260517_phase7b_datetime_tz"
branch_labels = None
depends_on = None

_BOOTSTRAP_KEY_NAME = "bootstrap-admin"


def _generate_bootstrap_key() -> tuple[str, str, str]:
    body = secrets.token_urlsafe(32)
    plaintext = f"lh_pat_{body}"
    prefix = plaintext[:16]
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=12)).decode()
    return plaintext, prefix, hashed


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

    conn = op.get_bind()
    count = conn.execute(sa.text("SELECT COUNT(*) FROM api_keys")).scalar()
    if count == 0:
        from datetime import UTC, datetime
        from uuid import uuid4

        plaintext, prefix, hashed = _generate_bootstrap_key()
        key_id = str(uuid4())
        now = datetime.now(UTC).isoformat()
        conn.execute(
            sa.text(
                "INSERT INTO api_keys "
                "(id, name, key_hash, key_prefix, scopes, allowed_printer_ids, "
                " rate_limit_per_minute, enabled, created_at) "
                "VALUES (:id, :name, :hash, :prefix, :scopes, :printers, "
                "        :rate, :enabled, :now)"
            ),
            {
                "id": key_id,
                "name": _BOOTSTRAP_KEY_NAME,
                "hash": hashed,
                "prefix": prefix,
                "scopes": json.dumps(["admin"]),
                "printers": json.dumps([]),
                "rate": 60,
                "enabled": 1,
                "now": now,
            },
        )
        # Print to stdout (Alembic migration stdout only — NOT the application logger).
        # This is the only time the plaintext key is visible; copy it before rotating.
        print(
            f"[label-printer-hub] BOOTSTRAP API KEY: {plaintext} (prefix: {prefix})"
            " — rotate via /api/admin/api-keys after first login"
        )


def downgrade() -> None:
    op.drop_index("ix_jobs_api_key_id", table_name="jobs")
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("source_ip")
        batch_op.drop_column("api_key_id")
    op.drop_index("ix_api_keys_key_prefix", table_name="api_keys")
    op.drop_index("ix_api_keys_name", table_name="api_keys")
    op.drop_table("api_keys")
