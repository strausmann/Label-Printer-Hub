"""Grocy integration plugin — product lookup by id.

Grocy uses a custom `GROCY-API-KEY` header (not Bearer) and returns 400
with `{"error_message": "..."}` for missing products instead of 404 —
both quirks are explicit in the plugin's mapping logic.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from app.integrations.live_config import StoreBoundPlugin
from app.schemas.label_data import LabelData
from app.services.errors import AppLookupNotFoundError


class GrocyNotFoundError(AppLookupNotFoundError):
    """Raised when no Grocy product matches the given id or barcode."""


_DIGITS = re.compile(r"[0-9]+")


class GrocyPlugin(StoreBoundPlugin):
    """Grocy integration plugin.

    Implements the IntegrationPlugin protocol — exposes `name`,
    `display_name`, and an async `lookup` resolving product-id →
    LabelData. Configuration injection follows the same pattern as
    SnipeITPlugin and SpoolmanPlugin.
    """

    name = "grocy"
    display_name = "Grocy"

    secret_suffix = "api_key"

    def __init__(self) -> None:
        self._init_live()

    @staticmethod
    def _headers(key: str) -> dict[str, str]:
        return {"GROCY-API-KEY": key, "Accept": "application/json"}

    async def lookup(self, product_id: str) -> LabelData:
        """Resolve a product id or a barcode, or raise GrocyNotFoundError.

        A pure integer is a product id first; a barcode (EAN) can be all digits too,
        so a digits-only value no product has as id is then tried as a barcode.
        Anything else is a barcode right away.
        """
        self._require_configured()
        if not _DIGITS.fullmatch(product_id):
            return await self._lookup_barcode(product_id)
        encoded_id = quote(product_id, safe="")
        response, base = await self._get(f"/api/objects/products/{encoded_id}", self._headers)

        # Grocy returns 400 with error_message for missing products, not 404.
        if response.status_code in (400, 404):
            return await self._lookup_barcode(product_id)
        # 401/403/5xx surface as httpx.HTTPStatusError — callers (AppLookupService)
        # decide whether to treat them as configuration errors vs transient failures.
        response.raise_for_status()

        payload: dict[str, Any] = response.json()
        return self._payload_to_label(payload, product_id, base)

    async def _lookup_barcode(self, barcode: str) -> LabelData:
        """``GET /api/stock/products/by-barcode/{barcode}`` (per Grocy's own OpenAPI file).

        200 is a ProductDetailsResponse whose ``product`` is the product; 400 is
        "Unknown barcode".
        """
        response, base = await self._get(
            f"/api/stock/products/by-barcode/{quote(barcode, safe='')}", self._headers
        )
        if response.status_code in (400, 404):
            raise GrocyNotFoundError(f"Product {barcode!r} not found")
        response.raise_for_status()
        details: dict[str, Any] = response.json()
        product = details.get("product")
        return self._payload_to_label(product if isinstance(product, dict) else {}, barcode, base)

    def _payload_to_label(
        self, payload: dict[str, Any], product_id: str, base: str | None = None
    ) -> LabelData:
        grocy_id = payload.get("id")
        if grocy_id is None:
            raise ValueError(f"Grocy response for {product_id!r} is missing required field 'id'")
        return LabelData(
            title=str(payload.get("name") or f"Product {product_id}"),
            primary_id=str(grocy_id),
            qr_payload=f"{base if base is not None else self._base_url}/product/{grocy_id}",
            source_app="grocy",
            secondary=(),
        )
