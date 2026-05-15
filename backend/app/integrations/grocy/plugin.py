"""Grocy integration plugin — product lookup by id.

Grocy uses a custom `GROCY-API-KEY` header (not Bearer) and returns 400
with `{"error_message": "..."}` for missing products instead of 404 —
both quirks are explicit in the plugin's mapping logic.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from app.schemas.label_data import LabelData
from app.services.errors import AppLookupNotFoundError


class GrocyNotFoundError(AppLookupNotFoundError):
    """Raised when no Grocy product matches the given id."""


class GrocyPlugin:
    """Grocy integration plugin.

    Implements the IntegrationPlugin protocol — exposes `name`,
    `display_name`, and an async `lookup` resolving product-id →
    LabelData. Configuration injection follows the same pattern as
    SnipeITPlugin and SpoolmanPlugin.
    """

    name = "grocy"
    display_name = "Grocy"

    def __init__(self) -> None:
        from app.config import get_settings
        settings = get_settings()
        self._base_url = settings.grocy_url.rstrip("/")
        self._api_key = settings.grocy_api_key.get_secret_value()
        self._timeout = settings.grocy_timeout

    async def lookup(self, product_id: str) -> LabelData:
        """Return LabelData for `product_id`, or raise GrocyNotFoundError."""
        # TODO(phase6): inject a shared httpx.AsyncClient for connection pooling
        #               when consumed by the FastAPI request handler.
        encoded_id = quote(product_id, safe="")
        url = f"{self._base_url}/api/objects/products/{encoded_id}"
        headers = {
            "GROCY-API-KEY": self._api_key,
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(url, headers=headers)

        # Grocy returns 400 with error_message for missing products, not 404.
        if response.status_code in (400, 404):
            raise GrocyNotFoundError(f"Product {product_id!r} not found")
        # 401/403/5xx surface as httpx.HTTPStatusError — callers (AppLookupService)
        # decide whether to treat them as configuration errors vs transient failures.
        response.raise_for_status()

        payload: dict[str, Any] = response.json()
        return self._payload_to_label(payload, product_id)

    def _payload_to_label(self, payload: dict[str, Any], product_id: str) -> LabelData:
        grocy_id = payload.get("id")
        if grocy_id is None:
            raise ValueError(f"Grocy response for {product_id!r} is missing required field 'id'")
        return LabelData(
            title=str(payload.get("name") or f"Product {product_id}"),
            primary_id=str(grocy_id),
            qr_payload=f"{self._base_url}/product/{grocy_id}",
            source_app="grocy",
            secondary=(),
        )
