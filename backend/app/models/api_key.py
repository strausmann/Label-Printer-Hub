"""SQLModel table definition for ApiKey — Phase 7c app-side authentication."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String
from sqlmodel import Column, Field, SQLModel


class ApiKey(SQLModel, table=True):
    __tablename__ = "api_keys"
    __table_args__ = (
        Index("ix_api_keys_name", "name"),
        Index("ix_api_keys_key_prefix", "key_prefix"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(sa_column=Column(String, nullable=False))
    key_hash: str = Field(sa_column=Column(String, nullable=False))
    key_prefix: str = Field(sa_column=Column(String, nullable=False))
    scopes: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    allowed_printer_ids: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    rate_limit_per_minute: int = Field(
        default=60,
        sa_column=Column(Integer, nullable=False),
    )
    enabled: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    last_used_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    last_used_ip: str | None = Field(
        default=None,
        sa_column=Column(String, nullable=True),
    )
    expires_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    notes: str | None = Field(
        default=None,
        sa_column=Column(String, nullable=True),
    )
