"""App-agnostic label data passed from lookup-clients to the LayoutEngine.

LabelData is what a `*_client.lookup(id)` call produces. It is the
serialisable view of a real-world entity (Snipe-IT asset, Grocy product,
Spoolman spool, Hangar location) condensed into the minimal set of fields
a label may need: an optional title, an optional identifier, an optional
QR payload, optional secondary lines, and a source-app tag.

Phase 1k.1a: All content fields are optional because ContentType selects
which fields are required for a given render call. The LayoutEngine
validates per-ContentType requirements in `_validate_data()` and raises
`ContentTypeDataMismatchError` if the required fields are missing.

Only `source_app` remains required — it is used for downstream routing,
logging, and metrics independent of the chosen ContentType.

Layout, font, geometry, and tape-fit decisions live in TapeGeometry +
LayoutEngine, NOT here.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.schemas.label_data_item import LabelDataItem


class LabelData(BaseModel):
    """Immutable, app-agnostic label payload."""

    model_config = ConfigDict(frozen=True)

    source_app: str
    """Source application tag (e.g. 'snipeit', 'grocy', 'spoolman', 'hangar', 'manual')."""

    title: str | None = None
    """Optional title; required by qr_two_lines, qr_three_lines, text_two_lines."""

    primary_id: str | None = None
    """Optional primary identifier.

    Required by qr_one_line, *_two_lines, *_three_lines, text_one_line,
    qr_with_listing (header).
    """

    qr_payload: str | None = None
    """Optional URL/payload for the QR code; required by qr_only, qr_*_line(s), qr_with_listing."""

    secondary: tuple[str, ...] = ()
    """Optional additional text lines; first entry rendered by qr_three_lines."""

    items: tuple[LabelDataItem, ...] = ()
    """Child items for qr_with_listing aggregation labels (Kallax-Regal-Uebersicht etc.)."""
