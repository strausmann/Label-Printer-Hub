"""Pydantic-Schemas für POST /api/print/{slug_or_uuid}/batch."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.print_request import PrintRequest


class BatchRequest(BaseModel):
    """Top-level POST /api/print/{slug_or_uuid}/batch body."""

    model_config = ConfigDict(extra="forbid")
    items: Annotated[list[PrintRequest], Field(min_length=1, max_length=500)]
    # Phase 1i C-Fix (CA-2):
    printer_slug: str | None = Field(
        default=None,
        description="Optional: Slug des Ziel-Druckers (muss mit URL-Path übereinstimmen).",
    )
    half_cut_override: bool | None = Field(
        default=None,
        description=(
            "Override half_cut for all items in this batch. "
            "If the printer backend does not support half_cut (e.g. QL-Series), "
            "the value is forced to False and a warning is logged."
        ),
    )


class BatchError(BaseModel):
    """Pro-Item-Fehler in der Batch-Response."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    index: Annotated[int, Field(ge=0)]
    error_code: str
    error_message: str
    error_detail: dict[str, object] | None = None


class BatchResponse(BaseModel):
    """202 Response für erfolgreich akzeptierte Batch (auch wenn 0 Items queued)."""

    model_config = ConfigDict(extra="forbid")
    batch_id: UUID
    printer_id: UUID
    queued_at: str  # ISO-8601 mit Z-Suffix
    job_ids: list[str]
    errors: list[BatchError] = Field(default_factory=list)
