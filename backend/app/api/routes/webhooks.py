"""REST endpoints for Spoolman and Grocy webhooks.

Routes
------
POST /api/v1/webhook/spoolman — accept a Spoolman event and print its label
POST /api/v1/webhook/grocy   — accept a Grocy event and print its label

Both routes are guarded by ``Depends(require_webhook_key)``.  The dependency
validates the ``X-API-Key`` request header and returns:

- **503** when ``PRINTER_HUB_WEBHOOK_API_KEY`` is not configured.
- **401** when the supplied key does not match.

A second dependency, ``enforce_webhook_rate_limit``, runs after the key is accepted and answers
**429** with ``Retry-After`` above ``PRINTER_HUB_WEBHOOK_LIMIT_PER_MINUTE`` calls per minute
(default 120; one bucket per webhook key, both routes together).

On a valid request the handler:

1. Validates the JSON body against the appropriate payload schema — Pydantic
   returns 422 automatically when required fields are missing or have the wrong
   type.
2. Looks up the first enabled tape printer from the DB (the MVP target; Phase 7 will
   add per-webhook printer routing) and its ``PrintService``.
3. Submits a ``qr_two_lines`` label for the spool or product through
   ``PrintService.submit_print_job`` — the same path as ``POST /api/v1/print``: preflight,
   lookup, render, persist, queue.
4. Returns 202 ``WebhookAcceptedResponse`` with the new job's UUID; the queue worker prints.

Errors before anything is queued (no tape, printer disabled or offline, unknown app, failed
lookup, ...) are answered exactly like ``POST /api/v1/print`` (409/422/502/503) and leave no
job row behind.  One copy is printed: ``quantity`` is accepted but not printed (#284).

Webhook jobs have no owner (the webhook key is not an API key), so only an admin or SSO caller
sees them.

References:
    docs/superpowers/specs/2026-05-16-phase6a-rest-api-design.md — Webhooks section
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.webhook_auth import enforce_webhook_rate_limit, require_webhook_key
from app.api.print_errors import SYNC_ERROR_TYPES, print_error_response
from app.db.session import get_session
from app.repositories import printers as printers_repo
from app.schemas.content_type import ContentType
from app.schemas.print_request import PrintLookupRequest, PrintOptions, PrintRequest
from app.schemas.webhook import (
    GrocyWebhookPayload,
    SpoolmanWebhookPayload,
    WebhookAcceptedResponse,
)

router = APIRouter(prefix="/api/v1/webhook", tags=["webhooks"])

# Type alias for the session dependency
SessionDep = Annotated[AsyncSession, Depends(get_session)]

_WEBHOOK_DEPENDENCIES = [Depends(require_webhook_key), Depends(enforce_webhook_rate_limit)]


async def _resolve_default_printer_id(session: AsyncSession) -> str:
    """Return the first enabled *tape* printer's ID, or raise 503.

    MVP: webhooks route to the first registered tape printer.  Phase 7 adds
    per-webhook printer-routing configuration.  A webhook job is a tape label job, and
    tape jobs are never routed to an IPP page printer (spec 11.4).
    """
    printers = await printers_repo.list_all(session)
    enabled = [p for p in printers if p.enabled and p.backend != "ipp"]
    if not enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No enabled printers registered that print tape labels — cannot accept webhook",
        )
    return str(enabled[0].id)


async def _print_label(
    request: Request, session: AsyncSession, *, app: str, identifier: str
) -> Any:
    """Submit the label of ``app``/``identifier`` to the default tape printer's queue."""
    printer_id = UUID(await _resolve_default_printer_id(session))
    service = request.app.state.printer_runtime.print_service_for(printer_id)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The tape printer is not attached to the print queue — cannot accept webhook",
        )
    try:
        job_id = await service.submit_print_job(
            PrintRequest(
                content_type=ContentType.QR_TWO_LINES,
                lookup=PrintLookupRequest(app=app, identifier=identifier),
                options=PrintOptions(),
            ),
            # No API key owns a webhook job, but the audit trail still names the peer.
            source_ip=request.client.host if request.client else None,
        )
    except SYNC_ERROR_TYPES as exc:
        return print_error_response(exc)
    return WebhookAcceptedResponse(job_id=job_id)


@router.post(
    "/spoolman",
    response_model=WebhookAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Accept a Spoolman spool event and print its label",
    description=(
        "Receives a Spoolman webhook event for a spool update and prints the spool label "
        "through the print queue, like ``POST /api/v1/print``.  "
        "Requires the ``X-API-Key`` header — returns 503 when the key is not "
        "configured, 401 when the key is wrong, 422 when required payload "
        "fields are missing and 429 above the per-key rate limit.  Printer and lookup "
        "errors (no tape, printer disabled or offline, integration failed) are answered "
        "as by ``POST /api/v1/print`` (409/422/502/503); an unknown spool or product "
        "answers 404 ``app-lookup-not-found`` and an integration that is not configured "
        "503 ``integration_not_configured`` (both in the problem-detail body shape). "
        "Nothing is queued.  On success "
        "returns 202 with the new job's UUID; the queue worker prints it.  One label is "
        "printed; ``quantity`` is accepted but not printed."
    ),
    dependencies=_WEBHOOK_DEPENDENCIES,
)
async def spoolman_webhook(
    payload: SpoolmanWebhookPayload,
    request: Request,
    session: SessionDep,
) -> Any:
    """Print a Spoolman spool label from the incoming event."""
    return await _print_label(request, session, app="spoolman", identifier=payload.spool_id)


@router.post(
    "/grocy",
    response_model=WebhookAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Accept a Grocy product event and print its label",
    description=(
        "Receives a Grocy webhook event for a product stock change and prints the product "
        "label through the print queue, like ``POST /api/v1/print``.  "
        "Requires the ``X-API-Key`` header — returns 503 when the key is not "
        "configured, 401 when the key is wrong, 422 when required payload "
        "fields are missing and 429 above the per-key rate limit.  Printer and lookup "
        "errors (no tape, printer disabled or offline, integration failed) are answered "
        "as by ``POST /api/v1/print`` (409/422/502/503); an unknown spool or product "
        "answers 404 ``app-lookup-not-found`` and an integration that is not configured "
        "503 ``integration_not_configured`` (both in the problem-detail body shape). "
        "Nothing is queued.  On success "
        "returns 202 with the new job's UUID; the queue worker prints it.  One label is "
        "printed; ``quantity`` is accepted but not printed."
    ),
    dependencies=_WEBHOOK_DEPENDENCIES,
)
async def grocy_webhook(
    payload: GrocyWebhookPayload,
    request: Request,
    session: SessionDep,
) -> Any:
    """Print a Grocy product label from the incoming event."""
    return await _print_label(request, session, app="grocy", identifier=payload.product_id)
