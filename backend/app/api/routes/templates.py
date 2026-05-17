"""REST endpoints for the Templates aggregate (Phase 6a Task 2 + Bug-3 fix).

Routes
------
GET  /api/templates?app=<optional>         — list all templates, optionally
    filtered by integration app (snipeit, grocy, spoolman, …)
POST /api/render/preview?key=<template_key> — render a sample label as PNG

The preview endpoint is used by the frontend template-detail page to show a
rendered preview image. It builds app-appropriate sample data so the preview
looks representative without requiring a real integration entity.

References:
    docs/superpowers/specs/2026-05-16-phase6a-rest-api-design.md — Templates section
    docs/superpowers/plans/2026-05-16-phase6a-rest-api.md — Task 2
"""

from __future__ import annotations

import io
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.repositories import templates as templates_repo
from app.schemas.label_data import LabelData
from app.schemas.template import TemplateSchema
from app.schemas.template_read import TemplateRead
from app.services.label_renderer import LabelRenderer

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/templates", tags=["templates"])

# Separate router for /api/render so the preview endpoint can live here while
# the prefix keeps it at /api/render/preview (not /api/templates/render/preview).
render_router = APIRouter(prefix="/api/render", tags=["templates"])

# Type alias for the session dependency
SessionDep = Annotated[AsyncSession, Depends(get_session)]

# ---------------------------------------------------------------------------
# Sample data per app — used by the preview renderer to produce representative
# output without requiring a real integration entity.
# ---------------------------------------------------------------------------

_SAMPLE_DATA: dict[str | None, LabelData] = {
    "snipeit": LabelData(
        primary_id="ASSET-001",
        title="Sample Laptop",
        qr_payload="https://example.com/snipeit/hardware/1",
        source_app="snipeit",
    ),
    "grocy": LabelData(
        primary_id="12345",
        title="Sample Product",
        qr_payload="https://example.com/grocy/product/12345",
        source_app="grocy",
    ),
    "spoolman": LabelData(
        primary_id="Spool 7",
        title="PLA Black 1kg",
        qr_payload="https://example.com/spoolman/spool/7",
        source_app="spoolman",
    ),
}

_GENERIC_SAMPLE = LabelData(
    primary_id="SAMPLE-001",
    title="Sample Label",
    qr_payload="https://example.com/sample/001",
    source_app="generic",
)


@render_router.post(
    "/preview",
    response_class=Response,
    responses={
        200: {
            "content": {"image/png": {"schema": {"type": "string", "format": "binary"}}},
            "description": "PNG image of the rendered sample label",
        }
    },
    summary="Render a template preview as PNG",
    description=(
        "Renders the named template with app-appropriate sample data and returns "
        "a PNG image. Used by the frontend template-detail page. "
        "Returns 404 if the template key is not registered."
    ),
)
async def render_preview(
    session: SessionDep,
    key: str = Query(description="Template key, e.g. 'snipeit/asset'"),
) -> Response:
    """Render a sample preview PNG for the given template key."""
    template_row = await templates_repo.get_by_key(session, key)
    if template_row is None:
        raise HTTPException(status_code=404, detail=f"template {key!r} not found")

    # Reconstruct TemplateSchema from the DB row — the definition column stores
    # the TemplateSchema field values. Supplement missing fields from the row's
    # top-level columns (id→key, tape_mm→tape_width_mm, etc.) so that rows
    # created before the definition was normalised can still render.
    definition = dict(template_row.definition)
    definition.setdefault("id", template_row.key)
    definition.setdefault("name", template_row.name)
    definition.setdefault("app", template_row.app)
    definition.setdefault("tape_mm", template_row.tape_width_mm)
    definition.setdefault("schema_version", template_row.schema_version)
    definition.setdefault("elements", [])

    try:
        template_schema = TemplateSchema(**definition)
    except Exception as exc:
        _log.warning("render_preview: invalid definition for key=%r: %s", key, exc)
        raise HTTPException(status_code=422, detail=f"invalid template definition: {exc}") from exc

    sample_data = _SAMPLE_DATA.get(template_row.app, _GENERIC_SAMPLE)

    renderer = LabelRenderer()
    try:
        img = renderer.render(template_schema, sample_data)
    except ValueError as exc:
        _log.warning("render_preview: render failed for key=%r: %s", key, exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Convert PIL image to PNG bytes
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@router.get(
    "",
    response_model=list[TemplateRead],
    summary="List all templates",
    description=(
        "Returns every registered template (seed + user).  "
        "Pass ``?app=<name>`` to filter to a specific integration "
        "(e.g. ``snipeit``, ``grocy``, ``spoolman``).  "
        "When the query parameter is absent all templates are returned."
    ),
)
async def list_templates(
    session: SessionDep,
    app: str | None = Query(
        default=None,
        description="Filter by integration app (snipeit / grocy / spoolman / …)",
    ),
) -> list[TemplateRead]:
    """Return all templates, with an optional app-name filter."""
    rows = await templates_repo.list_all(session)
    if app is not None:
        rows = [r for r in rows if r.app == app]
    return [TemplateRead.model_validate(r, from_attributes=True) for r in rows]
