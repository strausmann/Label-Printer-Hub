"""Aggregator that routes lookup requests to the right integration plugin.

The service uses IntegrationRegistry as its source of truth. New apps
register themselves via entry_points (group 'label_hub.integrations') and
become available without touching this module.

Exception hierarchy
-------------------
- LookupFailedError  — umbrella; the REST layer catches this for HTTP 502
  - UnknownAppError  — config mismatch ("you asked for an unknown app")
- AppLookupNotFoundError (from any plugin) — entity-not-found; propagates
  unchanged so callers can handle it separately (e.g., HTTP 404).
  It is NOT a subclass of LookupFailedError — operationally distinct.
"""

from __future__ import annotations

# Trigger plugin discovery — importing this module guarantees the
# registry is populated regardless of whether main.py has imported
# app.integrations yet. The discovery is idempotent (registry
# rejects duplicates), so multiple imports are safe.
import app.integrations  # noqa: F401
from app.integrations.registry import (
    IntegrationNotFoundError,
    IntegrationRegistry,
)
from app.schemas.label_data import LabelData
from app.services.errors import AppLookupNotFoundError


class LookupFailedError(Exception):
    """Resolving label data via an integration plugin failed.

    This is the umbrella exception for all lookup failures:

    - UnknownAppError: config mismatch (unknown app name)
    - Any runtime exception from a plugin is wrapped into this type

    The REST layer catches this single type to return HTTP 502.
    """


class UnknownAppError(LookupFailedError):
    """Raised when `source_app` does not match any registered plugin."""


class AppLookupService:
    """Route `lookup(source_app, id)` through IntegrationRegistry."""

    async def lookup(self, source_app: str, identifier: str) -> LabelData:
        """Dispatch to the registered plugin for `source_app`.

        Raises:
            UnknownAppError: if no plugin is registered for `source_app`.
            AppLookupNotFoundError: if the plugin signals entity-not-found
                (propagates unchanged so callers can handle it separately).
            LookupFailedError: wraps any unexpected runtime exception from
                the plugin so the REST layer has one type to catch for 502.
        """
        try:
            plugin = IntegrationRegistry.get(source_app)
        except IntegrationNotFoundError as e:
            raise UnknownAppError(str(e)) from e
        try:
            return await plugin.lookup(identifier)
        except (LookupFailedError, AppLookupNotFoundError):
            raise
        except Exception as e:
            raise LookupFailedError(f"{source_app} lookup failed: {e}") from e

    @property
    def available_apps(self) -> list[str]:
        """Names of currently registered plugins, sorted alphabetically."""
        return IntegrationRegistry.names()
