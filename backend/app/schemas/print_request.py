"""Request schemas for POST /api/print + supporting models.

Phase 1k.1a: template_id and on_tape_mismatch removed; content_type added.
RawLabelData mirrors LabelData (minus source_app which is set server-side
to 'manual' for raw requests).
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.content_type import ContentType
from app.schemas.label_data_item import LabelDataItem


class PrintLookupRequest(BaseModel):
    """Resolve label data via an integration plugin."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    app: str
    identifier: str


class PrintOptions(BaseModel):
    """Per-print options — copies, cut behaviour, resolution."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    copies: int = Field(default=1, ge=1, le=10)
    auto_cut: bool = True
    high_resolution: bool = False
    half_cut: bool = False
    last_page: bool = True


class RawLabelData(BaseModel):
    """Raw label payload accepted when the client supplies data directly.

    Mirrors LabelData minus `source_app` (set server-side to 'manual').
    All content fields are optional — ContentType-specific validation
    happens in LayoutEngine._validate_data.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    title: str | None = None
    primary_id: str | None = None
    qr_payload: str | None = None
    secondary: tuple[str, ...] = ()
    items: tuple[LabelDataItem, ...] = ()


class PrintRequest(BaseModel):
    """POST /api/print body.

    Either `data` (RawLabelData) or `lookup` (PrintLookupRequest) is provided.
    Exactly one of the two must be present.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    content_type: ContentType
    """Semantic content type — drives LayoutEngine render dispatch."""

    options: PrintOptions = PrintOptions()
    """Per-print options (copies, cut behaviour, etc.)."""

    data: RawLabelData | None = None
    """Raw label data (preferred over lookup)."""

    lookup: PrintLookupRequest | None = None
    """Lookup-based label data (resolved via plugin)."""

    @model_validator(mode="after")
    def _exactly_one_data_source(self) -> Self:
        if (self.data is None) == (self.lookup is None):
            msg = "Exactly one of 'data' or 'lookup' must be set."
            raise ValueError(msg)
        return self
