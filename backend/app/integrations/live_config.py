"""Shared runtime-settings wiring for integration plugins (D4/D5).

A plugin keeps its no-argument constructor (entry-point discovery calls
``plugin_cls()``).  The lifespan then calls :meth:`bind` with the
``SettingsStore``; from that moment URL, secret and timeout come from the store
and follow every change without a restart.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import httpx

from app.services.errors import IntegrationNotConfiguredError

if TYPE_CHECKING:
    from app.settings_store import SettingsStore

_log = logging.getLogger(__name__)


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
        self._client = httpx.AsyncClient(timeout=self._timeout)
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
        self._base_url = str(store.get(self._key("url")) or "").rstrip("/")
        self._api_key = (
            str(store.get(self._key(self.secret_suffix)) or "") if self.secret_suffix else ""
        )
        timeout = float(store.get(self._key("timeout")))
        if timeout != self._timeout:
            self._timeout = timeout
            old = self._client
            self._client = httpx.AsyncClient(timeout=timeout)
            self._schedule_close(old)

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
        old = self._client
        self._refresh()
        if self._client is old:
            self._client = httpx.AsyncClient(timeout=self._timeout)
            await old.aclose()

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
