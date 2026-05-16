"""API read schema for Template entities (Phase 6a).

``TemplateRead`` maps the ``templates`` DB table to a JSON-serialisable
Pydantic model for the REST API.  It is distinct from ``TemplateSchema``
(the renderer's layout descriptor) — the DB row carries additional fields
(``id``, ``source``, ``created_at``, etc.) that the renderer does not need.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TemplateRead(BaseModel):
    """Serialised view of a Template DB row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key: str
    name: str
    app: str | None
    printer_model: str
    tape_width_mm: int
    schema_version: int
    definition: dict[str, Any]
    source: str
    created_at: datetime
    updated_at: datetime
