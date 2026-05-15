"""Aggregator that routes lookup requests to the right integration plugin.

The service uses IntegrationRegistry as its source of truth. New apps
register themselves via entry_points (group 'label_hub.integrations') and
become available without touching this module.

UnknownAppError signals a configuration mismatch (the caller asked for an
app that wasn't registered). It deliberately does NOT inherit from
AppLookupNotFoundError — the two failure modes are operationally distinct:

- UnknownAppError: "you misconfigured the request"
- AppLookupNotFoundError (from any plugin): "the entity doesn't exist"
"""

from __future__ import annotations

from app.integrations.registry import (
    IntegrationNotFoundError,
    IntegrationRegistry,
)
from app.schemas.label_data import LabelData


class UnknownAppError(Exception):
    """Raised when `source_app` does not match any registered plugin."""


class AppLookupService:
    """Route `lookup(source_app, id)` through IntegrationRegistry."""

    async def lookup(self, source_app: str, identifier: str) -> LabelData:
        """Dispatch to the registered plugin for `source_app`.

        Raises UnknownAppError if no plugin is registered. Any
        AppLookupNotFoundError raised by the underlying plugin propagates
        unchanged so callers can catch it uniformly.
        """
        try:
            plugin = IntegrationRegistry.get(source_app)
        except IntegrationNotFoundError as e:
            raise UnknownAppError(str(e)) from e
        return await plugin.lookup(identifier)

    @property
    def available_apps(self) -> list[str]:
        """Names of currently registered plugins, sorted alphabetically."""
        return IntegrationRegistry.names()
