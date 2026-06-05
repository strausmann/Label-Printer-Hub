"""SQLModel table definition for Job entities and JobState enum."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, Index, String
from sqlmodel import Column, Field, SQLModel


class JobState(StrEnum):
    QUEUED = "queued"
    PRINTING = "printing"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    FAILED_RESTART = "failed_restart"


class Job(SQLModel, table=True):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_state", "state"),
        Index("ix_jobs_api_key_id", "api_key_id"),
        CheckConstraint(
            f"state IN ({','.join(repr(s.value) for s in JobState)})",
            name="ck_jobs_state",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    printer_id: UUID = Field(foreign_key="printers.id")
    template_key: str | None = Field(default=None)  # nullable since Phase 1k.1a (Task 15); Alembic migration in Task 22
    state: str = Field(default=JobState.QUEUED.value)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    result: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    error: str | None = None
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
    started_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    finished_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    # Phase 7c: audit trail — which API key submitted this job and from where.
    # Both nullable so historical pre-7c jobs retain integrity (no backfill).
    api_key_id: UUID | None = Field(default=None, nullable=True)
    source_ip: str | None = Field(
        default=None,
        sa_column=Column(String, nullable=True),
    )
