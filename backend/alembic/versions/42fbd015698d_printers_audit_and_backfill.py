"""printers_audit_and_backfill

Issue #124: Schema-Erweiterung der printers-Tabelle um queue_timeout_s und
cut_defaults_half_cut, neue printers_audit-Tabelle für Änderungsprotokoll sowie
Backfill des connection.snmp-Blocks für Bestandsdrucker.

Revision ID: 42fbd015698d
Revises: 20260605b2c3d4e5
Create Date: 2026-06-20

"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "42fbd015698d"
down_revision: str | Sequence[str] | None = "20260605b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _backfill_snmp(bind: sa.engine.Connection) -> None:
    """Befüllt connection.snmp für Bestandsdrucker ohne SNMP-Konfiguration.

    Pro printers-Row: wenn connection.snmp fehlt UND connection.host vorhanden,
    wird snmp = {"discover": false, "community": "public"} gesetzt.

    Schutzklauseln:
    - NULL connection wird übersprungen
    - Fehlendes host-Feld wird übersprungen
    - Bereits vorhandenes snmp-Feld bleibt unverändert (idempotent)

    Diese Funktion ist als top-level Funktion definiert damit sie direkt
    via ``await conn.run_sync(mig._backfill_snmp)`` in Tests testbar ist.
    """
    rows = bind.execute(sa.text("SELECT id, connection FROM printers")).all()
    for row in rows:
        pid, conn_raw = row[0], row[1]
        if conn_raw is None:
            continue
        conn_json: dict = json.loads(conn_raw) if isinstance(conn_raw, str) else conn_raw
        if "host" not in conn_json:
            continue
        if "snmp" in conn_json:
            continue  # idempotent — bereits konfiguriert
        conn_json["snmp"] = {"discover": False, "community": "public"}
        bind.execute(
            sa.text("UPDATE printers SET connection = :c WHERE id = :pid"),
            {"c": json.dumps(conn_json), "pid": pid},
        )


def upgrade() -> None:
    """Schema-Erweiterung: neue Spalten auf printers + printers_audit-Tabelle + Backfill."""
    # 1. Neue Spalten auf printers (batch_alter_table für SQLite-Kompatibilität)
    with op.batch_alter_table("printers", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "queue_timeout_s",
                sa.Integer(),
                nullable=False,
                server_default="30",
            )
        )
        batch_op.add_column(
            sa.Column(
                "cut_defaults_half_cut",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            )
        )

    # 2. printers_audit-Tabelle (kein FK auf printers — Soft-Delete behält Rows)
    op.create_table(
        "printers_audit",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("printer_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("before_json", sa.JSON(), nullable=True),
        sa.Column("after_json", sa.JSON(), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_printers_audit_printer_id",
        "printers_audit",
        ["printer_id"],
    )
    op.create_index(
        "idx_printers_audit_created_at_desc",
        "printers_audit",
        [sa.text("created_at DESC")],
    )

    # 3. Backfill connection.snmp für Bestandsdrucker
    bind = op.get_bind()
    _backfill_snmp(bind)


def downgrade() -> None:
    """Downgrade ist ein no-op.

    Die neuen Spalten und die printers_audit-Tabelle können nicht sicher
    zurückgerollt werden ohne Datenverlust (Audit-Logs sind produktiv relevant).
    Der SNMP-Backfill kann ebenfalls nicht rückgängig gemacht werden ohne
    Originalzustand zu kennen. Downgrade wird daher nicht unterstützt.
    """
    pass
