"""Request schemas for POST /api/v1/print + supporting models.

Phase 1k.1a: template_id and on_tape_mismatch removed; content_type added.
RawLabelData mirrors LabelData (minus source_app which is set server-side
to 'manual' for raw requests).
"""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.content_type import ContentType
from app.schemas.label_data_item import LabelDataItem
from app.schemas.label_layout import LabelOrientation, QlLayoutPreset


class PrintLookupRequest(BaseModel):
    """Resolve label data via an integration plugin."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    app: str
    identifier: str


class PrintOptions(BaseModel):
    """Per-print options — copies, cut behaviour, resolution, layout."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    copies: int = Field(default=1, ge=1, le=10)
    auto_cut: bool = True
    high_resolution: bool = False
    half_cut: bool = False
    """Ignored by QL printers (they have a full cut only)."""
    last_page: bool = True
    orientation: LabelOrientation | None = None
    """``across`` or ``along`` (#258). Omitted: the printer's stored default for the loaded
    tape, else the tape default (62 mm across, every other width along). ``across`` on a tape
    without an across-width layout is refused with 409 ``unsupported_tape``. A batch prints
    with one orientation: items without one follow the item that names one; items naming
    different orientations are refused with 422 ``conflicting_orientation``."""
    layout_preset: QlLayoutPreset | None = None
    """QL 62 mm across-width preset (#258). Omitted: stored default, else ``compact``.
    Ignored for ``along``."""


QR_PAYLOAD_MAX = 512  # keeps a render's cost bounded; a scan URL is far shorter
RAW_TEXT_MAX = 512  # one raw text field (title, id, a secondary line, a listing row)
RAW_SECONDARY_MAX = 10  # secondary lines per label
RAW_LISTING_MAX = 100  # listing rows per label

_RawText = Annotated[str, Field(max_length=RAW_TEXT_MAX)]


class RawListingItem(LabelDataItem):
    """One listing row of raw label data, with bounded text."""

    item: _RawText
    qr_payload: str | None = Field(default=None, max_length=QR_PAYLOAD_MAX)


class RawLabelData(BaseModel):
    """Raw label payload accepted when the client supplies data directly.

    Mirrors LabelData minus `source_app` (set server-side to 'manual').
    All content fields are optional — ContentType-specific validation
    happens in LayoutEngine._validate_data.

    Every free text is bounded at the request (the same caps as sheet items): 512 characters
    per text and QR payload, at most 10 ``secondary`` lines and 100 ``items``. A label shows
    far less; the renderer shortens what does not fit (#258 security review).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    title: _RawText | None = None
    primary_id: _RawText | None = None
    qr_payload: str | None = Field(default=None, max_length=QR_PAYLOAD_MAX)
    secondary: tuple[_RawText, ...] = Field(default=(), max_length=RAW_SECONDARY_MAX)
    items: tuple[RawListingItem, ...] = Field(default=(), max_length=RAW_LISTING_MAX)


class PrintRequest(BaseModel):
    """POST /api/v1/print body.

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
