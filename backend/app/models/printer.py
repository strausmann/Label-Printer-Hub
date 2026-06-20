"""SQLModel table definitions für Printer-Entities und PrinterAudit-Protokoll."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String
from sqlmodel import Column, Field, SQLModel


class Printer(SQLModel, table=True):
    __tablename__ = "printers"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(index=True, unique=True)
    slug: str = Field(
        default="",
        index=True,
        unique=True,
        description="Stable URL-safe identifier (e.g., 'brother-p750w'). "
        "Defaults to slugified name on init.",
    )
    model: str
    backend: str
    connection: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    enabled: bool = Field(default=True)
    queue_timeout_s: int = Field(
        default=30,
        sa_column=Column(Integer(), nullable=False, server_default="30"),
        description="Sekunden bis ein Druckjob in der Queue als Timeout gilt.",
    )
    cut_defaults_half_cut: bool = Field(
        default=False,
        sa_column=Column(Boolean(), nullable=False, server_default="0"),
        description="Standard-Schnittmodus: True = halber Schnitt, False = voller Schnitt.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            onupdate=lambda: datetime.now(UTC),
        ),
    )


class PrinterAudit(SQLModel, table=True):
    """Audit-Log für Drucker-Änderungen (create, update, disable, enable).

    Kein FK auf printers — Soft-Delete behält Printer-Rows. Der printer_id-Wert
    verweist logisch auf die Drucker-ID, wird aber nicht via DB-Constraint
    durchgesetzt damit Audit-Logs nach Printer-Löschung erhalten bleiben.
    """

    __tablename__ = "printers_audit"
    __table_args__ = (
        Index("idx_printers_audit_printer_id", "printer_id"),
        Index("idx_printers_audit_created_at_desc", "created_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    printer_id: UUID = Field(nullable=False)
    slug: str = Field(sa_column=Column(String(255), nullable=False))
    action: str = Field(
        sa_column=Column(String(50), nullable=False),
        description="Aktionstyp: create | update | disable | enable",
    )
    before_json: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    after_json: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    updated_by: str = Field(sa_column=Column(String(255), nullable=False))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
