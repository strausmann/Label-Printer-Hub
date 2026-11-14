# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Snipe-IT REST API client — asset lookup by asset_tag.

The client emits domain-level `LabelData` records so downstream consumers
(LabelRenderer, queue submitters) never see Snipe-IT's raw schema. Add new
fields by extending the mapping in `lookup()`, never by leaking the upstream
shape.
"""

from __future__ import annotations

import re
from typing import Any, TypedDict, cast

from app.integrations.live_config import StoreBoundPlugin
from app.schemas.label_data import LabelData
from app.services.errors import AppLookupNotFoundError


class _SnipeITAssetResponse(TypedDict, total=False):
    """Subset of Snipe-IT `/api/v1/hardware/bytag/{tag}` response we actually
    read. Strikt-typisiert statt `dict[str, Any]` — beschränkt sich auf die
    Felder die `_payload_to_label` konsumiert. `total=False` weil alle Felder
    außer `id` optional sind (User-Mapping kann Snipe-IT-fields ausblenden).

    Audit #67 / PR #51 Finding: das alte `dict[str, Any]` hat das Hub-mypy-
    strict-Verbot von `Any` in Plugin-Responses verletzt.
    """

    id: int
    asset_tag: str | None
    name: str | None
    serial: str | None


class SnipeITNotFoundError(AppLookupNotFoundError):
    """Raised when no Snipe-IT asset or location matches the given value."""


#: ``loc:<id>`` addresses a location; every other value is an asset (tag or numeric id).
LOCATION_PREFIX = "loc:"
# Identifiers go into URL paths. quote() leaves dots alone and httpx collapses dot-segments, so
# ".." would reach another endpoint: allow letters, digits, "-", "_" and "." (never dots only).
_ASSET_TAG = re.compile(r"(?!\.+$)[A-Za-z0-9._-]{1,64}")
_DIGITS = re.compile(r"[0-9]{1,20}")


def _as_object(response_json: object, what: str) -> dict[str, Any]:
    if not isinstance(response_json, dict):
        raise ValueError(f"Snipe-IT response for {what} is not an object")
    return response_json


def _is_error_payload(response_json: object) -> bool:
    """Snipe-IT answers some unknown ids with 200 and ``{"status": "error", ...}``."""
    return isinstance(response_json, dict) and response_json.get("status") == "error"


class SnipeITPlugin(StoreBoundPlugin):
    """Snipe-IT integration plugin.

    Implements the IntegrationPlugin protocol — exposes `name`,
    `display_name`, and an async `lookup` resolving asset_tag → LabelData.
    Configuration (base URL, API key, timeout) is injected so the same
    instance can hit the user's live Snipe-IT from production and a
    respx-mocked endpoint from tests, with no hidden global state.

    A single ``httpx.AsyncClient`` is created at construction time and
    reused for the lifetime of the plugin instance, enabling TCP/TLS
    connection pooling. Call ``aclose()`` on application shutdown to
    release the underlying connection pool gracefully.
    """

    name = "snipeit"
    display_name = "Snipe-IT"

    secret_suffix = "api_key"

    def __init__(self) -> None:
        self._init_live()

    @staticmethod
    def _headers(key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {key}", "Accept": "application/json"}

    async def lookup(self, asset_tag: str) -> LabelData:
        """Resolve ``loc:<id>`` to a location, anything else to an asset.

        An asset is found by its tag; a purely numeric value that is no tag is tried
        as the numeric asset id (the number in a printed ``/asset/<id>`` link).
        Raises SnipeITNotFoundError when nothing matches.
        """
        self._require_configured()
        if asset_tag.startswith(LOCATION_PREFIX):
            return await self._lookup_location(asset_tag, asset_tag[len(LOCATION_PREFIX) :])
        if not _ASSET_TAG.fullmatch(asset_tag):
            raise SnipeITNotFoundError(f"Asset {asset_tag!r} not found")
        response, base = await self._get(f"/api/v1/hardware/bytag/{asset_tag}", self._headers)

        if response.status_code == 404 or (
            response.status_code == 200 and _is_error_payload(response.json())
        ):
            if _DIGITS.fullmatch(asset_tag):
                return await self._lookup_asset_by_id(asset_tag)
            raise SnipeITNotFoundError(f"Asset {asset_tag!r} not found")
        # 401/403/5xx surface as httpx.HTTPStatusError — callers (AppLookupService)
        # decide whether to treat them as configuration errors vs transient failures.
        response.raise_for_status()

        payload = cast(_SnipeITAssetResponse, _as_object(response.json(), repr(asset_tag)))
        return self._payload_to_label(payload, asset_tag, base)

    async def _lookup_asset_by_id(self, asset_id: str) -> LabelData:
        response, base = await self._get(f"/api/v1/hardware/{asset_id}", self._headers)
        if response.status_code == 404 or (
            response.status_code == 200 and _is_error_payload(response.json())
        ):
            raise SnipeITNotFoundError(f"Asset {asset_id!r} not found")
        response.raise_for_status()
        payload = cast(_SnipeITAssetResponse, _as_object(response.json(), repr(asset_id)))
        return self._payload_to_label(payload, asset_id, base)

    async def _lookup_location(self, value: str, location_id: str) -> LabelData:
        # Only digits reach the URL: a malformed id is "not found" without a request.
        if not _DIGITS.fullmatch(location_id):
            raise SnipeITNotFoundError(f"Location {value!r} not found")
        response, base = await self._get(f"/api/v1/locations/{location_id}", self._headers)
        if response.status_code == 404 or (
            response.status_code == 200 and _is_error_payload(response.json())
        ):
            raise SnipeITNotFoundError(f"Location {location_id!r} not found")
        response.raise_for_status()
        payload = _as_object(response.json(), repr(value))
        loc_id = payload.get("id")
        if loc_id is None:
            raise ValueError(f"Snipe-IT response for {value!r} is missing required field 'id'")
        address = payload.get("address")
        return LabelData(
            title=str(payload.get("name") or f"Location {loc_id}"),
            primary_id=f"{LOCATION_PREFIX}{loc_id}",
            qr_payload=f"{base}/locations/{loc_id}",
            source_app="snipeit",
            secondary=(str(address),) if address else (),
        )

    def _payload_to_label(
        self, payload: _SnipeITAssetResponse, asset_tag: str, base: str | None = None
    ) -> LabelData:
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
            qr_payload=f"{base if base is not None else self._base_url}/hardware/{asset_id}",
            source_app="snipeit",
            secondary=tuple(secondary),
        )
