"""Spoolman REST API client — filament-spool lookup by id.

Spoolman is intended for trusted-network deployment and requires no
authentication. The label title is composed from the spool's filament
vendor + name; primary_id is prefixed with '#' to read like an entity id
on the printed label.
"""

from __future__ import annotations

import math
from typing import Any
from urllib.parse import quote

import httpx

from app.schemas.label_data import LabelData
from app.services.errors import AppLookupNotFoundError


class SpoolmanNotFoundError(AppLookupNotFoundError):
    """Raised when no Spoolman spool matches the given id."""


class SpoolmanClient:
    """Async client for Spoolman's REST API."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout: float = 5.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def lookup(self, spool_id: str) -> LabelData:
        """Return LabelData for `spool_id`, or raise SpoolmanNotFoundError."""
        # TODO(phase6): inject a shared httpx.AsyncClient for connection pooling
        #               when consumed by the FastAPI request handler.
        encoded_id = quote(spool_id, safe="")
        url = f"{self._base_url}/api/v1/spool/{encoded_id}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(url, headers={"Accept": "application/json"})

        if response.status_code == 404:
            raise SpoolmanNotFoundError(f"Spool {spool_id!r} not found")
        # 401/403/5xx surface as httpx.HTTPStatusError — callers (AppLookupService)
        # decide whether to treat them as configuration errors vs transient failures.
        response.raise_for_status()

        payload: dict[str, Any] = response.json()
        return self._payload_to_label(payload, spool_id)

    def _payload_to_label(self, payload: dict[str, Any], spool_id: str) -> LabelData:
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
            qr_payload=f"{self._base_url}/spool/show/{spoolman_id}",
            source_app="spoolman",
            secondary=tuple(secondary_parts),
        )
