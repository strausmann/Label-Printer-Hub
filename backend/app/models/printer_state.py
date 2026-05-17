"""SQLModel table definition for per-printer pause/resume state."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel


class PrinterState(SQLModel, table=True):
    __tablename__ = "printer_state"

    printer_id: UUID = Field(primary_key=True, foreign_key="printers.id")
    paused: bool = Field(default=False)
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            onupdate=lambda: datetime.now(UTC),
        ),
    )
