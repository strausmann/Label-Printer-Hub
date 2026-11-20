# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Shared runtime-settings wiring for integration plugins (D4/D5).

A plugin keeps its no-argument constructor (entry-point discovery calls
``plugin_cls()``).  The lifespan then calls :meth:`bind` with the
``SettingsStore``; from that moment URL, secret and timeout come from the store
and follow every change without a restart.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Final

import httpx

from app.integrations.urls import base_url
from app.services.errors import IntegrationNotConfiguredError, LookupFailedError

if TYPE_CHECKING:
    from app.settings_store import SettingsStore

_log = logging.getLogger(__name__)

#: Largest upstream answer a lookup accepts. A label lookup reads one small object; a
#: misconfigured or hostile upstream must not make the hub buffer an unbounded body.
MAX_LOOKUP_RESPONSE_BYTES: Final = 1_048_576


class LookupResponseTooLargeError(LookupFailedError):
    """The upstream answer is larger than :data:`MAX_LOOKUP_RESPONSE_BYTES` (HTTP 502)."""


async def _read_bounded(response: httpx.Response) -> bytes:
    """The body of ``response``, read in chunks and refused above the limit.

    A streaming response is read with ``aiter_raw`` and every wire byte is counted, so the
    limit holds without a ``Content-Length`` and for a chunked or lying one. The raw bytes are
    the body bytes because lookups ask for ``Accept-Encoding: identity`` and an answer that
    nevertheless carries a ``Content-Encoding`` is refused: httpx decodes a compressed chunk
    in one call without an output limit (a 64 KiB gzip chunk inflates to ~64 MiB), so the
    decoded size cannot be bounded after the fact. An already read response is checked by
    its size.
    """
    encoding = response.headers.get("content-encoding", "").strip().lower()
    if encoding not in ("", "identity"):
        raise LookupResponseTooLargeError("the upstream answer is compressed")
    if (declared := response.headers.get("content-length", "")).isdigit() and (
        int(declared) > MAX_LOOKUP_RESPONSE_BYTES
    ):
        raise LookupResponseTooLargeError("the upstream answer is too large")
    try:
        data = response.content
    except httpx.ResponseNotRead:
        pass
    else:
        if len(data) > MAX_LOOKUP_RESPONSE_BYTES:
            raise LookupResponseTooLargeError("the upstream answer is too large")
        return data
    body = bytearray()
    async for chunk in response.aiter_raw():
        body += chunk
        if len(body) > MAX_LOOKUP_RESPONSE_BYTES:
            raise LookupResponseTooLargeError("the upstream answer is too large")
    return bytes(body)


async def read_json_bounded(response: httpx.Response) -> Any:
    """Parse the JSON body of ``response`` after checking it against the size limit.

    Raises :class:`LookupResponseTooLargeError` above the limit and ``ValueError`` for a body
    that is not JSON (the lookup service maps both to ``integration_lookup_failed``).
    """
    return json.loads(await _read_bounded(response))


class _ClientSlot:
    """An ``httpx.AsyncClient`` plus the number of requests currently using it.

    A retired slot closes its client only when the last user has released it,
    so a settings change never cuts off a lookup that is already in flight.
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.users = 0
        self.retired = False


class StoreBoundPlugin:
    """Mixin: HTTP client + config snapshot refreshed from the settings store."""

    name: str
    display_name: str
    #: suffix of the secret setting ("api_key"), or None when the app needs none.
    secret_suffix: str | None = None

    def _init_live(self) -> None:
        self._store: SettingsStore | None = None
        self._base_url = ""
        self._api_key = ""
        self._timeout = 5.0
        self._slot = _ClientSlot(httpx.AsyncClient(timeout=self._timeout))
        self._closing: set[asyncio.Task[None]] = set()

    # -- binding ------------------------------------------------------------

    def bind(self, store: SettingsStore) -> None:
        self._store = store
        self._refresh()
        store.subscribe(self._on_settings_changed)

    def _key(self, suffix: str) -> str:
        return f"integrations.{self.name}.{suffix}"

    def _refresh(self) -> None:
        """Take a fresh snapshot of the store values and swap the client if needed."""
        store = self._store
        if store is None:
            return
        try:
            self._base_url = base_url(str(store.get(self._key("url")) or ""))
        except ValueError:
            # Environment URLs bypass the settings validator; a broken optional
            # integration must never stop the hub. The URL itself is not logged.
            _log.warning("%s: configured URL is an invalid URL; integration disabled", self.name)
            self._base_url = ""
        self._api_key = (
            str(store.get(self._key(self.secret_suffix)) or "") if self.secret_suffix else ""
        )
        timeout = float(store.get(self._key("timeout")))
        if timeout != self._timeout:
            self._timeout = timeout
            self._swap_client(timeout)

    @property
    def _client(self) -> httpx.AsyncClient:
        return self._slot.client

    def _swap_client(self, timeout: float) -> None:
        old = self._slot
        self._slot = _ClientSlot(httpx.AsyncClient(timeout=timeout))
        old.retired = True
        if old.users == 0:
            self._schedule_close(old.client)

    async def _get(
        self, path: str, headers: Callable[[str], dict[str, str]]
    ) -> tuple[httpx.Response, str]:
        """GET ``path`` with the config snapshot taken now; returns (response, base_url).

        The returned base URL is the one the request actually used, so callers
        build deep links from it instead of re-reading ``self._base_url``.

        The body is streamed and refused above :data:`MAX_LOOKUP_RESPONSE_BYTES`; the returned
        response is fully read, so ``read_json_bounded`` can parse it.
        """
        slot, base, key = self._slot, self._base_url, self._api_key
        slot.users += 1
        try:
            request = slot.client.build_request(
                "GET", f"{base}{path}", headers={**headers(key), "Accept-Encoding": "identity"}
            )
            streamed = await slot.client.send(request, stream=True)
            try:
                body = await _read_bounded(streamed)
            finally:
                await streamed.aclose()
            response = httpx.Response(
                streamed.status_code,
                headers=[
                    (k, v)
                    for k, v in streamed.headers.multi_items()
                    if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")
                ],
                content=body,
                request=request,
            )
            return response, base
        finally:
            slot.users -= 1
            if slot.retired and slot.users == 0:
                self._schedule_close(slot.client)

    def _schedule_close(self, client: httpx.AsyncClient) -> None:
        try:
            task = asyncio.get_running_loop().create_task(client.aclose())
        except RuntimeError:  # no running loop (sync caller): the pool is garbage collected
            return
        self._closing.add(task)
        task.add_done_callback(self._closing.discard)

    def _on_settings_changed(self, keys: set[str]) -> None:
        prefix = f"integrations.{self.name}."
        if any(k.startswith(prefix) for k in keys):
            self._refresh()

    async def reconfigure(self) -> None:
        """Re-read the store and recreate the HTTP client from the current values."""
        old = self._slot
        self._refresh()
        if self._slot is old:
            self._swap_client(self._timeout)

    def is_configured(self) -> bool:
        if self._store is None or not self._base_url:
            return False
        return not (self.secret_suffix and not self._api_key)

    def _require_configured(self) -> None:
        if not self.is_configured():
            raise IntegrationNotConfiguredError(f"{self.display_name} is not configured")

    async def aclose(self) -> None:
        """Close the shared HTTP client. Safe to call more than once."""
        await self._client.aclose()
