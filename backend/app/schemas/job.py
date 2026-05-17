"""API read schema for Job entities (Phase 6a).

``JobRead`` maps the ``jobs`` DB table to a JSON-serialisable Pydantic model
for the REST API.  It intentionally exposes all fields — consumers (Phase 7 UI,
webhooks) need the full state history to render job timelines.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_serializer

from app.schemas._datetime import serialize_datetime_utc


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

    @field_serializer("created_at", "updated_at")
    def _serialise_datetimes(self, dt: datetime, _info: object) -> str:
        return serialize_datetime_utc(dt, _info)

    @field_serializer("started_at")
    def _serialise_started_at(self, dt: datetime | None, _info: object) -> str | None:
        return serialize_datetime_utc(dt, _info) if dt is not None else None

    @field_serializer("finished_at")
    def _serialise_finished_at(self, dt: datetime | None, _info: object) -> str | None:
        return serialize_datetime_utc(dt, _info) if dt is not None else None
