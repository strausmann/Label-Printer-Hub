"""SQLModel table definition for Job entities and JobState enum."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, Index, String, text
from sqlalchemy.types import TypeDecorator
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


def json_at(path: str) -> str:
    """``json_extract`` of ``path`` in a job's payload, ``NULL`` if the payload is not valid JSON.

    SQLite older than 3.45 (the production image has 3.40) raises "malformed JSON" on a text
    such as ``{"a": NaN}``, and an index over an unguarded expression would then fail to build
    and fail every later insert of such a row. ``json_valid`` is cheap; the guard keeps an
    invalid payload from ever breaking the index or a query (run-12 R12-1).
    """
    return f"CASE WHEN json_valid(payload) THEN json_extract(payload, '{path}') END"


# The sheet a stored page payload belongs to, as an expression. The same text builds the index
# ``ix_jobs_page_sheet`` (migration 20261108a1), so SQLite finds a sheet's jobs by index and
# never parses the payloads of other sheets' jobs (R11-1): one literal, not a bound parameter,
# or the index cannot match.
PAGE_SHEET_EXPR = json_at("$.detail.sheet_id")


class FiniteJSON(TypeDecorator[Any]):
    """A JSON column that refuses ``NaN`` and ``Infinity``.

    Python writes them as bare words, which is not JSON: SQLite older than 3.45 rejects such a
    document in every JSON function (run-12 R12-1). The API refuses non-finite numbers at the
    boundary; this is the second guard, at the one place a payload is stored.
    """

    impl = JSON
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Any:  # noqa: ARG002
        if value is not None:
            json.dumps(value, allow_nan=False)  # ValueError for a non-finite number
        return value


class Job(SQLModel, table=True):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_state", "state"),
        Index("ix_jobs_api_key_id", "api_key_id"),
        # The sheet of a page job, for the in-flight rules (R11-1). Queries use the same
        # ``PAGE_SHEET_EXPR`` text or SQLite does not use the index.
        Index("ix_jobs_page_sheet", text(PAGE_SHEET_EXPR)),
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
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(FiniteJSON))
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
