"""Snipe-IT REST API client — asset lookup by asset_tag.

The client emits domain-level `LabelData` records so downstream consumers
(LabelRenderer, queue submitters) never see Snipe-IT's raw schema. Add new
fields by extending the mapping in `lookup()`, never by leaking the upstream
shape.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from app.schemas.label_data import LabelData


class SnipeITNotFoundError(Exception):
    """Raised when no Snipe-IT asset matches the given tag."""


class SnipeITClient:
    """Async client for Snipe-IT's REST API.

    Authenticates with a bearer token (Snipe-IT API key). Configuration —
    base URL, API key, timeout — is injected so the same class can hit the
    user's live instance from production and a respx-mocked endpoint from
    tests, with no hidden global state.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout: float = 5.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    async def lookup(self, asset_tag: str) -> LabelData:
        """Return LabelData for `asset_tag`, or raise SnipeITNotFoundError."""
        # TODO(phase6): inject a shared httpx.AsyncClient for connection pooling
        #               when this client is consumed by the FastAPI request handler.
        encoded_tag = quote(asset_tag, safe="")
        url = f"{self._base_url}/api/v1/hardware/bytag/{encoded_tag}"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(url, headers=headers)

        if response.status_code == 404:
            raise SnipeITNotFoundError(f"Asset {asset_tag!r} not found")
        # 401/403/5xx surface as httpx.HTTPStatusError — callers (AppLookupService)
        # decide whether to treat them as configuration errors vs transient failures.
        response.raise_for_status()

        payload: dict[str, Any] = response.json()
        return self._payload_to_label(payload, asset_tag)

    def _payload_to_label(self, payload: dict[str, Any], asset_tag: str) -> LabelData:
        asset_id = payload.get("id")
        if asset_id is None:
            raise ValueError(f"Snipe-IT response for {asset_tag!r} is missing required field 'id'")
        secondary: list[str] = []
        serial = payload.get("serial")
        if serial:
            secondary.append(f"S/N: {serial}")
        return LabelData(
            title=str(payload.get("name") or asset_tag),
            primary_id=str(payload.get("asset_tag") or asset_tag),
            qr_payload=f"{self._base_url}/hardware/{asset_id}",
            source_app="snipeit",
            secondary=tuple(secondary),
        )
