"""Page printers: trays and per-tray calibration.

Revision ID: 20261105b1
Revises: 20261105a1
Create Date: 2026-11-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261105b1"
down_revision = "20261105a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No ON DELETE action: printers are soft-disabled, never deleted.
    op.create_table(
        "printer_trays",
        sa.Column("printer_id", sa.Uuid, sa.ForeignKey("printers.id"), primary_key=True),
        sa.Column("tray_key", sa.String, primary_key=True),
        sa.Column("label", sa.String, nullable=False),
        sa.Column("load_hint", sa.String, nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("is_default", sa.Boolean, nullable=False),
    )
    op.create_table(
        "printer_calibrations",
        sa.Column("printer_id", sa.Uuid, sa.ForeignKey("printers.id"), primary_key=True),
        sa.Column("tray_key", sa.String, primary_key=True),
        sa.Column("method", sa.String, nullable=False),
        sa.Column("offset_x_hmm", sa.Integer, nullable=False),
        sa.Column("offset_y_hmm", sa.Integer, nullable=False),
        sa.Column("scale_x_ppm", sa.Integer, nullable=False),
        sa.Column("scale_y_ppm", sa.Integer, nullable=False),
        sa.Column("rotation_udeg", sa.Integer, nullable=False),
        sa.Column("corrections", sa.JSON, nullable=True),
        sa.Column("measured_on_type_version_id", sa.Uuid, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String, nullable=True),
        sa.CheckConstraint("method IN ('manual','photo')", name="ck_printer_calibrations_method"),
    )


def downgrade() -> None:
    op.drop_table("printer_calibrations")
    op.drop_table("printer_trays")
