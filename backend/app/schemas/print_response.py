"""Response schema for POST /api/v1/print."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class PrintJobResponse(BaseModel):
    """POST /api/v1/print 202 body — queue accepted."""

    model_config = ConfigDict(frozen=True)
    job_id: str
    status: Literal["queued"]
