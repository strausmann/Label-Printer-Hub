"""API schemas for webhook endpoints (Phase 6a Task 5).

Spoolman and Grocy both push event payloads when their data changes.  The hub
receives those events, resolves the label data via the appropriate integration
plugin, and prints the label through the print queue — returning a ``WebhookAcceptedResponse`` with
the new job's UUID so callers can poll for completion via ``GET /api/v1/jobs/{id}``.

Payload designs follow each upstream's documented webhook format:

- **Spoolman** — https://github.com/Donkie/Spoolman — events include a
  ``spool_id`` (the numeric spool identifier) and an event ``type`` string.
  ``quantity`` (filament remaining in grams) is accepted but not printed yet (#284).

- **Grocy** — https://grocy.info/api — webhook events include a
  ``product_id`` and an event ``type``.  ``quantity`` is the stock-level delta
  (optional; accepted but not printed yet, #284).

Both payloads use ``model_config = ConfigDict(strict=True, extra="ignore")``
so unknown upstream fields are silently dropped (forward-compatible) while
required fields are validated with Pydantic's strict type coercion.  A missing
required field (e.g. ``spool_id``) triggers a standard 422 Unprocessable Entity
response without any extra handler code.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SpoolmanWebhookPayload(BaseModel):
    """Event payload emitted by Spoolman when a spool is updated."""

    model_config = ConfigDict(strict=True, extra="ignore")

    spool_id: str = Field(
        description="Spoolman spool identifier (as a string to accept both int and str JSON input)",
    )
    type: str = Field(
        description="Event type string (e.g. 'updated', 'created', 'consumed')",
    )
    quantity: float | None = Field(
        default=None,
        allow_inf_nan=False,
        description="Optional remaining filament in grams. Accepted, not printed yet (see #284)",
    )


class GrocyWebhookPayload(BaseModel):
    """Event payload emitted by Grocy when a product stock event occurs."""

    model_config = ConfigDict(strict=True, extra="ignore")

    product_id: str = Field(
        description="Grocy product identifier",
    )
    type: str = Field(
        description="Event type string (e.g. 'stock_added', 'stock_removed')",
    )
    quantity: float | None = Field(
        default=None,
        allow_inf_nan=False,
        description="Optional stock quantity delta. Accepted, not printed yet (see #284)",
    )


class WebhookAcceptedResponse(BaseModel):
    """202 Accepted response body for both webhook endpoints."""

    job_id: UUID = Field(
        description="UUID of the new print job; poll GET /api/v1/jobs/{job_id} for status",
    )
