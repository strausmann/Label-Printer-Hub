"""SQLModel table definition for Template entities."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, CheckConstraint
from sqlmodel import Column, Field, SQLModel


class Template(SQLModel, table=True):
    __tablename__ = "templates"
    __table_args__ = (CheckConstraint("source IN ('seed', 'user')", name="ck_templates_source"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    key: str = Field(index=True, unique=True)
    name: str
    app: str | None = None
    printer_model: str
    tape_width_mm: int
    schema_version: int = Field(default=1)
    definition: dict = Field(default_factory=dict, sa_column=Column(JSON))
    source: str = Field(default="user")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column_kwargs={"onupdate": lambda: datetime.now(UTC)},
    )
