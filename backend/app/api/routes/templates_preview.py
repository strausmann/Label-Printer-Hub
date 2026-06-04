"""Phase 1i Sub-Task A+D: Preview-API für Templates.

A: GET /api/templates/{key}/preview-png — Bitmap (Diagnose-Tool, 1:1 wie an Drucker)
D: GET /api/templates/{key}/preview-svg — SVG (Live-Preview, Hub-Dashboard-Modal)

R3-Drift-Behebung #5: LabelData.source_app ist Pflichtfeld — kein Default.
Setzen wir auf "preview" für alle Preview-Aufrufe.
"""

from __future__ import annotations

import hashlib
import io
import json
from typing import cast

from fastapi import APIRouter, Header, HTTPException, Query, Response

from app.schemas.label_data import LabelData
from app.services.label_renderer import LabelRenderer
from app.services.svg_renderer import render_template_svg
from app.services.template_loader import TemplateLoader, TemplateNotFoundError

router = APIRouter(prefix="/api/templates", tags=["templates-preview"])


def _resolve_sample(
    template_definition: dict[str, object],
    primary_id: str | None,
    title: str | None,
    qr_payload: str | None,
) -> dict[str, object]:
    """Merge query-params über template.preview_sample (Query gewinnt)."""
    sample: dict[str, object] = dict(
        cast(dict[str, object], template_definition.get("preview_sample") or {})
    )
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


def _label_data_from_sample(sample: dict[str, object], source_app: str) -> LabelData:
    """Konstruiert LabelData aus dem sample-Dict mit expliziten Feldern.

    Vermeidet **dict[str, object] unpack (mypy: Argument 1 to LabelData incompatible).
    cast() ist safe weil _resolve_sample alle Felder als str setzt.
    """
    return LabelData(
        primary_id=cast(str, sample.get("primary_id", "PREVIEW")),
        title=cast(str, sample.get("title", "preview")),
        qr_payload=cast(str, sample.get("qr_payload", "https://hangar.example/preview")),
        secondary=cast(tuple[str, ...], sample.get("secondary", ())),
        source_app=source_app,
    )


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
    label_data = _label_data_from_sample(sample, source_app="preview")
    img = renderer.render(template, label_data)

    buf = io.BytesIO()
    img.convert("L").save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@router.get("/{key}/preview-svg", response_class=Response)
def preview_svg(
    key: str,
    primary_id: str | None = Query(default=None),
    title: str | None = Query(default=None),
    qr_payload: str | None = Query(default=None),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
) -> Response:
    """SVG-Preview für Hub-Dashboard-Modal und Hangar Print-Form.

    M3-Arch-Fix: ETag nur für Seed-Templates in Phase 1i (sample = stable).
    ETag = sha256(key + sorted-json(sample))[:16].
    """
    try:
        template = TemplateLoader.get(key)
    except TemplateNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"template not found: {key}") from e

    template_definition = template.model_dump()
    sample = _resolve_sample(template_definition, primary_id, title, qr_payload)

    # ETag aus template-key + sample-Inhalt (stabil für Seed-Templates)
    seed_id = f"{key}|{json.dumps(sample, sort_keys=True)}"
    etag = hashlib.sha256(seed_id.encode()).hexdigest()[:16]
    weak_etag = f'"{etag}"'

    if if_none_match is not None and if_none_match.strip('"') == etag:
        return Response(status_code=304, headers={"ETag": weak_etag})

    # R3-Drift #5: source_app ist Pflichtfeld
    label_data = _label_data_from_sample(sample, source_app="preview")

    # R4-A-C1+MA2-Fix: render_template_svg erwartet dicts — .model_dump() konvertiert
    svg_str = render_template_svg(
        template_definition=template.model_dump(),
        sample_data=label_data.model_dump(),
    )
    svg_bytes = svg_str.encode("utf-8") if isinstance(svg_str, str) else svg_str

    return Response(
        content=svg_bytes,
        media_type="image/svg+xml",
        headers={"ETag": weak_etag, "Cache-Control": "private, max-age=300"},
    )
