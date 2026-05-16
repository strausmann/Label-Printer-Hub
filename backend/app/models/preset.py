"""SQLModel table definition for Preset entities."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


class Preset(SQLModel, table=True):
    __tablename__ = "presets"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str
    printer_id: UUID | None = Field(default=None, foreign_key="printers.id")
    template_id: UUID = Field(foreign_key="templates.id")
    field_values: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column_kwargs={"onupdate": lambda: datetime.now(UTC)},
    )
