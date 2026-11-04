"""SQLModel table definition for Preset entities.

Phase 1k.1a (Task 25): template_id foreign key removed — the templates table
and Template model were deleted in Phase 1k.1a. Presets are now independent
of templates (template_id column dropped via migration
20260605_phase1k1a_drop_preset_template_id).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime
from sqlmodel import Column, Field, SQLModel


class Preset(SQLModel, table=True):
    __tablename__ = "presets"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str
    content_type: str = Field(
        default="qr_three_lines",
        description="Semantischer ContentType (siehe app.schemas.content_type.ContentType).",
    )
    tape_mm: int = Field(
        default=12,
        description="Ziel-Bandbreite in mm (muss in TAPE_GEOMETRY existieren).",
    )
    printer_id: UUID | None = Field(default=None, foreign_key="printers.id")
    field_values: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
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
