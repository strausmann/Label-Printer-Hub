"""Pydantic-Schemas für die Preset-CRUD-API (Phase 1k.3, Refs #104)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.content_type import ContentType


class PresetCreatePayload(BaseModel):
    """Body für POST /api/v1/presets."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    content_type: ContentType
    tape_mm: int = Field(ge=1)
    field_values: dict[str, Any] = Field(default_factory=dict)
    printer_id: UUID | None = None


class PresetUpdatePayload(BaseModel):
    """Body für PUT /api/v1/presets/{id} — PATCH-Semantik, alle Felder optional."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    content_type: ContentType | None = None
    tape_mm: int | None = Field(default=None, ge=1)
    field_values: dict[str, Any] | None = None
    printer_id: UUID | None = None


class PresetResponse(BaseModel):
    """Response-Darstellung eines Presets."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    content_type: ContentType
    tape_mm: int
    field_values: dict[str, Any]
    printer_id: UUID | None
    created_at: datetime
    updated_at: datetime
