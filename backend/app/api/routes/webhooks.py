"""REST endpoints for Spoolman and Grocy webhooks (Phase 6a Task 5).

Routes
------
POST /api/webhook/spoolman — accept a Spoolman event, enqueue a print job
POST /api/webhook/grocy   — accept a Grocy event, enqueue a print job

Both routes are guarded by ``Depends(require_webhook_key)``.  The dependency
validates the ``X-API-Key`` request header and returns:

- **503** when ``PRINTER_HUB_WEBHOOK_API_KEY`` is not configured.
- **401** when the supplied key does not match.

On a valid request the handler:

1. Validates the JSON body against the appropriate payload schema — Pydantic
   returns 422 automatically when required fields are missing or have the wrong
   type.
2. Resolves the label data via ``AppLookupService.lookup()``.
3. Looks up the first enabled printer from the DB (the MVP target; Phase 7 will
   add per-webhook printer routing).
4. Creates a QUEUED job via ``jobs_repo.create_queued()``.
5. Returns 202 ``WebhookAcceptedResponse`` with the new job's UUID.

The queue worker (Phase 5 DB lifespan) picks up the QUEUED job and dispatches
the print asynchronously — the webhook returns before printing starts.

Design notes
------------
- Handlers do NOT call the printer directly; all print dispatch goes through
  ``jobs_repo.create_queued`` → queue worker.  This ensures job history,
  retry, and pause/resume work correctly.
- ``AppLookupService`` is module-level (stateless, settings read once).
- A 503 is returned with a ProblemDetail body when no printer is registered in
  the DB — this is a misconfiguration, not a caller error.

References:
    docs/superpowers/specs/2026-05-16-phase6a-rest-api-design.md — Webhooks section
    docs/superpowers/plans/2026-05-16-phase6a-rest-api.md — Task 5
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.webhook_auth import require_webhook_key
from app.db.session import get_session
from app.repositories import jobs as jobs_repo
from app.repositories import printers as printers_repo
from app.schemas.webhook import (
    GrocyWebhookPayload,
    SpoolmanWebhookPayload,
    WebhookAcceptedResponse,
)
from app.services.lookup_service import AppLookupService

router = APIRouter(prefix="/api/webhook", tags=["webhooks"])

# Shared service instance — stateless, safe to reuse across requests.
_lookup_service = AppLookupService()

# Type alias for the session dependency
SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def _resolve_default_printer_id(session: AsyncSession) -> str:
    """Return the first enabled printer's ID, or raise 503.

    MVP: webhooks route to the first registered printer.  Phase 7 adds
    per-webhook printer-routing configuration.
    """
    printers = await printers_repo.list_all(session)
    enabled = [p for p in printers if p.enabled]
    if not enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No enabled printers registered — cannot accept webhook",
        )
    return str(enabled[0].id)


@router.post(
    "/spoolman",
    response_model=WebhookAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Accept a Spoolman spool event and enqueue a print job",
    description=(
        "Receives a Spoolman webhook event for a spool update.  "
        "Requires the ``X-API-Key`` header — returns 503 when the key is not "
        "configured, 401 when the key is wrong, and 422 when required payload "
        "fields are missing.  On success returns 202 with the new job's UUID; "
        "the print is dispatched asynchronously by the queue worker."
    ),
    dependencies=[Depends(require_webhook_key)],
)
async def spoolman_webhook(
    payload: SpoolmanWebhookPayload,
    session: SessionDep,
) -> WebhookAcceptedResponse:
    """Enqueue a Spoolman label-print job from the incoming event."""
    label_data = await _lookup_service.lookup("spoolman", payload.spool_id)
    printer_id_str = await _resolve_default_printer_id(session)
    printer_id = UUID(printer_id_str)
    job_payload: dict[str, object] = {
        "source_app": "spoolman",
        "entity_id": payload.spool_id,
        "event_type": payload.type,
        "label_title": label_data.title,
        "qr_payload": label_data.qr_payload,
    }
    if payload.quantity is not None:
        job_payload["quantity"] = payload.quantity
    job = await jobs_repo.create_queued(
        session,
        printer_id=printer_id,
        template_key=f"spoolman/{payload.spool_id}",
        payload=job_payload,
    )
    return WebhookAcceptedResponse(job_id=job.id)


@router.post(
    "/grocy",
    response_model=WebhookAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Accept a Grocy product event and enqueue a print job",
    description=(
        "Receives a Grocy webhook event for a product stock change.  "
        "Requires the ``X-API-Key`` header — returns 503 when the key is not "
        "configured, 401 when the key is wrong, and 422 when required payload "
        "fields are missing.  On success returns 202 with the new job's UUID; "
        "the print is dispatched asynchronously by the queue worker."
    ),
    dependencies=[Depends(require_webhook_key)],
)
async def grocy_webhook(
    payload: GrocyWebhookPayload,
    session: SessionDep,
) -> WebhookAcceptedResponse:
    """Enqueue a Grocy label-print job from the incoming event."""
    label_data = await _lookup_service.lookup("grocy", payload.product_id)
    printer_id_str = await _resolve_default_printer_id(session)
    printer_id = UUID(printer_id_str)
    job_payload: dict[str, object] = {
        "source_app": "grocy",
        "entity_id": payload.product_id,
        "event_type": payload.type,
        "label_title": label_data.title,
        "qr_payload": label_data.qr_payload,
    }
    if payload.quantity is not None:
        job_payload["quantity"] = payload.quantity
    job = await jobs_repo.create_queued(
        session,
        printer_id=printer_id,
        template_key=f"grocy/{payload.product_id}",
        payload=job_payload,
    )
    return WebhookAcceptedResponse(job_id=job.id)
