"""Response schemas for POST /api/v1/print and the legacy job status body."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.printer_backends.snmp_helper import LiveStatus
from app.services.job_lifecycle import JobState


class PrintJobResponse(BaseModel):
    """POST /api/v1/print 202 body — queue accepted."""

    model_config = ConfigDict(frozen=True)
    job_id: str
    status: Literal["queued"]


class PrintJobStatusResponse(BaseModel):
    """Status body of the removed legacy ``GET /jobs/{job_id}``; no route returns it any more."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
    job_id: str
    status: JobState
    error_code: str | None = None
    error_message: str | None = None
    error_detail: dict[str, Any] | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # Populated only when status == PRINTING; route handler fetches live SNMP.
    live: LiveStatus | None = None
