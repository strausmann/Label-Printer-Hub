"""SQLModel table für print_batches — Tracking-Aggregat für Batch-Druckaufträge."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime
from sqlmodel import Column, Field, SQLModel


class PrintBatch(SQLModel, table=True):
    __tablename__ = "print_batches"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    printer_id: UUID = Field(index=True, foreign_key="printers.id")
    job_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    created_by: str = Field(index=True, description="SSO-Email oder API-Key-ID")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
