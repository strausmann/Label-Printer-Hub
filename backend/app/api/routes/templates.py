"""REST endpoints for the Templates aggregate (Phase 6a Task 2 + Bug-3 fix).

Routes
------
GET  /api/templates?app=<optional>         — list all templates, optionally
    filtered by integration app (snipeit, grocy, spoolman, …)
POST /api/render/preview?key=<template_key> — render a sample label as PNG

The preview endpoint is used by the frontend template-detail page to show a
rendered preview image. Sample values are sourced from the template's own
``preview_sample`` block in its definition — the route does NOT fabricate
sample data. Templates without ``preview_sample`` return HTTP 422.

References:
    docs/superpowers/specs/2026-05-16-phase6a-rest-api-design.md — Templates section
    docs/superpowers/plans/2026-05-16-phase6a-rest-api.md — Task 2
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
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


def _build_label_data(
    template_key: str,
    template_app: str | None,
    preview_sample: dict[str, Any],
) -> LabelData:
    """Build a LabelData from a template's preview_sample dict.

    The template is responsible for declaring values for every ``field``
    and ``data_field`` its elements reference. Missing values raise
    HTTPException 422.
    """
    try:
        # source_app is filled from the template's own ``app`` field — falls
        # back to "generic" for templates without an integration.
        return LabelData(
            primary_id=str(preview_sample.get("primary_id", "")),
            title=str(preview_sample.get("title", "")),
            qr_payload=str(preview_sample.get("qr_payload", "")),
            source_app=template_app or "generic",
            secondary=tuple(preview_sample.get("secondary", ()) or ()),
        )
    except Exception as exc:  # ValidationError or coercion error
        raise HTTPException(
            status_code=422,
            detail=(f"Template {template_key!r} has an invalid preview_sample block: {exc}"),
        ) from exc


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
        "Renders the named template with the sample values declared in the "
        "template's own ``preview_sample`` block and returns a PNG image. "
        "Returns 404 if the template key is not registered. "
        "Returns 422 if the template has no ``preview_sample`` block."
    ),
)
async def render_preview(
    request: Request,
    session: SessionDep,
    key: str = Query(description="Template key, e.g. 'snipeit-12mm'"),
) -> Response:
    """Render a sample preview PNG for the given template key.

    Sample values are taken from the template's own ``preview_sample`` block
    (in ``template.definition``). Templates that do not declare one return
    HTTP 422 with a clear error message — the route does NOT fabricate
    fallback sample data.

    The LabelRenderer is reused from ``app.state.label_renderer`` (wired by
    the lifespan) to avoid per-request font-loading overhead. The CPU-bound
    render + PNG encode is offloaded to ``asyncio.to_thread`` so it does not
    block the event loop.
    """
    template_row = await templates_repo.get_by_key(session, key)
    if template_row is None:
        raise HTTPException(status_code=404, detail=f"template {key!r} not found")

    definition = dict(template_row.definition)

    # The preview_sample block lives in the template definition. Without it
    # the template cannot be previewed — we refuse to guess on its behalf.
    preview_sample = definition.get("preview_sample")
    if not preview_sample or not isinstance(preview_sample, dict):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Template {template_row.key!r} has no preview_sample in its "
                "definition. Add a 'preview_sample' block to the template YAML "
                "to enable previews."
            ),
        )

    # Reconstruct TemplateSchema from the DB row — the definition column stores
    # the TemplateSchema field values. Supplement missing fields from the row's
    # top-level columns (id→key, tape_mm→tape_width_mm, etc.) so that rows
    # created before the definition was normalised can still render.
    # ``preview_sample`` is not a TemplateSchema field — strip it before
    # passing to the schema constructor.
    schema_dict = {k: v for k, v in definition.items() if k != "preview_sample"}
    schema_dict.setdefault("id", template_row.key)
    schema_dict.setdefault("name", template_row.name)
    schema_dict.setdefault("app", template_row.app)
    schema_dict.setdefault("tape_mm", template_row.tape_width_mm)
    schema_dict.setdefault("schema_version", template_row.schema_version)
    schema_dict.setdefault("elements", [])

    try:
        template_schema = TemplateSchema(**schema_dict)
    except Exception as exc:
        # Log the sanitised key from the DB row (trusted), NOT the raw query
        # parameter, to prevent log injection via crafted key values.
        _log.warning("render_preview: invalid definition for key=%r: %s", template_row.key, exc)
        raise HTTPException(status_code=422, detail=f"invalid template definition: {exc}") from exc

    sample_data = _build_label_data(template_row.key, template_row.app, preview_sample)

    # Reuse the shared renderer from app.state (avoids per-request font-loading).
    # Fall back to a fresh instance when running outside a full lifespan
    # (e.g. unit tests that don't wire app.state).
    renderer: LabelRenderer = getattr(request.app.state, "label_renderer", None) or LabelRenderer()

    def _render_and_encode() -> bytes:
        """CPU-bound render + PNG encode — runs in a thread pool."""
        try:
            img = renderer.render(template_schema, sample_data)
        except ValueError as exc:
            # Log the sanitised key from the DB row (trusted), NOT the raw query
            # parameter, to prevent log injection via crafted key values.
            _log.warning("render_preview: render failed for key=%r: %s", template_row.key, exc)
            raise
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    try:
        png_bytes = await asyncio.to_thread(_render_and_encode)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return Response(content=png_bytes, media_type="image/png")


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
