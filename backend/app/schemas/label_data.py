"""App-agnostic label data passed from lookup-clients to the LabelRenderer.

LabelData is what a `*_client.lookup(id)` call produces. It is the
serialisable view of a real-world entity (Snipe-IT asset, Grocy product,
Spoolman spool) condensed into the minimal set of fields a label needs:
a title, an identifier to print, a QR-encodable URL, optional secondary
lines, and a source-app tag for downstream routing.

Layout, font, geometry, and tape-fit decisions live on the LabelRenderer
side — they are NOT in this model.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LabelData(BaseModel):
    """Immutable, app-agnostic label payload."""

    model_config = ConfigDict(frozen=True)

    title: str
    primary_id: str
    qr_payload: str
    source_app: str
    secondary: list[str] = Field(default_factory=list)
