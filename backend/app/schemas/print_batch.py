# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Pydantic-Schemas für POST /api/v1/print/{slug_or_uuid}/batch."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.print_request import PrintRequest


class BatchRequest(BaseModel):
    """Top-level POST /api/v1/print/{slug_or_uuid}/batch body."""

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
    label_job_ids: list[str] = Field(
        default_factory=list,
        description=(
            "The job of every label (copies included) in print order (#277). The labels are "
            "printed in sub-jobs of `sub_job_size`; each further sub-job waits for "
            "`POST /api/v1/batches/{batch_id}/continue`."
        ),
    )
    sub_job_size: int = Field(description="Labels per sub-job (#277).")
    # R2-3: errors field removed — route never populates it after Task-17 refactor.
    # BatchError class retained for potential future use (pre-validation per item).
