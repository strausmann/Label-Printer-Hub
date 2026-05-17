"""REST endpoint for the Templates aggregate (Phase 6a Task 2).

Single read-only endpoint — template CRUD is out of scope for Phase 6a.

Routes
------
GET /api/templates?app=<optional> — list all templates, optionally filtered
    by integration app (snipeit, grocy, spoolman, …)

References:
    docs/superpowers/specs/2026-05-16-phase6a-rest-api-design.md — Templates section
    docs/superpowers/plans/2026-05-16-phase6a-rest-api.md — Task 2
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_read
from app.db.session import get_session
from app.repositories import templates as templates_repo
from app.schemas.template_read import TemplateRead

router = APIRouter(prefix="/api/templates", tags=["templates"])

# Type alias for the session dependency
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ReadAuthDep = Annotated[AuthContext, Depends(require_read)]


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
    _auth: ReadAuthDep,
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
