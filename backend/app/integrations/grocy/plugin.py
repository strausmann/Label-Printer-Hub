# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Grocy integration plugin — product lookup by id, plus read-only battery and chore details.

Grocy uses a custom `GROCY-API-KEY` header (not Bearer) and returns 400
with `{"error_message": "..."}` for missing products instead of 404 —
both quirks are explicit in the plugin's mapping logic.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Protocol, runtime_checkable
from urllib.parse import quote

from app.integrations.live_config import StoreBoundPlugin, read_json_bounded
from app.schemas.grocy_object import GrocyBatteryResult, GrocyChoreResult
from app.schemas.label_data import LabelData
from app.services.errors import AppLookupNotFoundError


class GrocyNotFoundError(AppLookupNotFoundError):
    """Raised when no Grocy product, battery or chore matches the given id or barcode."""


_DIGITS = re.compile(r"[0-9]+")
# A barcode goes into a URL path. quote() leaves dots alone and httpx collapses dot-segments,
# so ".." would reach another authenticated Grocy endpoint: letters, digits, "-" and "_" only.
_BARCODE = re.compile(r"[A-Za-z0-9_-]{1,64}")
# Grocy writes "no next date" as the far-future 2999-12-31 23:59:59 (its OpenAPI example shows it).
_NEVER_YEAR = 2999


def _grocy_date(value: object) -> datetime | None:
    """Grocy's "YYYY-MM-DD HH:MM:SS" (local time) as a naive datetime.

    None for no date and for Grocy's "never" marker.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return None if parsed.year >= _NEVER_YEAR else parsed


_NAME_MAX = 200
_DESCRIPTION_MAX = 2000


def _text(value: object, limit: int) -> str | None:
    """Trimmed text cut to ``limit`` characters; None when it is not text or empty."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text[:limit] if text else None


@runtime_checkable
class GrocyObjectReader(Protocol):
    """What the scan page's battery and chore view needs from the registered Grocy integration."""

    async def battery(self, battery_id: str) -> GrocyBatteryResult: ...

    async def chore(self, chore_id: str) -> GrocyChoreResult: ...


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

        payload: dict[str, Any] = await read_json_bounded(response)
        return self._payload_to_label(payload, product_id, base)

    async def _lookup_barcode(self, barcode: str) -> LabelData:
        """``GET /api/stock/products/by-barcode/{barcode}`` (per Grocy's own OpenAPI file).

        200 is a ProductDetailsResponse whose ``product`` is the product; 400 is
        "Unknown barcode".
        """
        if not _BARCODE.fullmatch(barcode):
            raise GrocyNotFoundError(f"Product {barcode!r} not found")
        response, base = await self._get(f"/api/stock/products/by-barcode/{barcode}", self._headers)
        if response.status_code in (400, 404):
            raise GrocyNotFoundError(f"Product {barcode!r} not found")
        response.raise_for_status()
        details = await read_json_bounded(response)
        product = details.get("product") if isinstance(details, dict) else None
        if not isinstance(product, dict):
            raise ValueError(f"Grocy response for barcode {barcode!r} has no product object")
        return self._payload_to_label(product, barcode, base)

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

    async def battery(self, battery_id: str) -> GrocyBatteryResult:
        """``GET /api/batteries/{batteryId}`` (BatteryDetailsResponse in Grocy's OpenAPI file).

        Grocy answers 400 with ``error_message`` for a battery that does not exist.
        The object sits under ``battery`` (what Grocy's code returns and its example shows;
        the schema section names the key ``chore`` by mistake).
        """
        details, base = await self._details("batteries", battery_id, "Battery")
        battery = details.get("battery")
        if not isinstance(battery, dict):
            raise ValueError(f"Grocy response for battery {battery_id!r} has no battery object")
        cycles = details.get("charge_cycles_count")
        # The id and the link come from the id that was asked for (digits only, checked), not from
        # the answer: Grocy's JSON never decides where the link points.
        return GrocyBatteryResult(
            id=battery_id,
            name=_text(battery.get("name"), _NAME_MAX) or f"Battery {battery_id}",
            description=_text(battery.get("description"), _DESCRIPTION_MAX),
            url=f"{base}/battery/{battery_id}",
            last_charged=_grocy_date(details.get("last_charged")),
            next_estimated_charge=_grocy_date(details.get("next_estimated_charge_time")),
            charge_cycles=cycles
            if isinstance(cycles, int) and not isinstance(cycles, bool) and cycles >= 0
            else 0,
        )

    async def chore(self, chore_id: str) -> GrocyChoreResult:
        """``GET /api/chores/{choreId}`` (ChoreDetailsResponse in Grocy's OpenAPI file)."""
        details, base = await self._details("chores", chore_id, "Chore")
        chore = details.get("chore")
        if not isinstance(chore, dict):
            raise ValueError(f"Grocy response for chore {chore_id!r} has no chore object")
        assigned = details.get("next_execution_assigned_user")
        return GrocyChoreResult(
            id=chore_id,
            name=_text(chore.get("name"), _NAME_MAX) or f"Chore {chore_id}",
            description=_text(chore.get("description"), _DESCRIPTION_MAX),
            url=f"{base}/chore/{chore_id}",
            last_tracked=_grocy_date(details.get("last_tracked")),
            next_estimated_execution=_grocy_date(details.get("next_estimated_execution_time")),
            assigned_to=(
                _text(assigned.get("display_name"), _NAME_MAX)
                if isinstance(assigned, dict)
                else None
            ),
        )

    async def _details(
        self, collection: str, object_id: str, label: str
    ) -> tuple[dict[str, Any], str]:
        """The details object of one battery or chore, with the base URL the request used."""
        self._require_configured()
        if not _DIGITS.fullmatch(object_id):
            raise GrocyNotFoundError(f"{label} {object_id!r} not found")
        response, base = await self._get(f"/api/{collection}/{object_id}", self._headers)
        if response.status_code in (400, 404):
            raise GrocyNotFoundError(f"{label} {object_id!r} not found")
        response.raise_for_status()
        details = await read_json_bounded(response)
        if not isinstance(details, dict):
            raise ValueError(f"Grocy response for {label.lower()} {object_id!r} is not an object")
        return details, base
