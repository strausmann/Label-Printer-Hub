# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""REST endpoint for the Lookup aggregate (Phase 6a Task 4).

Routes
------
GET /api/v1/lookup/{app}/{id} — resolve an integration entity and return LookupResult
GET /api/v1/lookup/grocy/batteries/{id} — a few facts about one Grocy battery
GET /api/v1/lookup/grocy/chores/{id} — a few facts about one Grocy chore

Design notes
------------
This is a thin REST wrapper around ``AppLookupService.lookup()``.  The service
already exists (used by the print pipeline and the web app's item view) and does
all the heavy lifting.  The route's job is:

1. Validate ``app`` against the known-apps enum so FastAPI returns 422 for
   unsupported apps before even calling the service.
2. Delegate to the service.
3. Project the returned ``LabelData`` into a ``LookupResult``.

Auth
----
Read scope (a key or a signed-in browser session). The endpoint answers with data from the
connected apps, so it is not public; the QR landing paths only serve the app shell.

Error mapping
-------------
``AppLookupNotFoundError`` propagates to the global exception handler
registered in ``app.api.error_handlers`` which returns 404 ProblemDetail.

``UnknownAppError`` cannot be raised here because the ``app`` path parameter is
validated as a ``Literal`` — FastAPI returns 422 before the handler runs.

References:
    docs/superpowers/specs/2026-05-16-phase6a-rest-api-design.md — Lookup section
    docs/superpowers/plans/2026-05-16-phase6a-rest-api.md — Task 4
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path

from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_read
from app.schemas.grocy_object import GrocyBatteryResult, GrocyChoreResult
from app.schemas.label_data import LabelData
from app.schemas.lookup import LookupResult
from app.services.lookup_service import AppLookupService

router = APIRouter(prefix="/api/v1/lookup", tags=["lookup"])

ReadAuthDep = Annotated[AuthContext, Depends(require_read)]

# Dependency instance — shared across requests within a single process.
# AppLookupService is stateless (reads settings once at construction);
# constructing it at module level avoids per-request overhead.
_lookup_service = AppLookupService()

# A Grocy object id goes into an upstream URL path: digits only, so nothing else can reach it.
GrocyIdPath = Annotated[str, Path(pattern=r"^[0-9]{1,18}$", description="The numeric Grocy id")]

# Shared type alias for the app path parameter
AppLiteral = Literal["snipeit", "grocy", "spoolman"]


def _label_data_to_result(app: AppLiteral, entity_id: str, data: LabelData) -> LookupResult:
    """Project ``LabelData`` (internal) into ``LookupResult`` (API)."""
    extra: dict[str, object] = {}
    if data.secondary:
        extra["secondary"] = list(data.secondary)
    return LookupResult(
        app=app,
        id=entity_id,
        name=data.title,
        url=data.qr_payload,
        extra=extra,
    )


@router.get(
    "/{app}/{entity_id}",
    response_model=LookupResult,
    summary="Resolve an integration entity",
    description=(
        "Looks up an entity from the given integration app by its identifier.  "
        "``app`` must be one of ``snipeit``, ``grocy``, or ``spoolman`` — an "
        "unsupported value returns 422.  "
        "Returns 404 ProblemDetail when the entity does not exist in the "
        "integration's backend.  "
        "The ``url`` field is the deep-link to the entity in the integration's "
        "own web UI, suitable for embedding in a QR code or label."
    ),
)
async def lookup(
    app: AppLiteral,
    entity_id: str,
    _auth: ReadAuthDep,
) -> LookupResult:
    """Resolve ``entity_id`` via the integration named ``app``."""
    # AppLookupNotFoundError propagates to the global handler → 404 ProblemDetail.
    # All other errors (network, 5xx) propagate as HTTP 500.
    data = await _lookup_service.lookup(app, entity_id)
    return _label_data_to_result(app, entity_id, data)


@router.get(
    "/grocy/batteries/{battery_id}",
    response_model=GrocyBatteryResult,
    summary="Read a Grocy battery",
    description=(
        "Name, description, last and next charging and the number of charge cycles of one Grocy "
        "battery, for the page a scanned battery code opens.  Same access and errors as the "
        "product lookup: 404 when Grocy has no such battery, 503 when Grocy is not set up."
    ),
)
async def grocy_battery(battery_id: GrocyIdPath, _auth: ReadAuthDep) -> GrocyBatteryResult:
    return await _lookup_service.grocy_battery(battery_id)


@router.get(
    "/grocy/chores/{chore_id}",
    response_model=GrocyChoreResult,
    summary="Read a Grocy chore",
    description=(
        "Name, description, last and next execution and the assigned user of one Grocy chore, "
        "for the page a scanned chore code opens.  Same access and errors as the product lookup: "
        "404 when Grocy has no such chore, 503 when Grocy is not set up."
    ),
)
async def grocy_chore(chore_id: GrocyIdPath, _auth: ReadAuthDep) -> GrocyChoreResult:
    return await _lookup_service.grocy_chore(chore_id)
