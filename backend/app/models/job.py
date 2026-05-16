"""SQLModel table definition for Job entities and JobState enum."""
from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Index, JSON
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
        CheckConstraint(
            f"state IN ({','.join(repr(s.value) for s in JobState)})",
            name="ck_jobs_state",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    printer_id: UUID = Field(foreign_key="printers.id")
    template_key: str  # snapshot string — survives template deletion
    state: str = Field(default=JobState.QUEUED.value)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    result: dict | None = Field(default=None, sa_column=Column(JSON))
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column_kwargs={"onupdate": lambda: datetime.now(UTC)},
    )
    started_at: datetime | None = None
    finished_at: datetime | None = None
