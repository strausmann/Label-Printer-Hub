"""Spoolman REST API client — filament-spool lookup by id.

Spoolman is intended for trusted-network deployment and requires no
authentication. The label title is composed from the spool's filament
vendor + name; primary_id is prefixed with '#' to read like an entity id
on the printed label.
"""

from __future__ import annotations

import math
import re
from typing import Any

from app.integrations.live_config import StoreBoundPlugin
from app.schemas.label_data import LabelData
from app.services.errors import AppLookupNotFoundError

# Spool ids are integers. Anything else (dot-segments included) would change the request path.
_SPOOL_ID = re.compile(r"[0-9]{1,20}")


class SpoolmanNotFoundError(AppLookupNotFoundError):
    """Raised when no Spoolman spool matches the given id."""


class SpoolmanPlugin(StoreBoundPlugin):
    """Spoolman integration plugin.

    Implements the IntegrationPlugin protocol — exposes `name`,
    `display_name`, and an async `lookup` resolving spool-id → LabelData.
    Configuration (base URL + timeout) is read from settings; Spoolman
    requires no authentication, so there is no api_key field.
    """

    name = "spoolman"
    display_name = "Spoolman"

    secret_suffix = None

    def __init__(self) -> None:
        self._init_live()

    async def lookup(self, spool_id: str) -> LabelData:
        """Return LabelData for `spool_id`, or raise SpoolmanNotFoundError."""
        self._require_configured()
        if not _SPOOL_ID.fullmatch(spool_id):
            raise SpoolmanNotFoundError(f"Spool {spool_id!r} not found")
        response, base = await self._get(
            f"/api/v1/spool/{spool_id}",
            lambda _key: {"Accept": "application/json"},
        )

        if response.status_code == 404:
            raise SpoolmanNotFoundError(f"Spool {spool_id!r} not found")
        # 401/403/5xx surface as httpx.HTTPStatusError — callers (AppLookupService)
        # decide whether to treat them as configuration errors vs transient failures.
        response.raise_for_status()

        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"Spoolman response for {spool_id!r} is not an object")
        return self._payload_to_label(payload, spool_id, base)

    def _payload_to_label(
        self, payload: dict[str, Any], spool_id: str, base: str | None = None
    ) -> LabelData:
        spoolman_id = payload.get("id")
        if spoolman_id is None:
            raise ValueError(f"Spoolman response for {spool_id!r} is missing required field 'id'")
        filament: dict[str, Any] = payload.get("filament") or {}
        vendor: dict[str, Any] = filament.get("vendor") or {}
        vendor_name = str(vendor.get("name") or "Unknown")
        material = str(filament.get("name") or "Unknown")

        secondary_parts: list[str] = []
        remaining = payload.get("remaining_weight")
        if remaining is not None:
            # Round half up — Python's round() and f"{x:.0f}" use banker's rounding,
            # which would display 850 for 850.5. Wrong for a weight label.
            grams = math.floor(float(remaining) + 0.5)
            secondary_parts.append(f"{grams}g remaining")

        return LabelData(
            title=f"{vendor_name} {material}",
            primary_id=f"#{spoolman_id}",
            qr_payload=f"{base if base is not None else self._base_url}/spool/show/{spoolman_id}",
            source_app="spoolman",
            secondary=tuple(secondary_parts),
        )
