"""SQLModel table definition for Job entities and JobState enum."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, Index, String, text
from sqlmodel import Column, Field, SQLModel


def is_page_payload(payload: dict[str, Any] | None) -> bool:
    """True for a stored page-job payload (it names a ``kind``); tape payloads have none.

    The definition of "is a page job" for *stored payloads*: the job stores, the repository
    and the retry route ask this function. Other components key on what they hold instead:
    the in-memory queue on ``job.kind``, capabilities and calibration on
    ``printer.backend == "ipp"``, and the status route on the cache row's ``kind``.
    """
    return bool(payload) and "kind" in (payload or {})


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
        # The sheet of a page job, for the in-flight rules (R11-1). The text must equal
        # ``repositories.sheets.PAGE_SHEET_EXPR`` or SQLite does not use the index.
        Index("ix_jobs_page_sheet", text("json_extract(payload, '$.detail.sheet_id')")),
        CheckConstraint(
            f"state IN ({','.join(repr(s.value) for s in JobState)})",
            name="ck_jobs_state",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    printer_id: UUID = Field(foreign_key="printers.id")
    # nullable since Phase 1k.1a (Task 15); Alembic migration in Task 22
    template_key: str | None = Field(default=None)
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
