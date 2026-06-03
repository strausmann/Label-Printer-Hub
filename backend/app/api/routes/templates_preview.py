"""Phase 1i Sub-Task A+D: Preview-API für Templates.

A: GET /api/templates/{key}/preview.png — Bitmap (Diagnose-Tool, 1:1 wie an Drucker)
D: GET /api/templates/{key}/preview.svg — SVG (Live-Preview, Phase 1i D)

R3-Drift-Behebung #5: LabelData.source_app ist Pflichtfeld — kein Default.
Setzen wir auf "preview" für alle Preview-Aufrufe.
"""

from __future__ import annotations

import io

from fastapi import APIRouter, HTTPException, Query, Response

from app.schemas.label_data import LabelData
from app.services.label_renderer import LabelRenderer
from app.services.template_loader import TemplateLoader, TemplateNotFoundError

router = APIRouter(prefix="/api/templates", tags=["templates-preview"])


def _resolve_sample(
    template_definition: dict[str, object],
    primary_id: str | None,
    title: str | None,
    qr_payload: str | None,
) -> dict[str, object]:
    """Merge query-params über template.preview_sample (Query gewinnt)."""
    sample = dict(template_definition.get("preview_sample") or {})
    if primary_id is not None:
        sample["primary_id"] = primary_id
    if title is not None:
        sample["title"] = title
    if qr_payload is not None:
        sample["qr_payload"] = qr_payload
    sample.setdefault("title", "preview")
    sample.setdefault("primary_id", "PREVIEW")
    sample.setdefault("qr_payload", "https://hangar.example/preview")
    return sample


@router.get("/{key}/preview-png", response_class=Response)
def preview_png(
    key: str,
    primary_id: str | None = Query(default=None),
    title: str | None = Query(default=None),
    qr_payload: str | None = Query(default=None),
) -> Response:
    """Bitmap-Preview 1:1 wie an den Drucker geht (Diagnose-Tool)."""
    try:
        template = TemplateLoader.get(key)
    except TemplateNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"template not found: {key}") from e

    template_definition = template.model_dump()
    sample = _resolve_sample(template_definition, primary_id, title, qr_payload)

    renderer = LabelRenderer()
    # R3-Drift #5: source_app ist Pflichtfeld
    label_data = LabelData(**sample, source_app="preview")
    img = renderer.render(template, label_data)

    buf = io.BytesIO()
    img.convert("L").save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")
