"""ui_sessions.sso_trust_fingerprint: bind SSO sessions to the trust token in use.

Revision ID: 20261104a2
Revises: 20261104a1
Create Date: 2026-11-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261104a2"
down_revision = "20261104a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ui_sessions") as batch:
        batch.add_column(sa.Column("sso_trust_fingerprint", sa.String, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("ui_sessions") as batch:
        batch.drop_column("sso_trust_fingerprint")
