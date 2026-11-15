# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Protocol contract for integration-lookup plugins.

Each external app (Snipe-IT, Spoolman, Grocy, future integrations) lives
in its own module under app.integrations.<name>, implements this Protocol,
and registers itself via setuptools entry-points (group
'label_hub.integrations'). The Protocol is @runtime_checkable so the
entry-points discovery in `app.integrations.__init__` can validate each
loaded class with isinstance() before registering it, rejecting broken
third-party plugins with a clear log message.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from app.schemas.label_data import LabelData

if TYPE_CHECKING:
    from app.settings_store import SettingsStore


@runtime_checkable
class IntegrationPlugin(Protocol):
    """Per-integration lookup contract."""

    name: str  # canonical id, e.g. "snipeit" — matches TemplateSchema.app
    display_name: str  # UI-friendly, e.g. "Snipe-IT"

    async def lookup(self, identifier: str) -> LabelData:
        """Resolve an integration-specific identifier to LabelData.

        Raises AppLookupNotFoundError (or a subclass) if the entity does not
        exist on the upstream app.
        """

    def bind(self, store: SettingsStore) -> None:
        """Attach the runtime settings store (called once in the lifespan after discovery)."""

    async def reconfigure(self) -> None:
        """Close and recreate the HTTP client from the current store values."""

    def is_configured(self) -> bool:
        """True when URL (and key, where needed) are set and usable. False before ``bind``."""
