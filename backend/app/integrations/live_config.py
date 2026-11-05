"""Shared runtime-settings wiring for integration plugins (D4/D5).

A plugin keeps its no-argument constructor (entry-point discovery calls
``plugin_cls()``).  The lifespan then calls :meth:`bind` with the
``SettingsStore``; from that moment URL, secret and timeout come from the store
and follow every change without a restart.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

import httpx

from app.integrations.urls import base_url
from app.services.errors import IntegrationNotConfiguredError

if TYPE_CHECKING:
    from app.settings_store import SettingsStore

_log = logging.getLogger(__name__)


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
        self._base_url = base_url(str(store.get(self._key("url")) or ""))
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
        """
        slot, base, key = self._slot, self._base_url, self._api_key
        slot.users += 1
        try:
            return await slot.client.get(f"{base}{path}", headers=headers(key)), base
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
