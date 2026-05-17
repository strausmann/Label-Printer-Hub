"""SQLModel table definition for the per-printer ESC i S status block cache."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, LargeBinary
from sqlmodel import Column, Field, SQLModel


class PrinterStatusCache(SQLModel, table=True):
    __tablename__ = "printer_status_cache"

    printer_id: UUID = Field(primary_key=True, foreign_key="printers.id")
    raw_block: bytes | None = Field(default=None, sa_column=Column(LargeBinary))
    parsed: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    captured_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            onupdate=lambda: datetime.now(UTC),
        ),
    )
