# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Normalise api_keys.id (and its references) to the 32-char hex form SQLModel binds.

The removed phase-7c seed inserted ``str(uuid4())`` (hyphenated). SQLite compares text, so a
row stored that way is invisible to ORM lookups by UUID, and a ``ui_sessions`` row pointing at
it breaks. Only SQLite stores UUIDs as text; other dialects have a native type and are left
alone. Downgrade is a no-op: both spellings denote the same UUID.

Revision ID: 20261104a3
Revises: 20261104a2
Create Date: 2026-11-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261104a3"
down_revision = "20261104a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "sqlite":
        return
    # Parent and children change inside one transaction; defer the FK check to commit.
    conn.execute(sa.text("PRAGMA defer_foreign_keys = ON"))
    for (old_id,) in conn.execute(sa.text("SELECT id FROM api_keys WHERE id LIKE '%-%'")).all():
        new_id = old_id.replace("-", "").lower()
        params = {"old": old_id, "new": new_id}
        conn.execute(sa.text("UPDATE api_keys SET id = :new WHERE id = :old"), params)
        conn.execute(sa.text("UPDATE jobs SET api_key_id = :new WHERE api_key_id = :old"), params)
        conn.execute(
            sa.text("UPDATE ui_sessions SET api_key_id = :new WHERE api_key_id = :old"), params
        )


def downgrade() -> None:
    """No-op: the hyphenated and the hex spelling are the same UUID."""
