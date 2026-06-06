"""Single child entry for qr_with_listing aggregation labels."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class LabelDataItem(BaseModel):
    """One row in a qr_with_listing label (e.g. Kallax-Regal-Uebersicht)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item: str
    """Display text for this child (e.g. 'A — Schrauben')."""

    qr_payload: str | None = None
    """Optional per-child QR payload (reserved; not rendered in 1k.1a)."""
