"""API read schema for Job entities (Phase 6a).

``JobRead`` maps the ``jobs`` DB table to a JSON-serialisable Pydantic model
for the REST API.  It intentionally exposes all fields — consumers (Phase 7 UI,
webhooks) need the full state history to render job timelines.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class JobRead(BaseModel):
    """Serialised view of a Job DB row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    printer_id: UUID
    template_key: str
    state: str  # 'queued' | 'printing' | 'done' | 'failed' | 'cancelled' | 'failed_restart'
    payload: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
