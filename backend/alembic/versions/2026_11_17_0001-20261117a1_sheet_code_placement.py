# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""sheet code on the back side or in a reserved cell

Revision ID: 20261117a1
Revises: 20261115a1
Create Date: 2026-11-17 08:00:00.000000

#350: a sheet type says where the sheet code of a new sheet goes (``id_placement``, default
``auto`` everywhere, so existing types keep resolving as before), which cell a ``cell`` sheet
prefers (``id_cell``) and which vendor print the back of its liner carries
(``backing_design_id`` → ``backing_designs``). A sheet gains ``back_side`` as a placement and
remembers its preferred ID cell (``id_cell_no``). ``printer_tray_loading`` records how a tray
takes paper, in its own table because the tray list is replaced on every printer save.

Downgrade maps ``back_side`` sheets to ``manual`` (an older hub has no back side; the code on
the back stays readable) and drops the rest.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261117a1"
down_revision: str | Sequence[str] | None = "20261115a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SHEET_PLACEMENTS_OLD = "id_placement IN ('cell','margin','manual')"
_SHEET_PLACEMENTS_NEW = "id_placement IN ('cell','margin','manual','back_side')"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "backing_designs",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("key", sa.String, nullable=False, unique=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("page_size", sa.String, nullable=False),
        sa.Column("strips", sa.JSON, nullable=False),
        sa.Column("origin", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("page_size IN ('A4','Letter')", name="ck_backing_designs_page_size"),
        sa.CheckConstraint(
            "origin IN ('seed','custom','imported')", name="ck_backing_designs_origin"
        ),
    )
    op.create_table(
        "printer_tray_loading",
        sa.Column("printer_id", sa.Uuid, sa.ForeignKey("printers.id"), primary_key=True),
        sa.Column("tray_key", sa.String, primary_key=True),
        sa.Column("print_side", sa.String, nullable=False),
        sa.Column("leading_edge", sa.String, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String, nullable=True),
        sa.CheckConstraint(
            "print_side IN ('up','down')", name="ck_printer_tray_loading_print_side"
        ),
        sa.CheckConstraint(
            "leading_edge IN ('top','bottom')", name="ck_printer_tray_loading_leading_edge"
        ),
    )
    with op.batch_alter_table("sheet_types") as batch:
        batch.add_column(
            sa.Column("id_placement", sa.String, nullable=False, server_default="auto")
        )
        batch.add_column(sa.Column("id_cell", sa.Integer, nullable=True))
        batch.add_column(sa.Column("backing_design_id", sa.Uuid, nullable=True))
        batch.create_foreign_key(
            "fk_sheet_types_backing_design_id", "backing_designs", ["backing_design_id"], ["id"]
        )
        batch.create_check_constraint(
            "ck_sheet_types_id_placement", "id_placement IN ('auto','margin','back_side','cell')"
        )
    # SQLite cannot alter a CHECK in place: ``recreate="always"`` copies the table with the
    # widened constraint.
    with op.batch_alter_table("sheets", recreate="always") as batch:
        batch.add_column(sa.Column("id_cell_no", sa.Integer, nullable=True))
        batch.drop_constraint("ck_sheets_id_placement", type_="check")
        batch.create_check_constraint("ck_sheets_id_placement", _SHEET_PLACEMENTS_NEW)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("UPDATE sheets SET id_placement = 'manual' WHERE id_placement = 'back_side'")
    with op.batch_alter_table("sheets", recreate="always") as batch:
        batch.drop_constraint("ck_sheets_id_placement", type_="check")
        batch.create_check_constraint("ck_sheets_id_placement", _SHEET_PLACEMENTS_OLD)
        batch.drop_column("id_cell_no")
    with op.batch_alter_table("sheet_types") as batch:
        batch.drop_constraint("ck_sheet_types_id_placement", type_="check")
        batch.drop_constraint("fk_sheet_types_backing_design_id", type_="foreignkey")
        batch.drop_column("backing_design_id")
        batch.drop_column("id_cell")
        batch.drop_column("id_placement")
    op.drop_table("printer_tray_loading")
    op.drop_table("backing_designs")
