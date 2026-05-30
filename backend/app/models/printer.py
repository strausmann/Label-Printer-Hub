"""SQLModel table definition for Printer entities."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime
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
