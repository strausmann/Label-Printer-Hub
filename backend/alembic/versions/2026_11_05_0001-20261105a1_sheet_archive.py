# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Sheet archive: types, versions, counters, sheets, cells and the write-lock row.

Revision ID: 20261105a1
Revises: 20261104a3
Create Date: 2026-11-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261105a1"
down_revision = "20261104a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sheet_types",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("key", sa.String, nullable=False, unique=True),
        sa.Column("prefix", sa.String, nullable=False, unique=True),
        sa.Column("vendor", sa.String, nullable=True),
        sa.Column("product_codes", sa.JSON, nullable=False),
        sa.Column("description", sa.String, nullable=True),
        sa.Column("allow_qr", sa.Boolean, nullable=False),
        sa.Column("verified", sa.Boolean, nullable=False),
        sa.Column("origin", sa.String, nullable=False),
        sa.Column("source_name", sa.String, nullable=True),
        sa.Column("source_url", sa.String, nullable=True),
        sa.Column("notes", sa.String, nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String, nullable=True),
        sa.CheckConstraint("origin IN ('seed','custom','imported')", name="ck_sheet_types_origin"),
    )
    op.create_table(
        "sheet_type_versions",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("type_id", sa.Uuid, sa.ForeignKey("sheet_types.id"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("page_size", sa.String, nullable=False),
        sa.Column("page_w", sa.Integer, nullable=False),
        sa.Column("page_h", sa.Integer, nullable=False),
        sa.Column("label_w", sa.Integer, nullable=False),
        sa.Column("label_h", sa.Integer, nullable=False),
        sa.Column("cols", sa.Integer, nullable=False),
        sa.Column("rows", sa.Integer, nullable=False),
        sa.Column("pitch_x", sa.Integer, nullable=False),
        sa.Column("pitch_y", sa.Integer, nullable=False),
        sa.Column("margin_top", sa.Integer, nullable=False),
        sa.Column("margin_left", sa.Integer, nullable=False),
        sa.Column("corner_radius", sa.Integer, nullable=True),
        sa.Column("shape", sa.String, nullable=False),
        sa.Column("geometry_hash", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String, nullable=True),
        sa.Column("change_note", sa.String, nullable=True),
        sa.UniqueConstraint("type_id", "version", name="uq_sheet_type_versions_type_version"),
        sa.CheckConstraint("shape IN ('rectangle','round')", name="ck_sheet_type_versions_shape"),
        sa.CheckConstraint("page_size IN ('A4','Letter')", name="ck_sheet_type_versions_page_size"),
    )
    op.create_table(
        "sheet_id_counters",
        sa.Column("prefix", sa.String, primary_key=True),
        sa.Column("next_value", sa.Integer, nullable=False),
    )
    op.create_table(
        "sheets",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("code", sa.String, nullable=False, unique=True),
        sa.Column("type_id", sa.Uuid, sa.ForeignKey("sheet_types.id"), nullable=False),
        sa.Column(
            "type_version_id", sa.Uuid, sa.ForeignKey("sheet_type_versions.id"), nullable=False
        ),
        sa.Column("state", sa.String, nullable=False),
        sa.Column("discarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discarded_by", sa.String, nullable=True),
        sa.Column("id_placement", sa.String, nullable=False),
        sa.Column("id_printed", sa.Boolean, nullable=False),
        sa.Column("note", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String, nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("state IN ('active','discarded')", name="ck_sheets_state"),
        sa.CheckConstraint(
            "id_placement IN ('cell','margin','manual')", name="ck_sheets_id_placement"
        ),
    )
    op.create_index("ix_sheets_type_state", "sheets", ["type_id", "state"])
    op.create_table(
        "sheet_cells",
        sa.Column("sheet_id", sa.Uuid, sa.ForeignKey("sheets.id"), primary_key=True),
        sa.Column("cell_no", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("state", sa.String, nullable=False),
        sa.Column("job_id", sa.Uuid, nullable=True),
        sa.Column("source", sa.String, nullable=False),
        sa.Column("purpose", sa.String, nullable=True),
        sa.Column("ref", sa.String, nullable=True),
        sa.Column("marked_by_hand", sa.Boolean, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String, nullable=True),
        sa.CheckConstraint(
            "state IN ('reserved','used','unconfirmed')", name="ck_sheet_cells_state"
        ),
    )
    op.create_index("ix_sheet_cells_source_ref", "sheet_cells", ["source", "ref"])
    op.create_index("ix_sheet_cells_job_id", "sheet_cells", ["job_id"])
    op.create_table(
        "sheet_write_lock",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.CheckConstraint("id = 1", name="ck_sheet_write_lock_single_row"),
    )
    op.execute("INSERT INTO sheet_write_lock (id, seq) VALUES (1, 0)")


def downgrade() -> None:
    op.drop_table("sheet_write_lock")
    op.drop_index("ix_sheet_cells_job_id", table_name="sheet_cells")
    op.drop_index("ix_sheet_cells_source_ref", table_name="sheet_cells")
    op.drop_table("sheet_cells")
    op.drop_index("ix_sheets_type_state", table_name="sheets")
    op.drop_table("sheets")
    op.drop_table("sheet_id_counters")
    op.drop_table("sheet_type_versions")
    op.drop_table("sheet_types")
