"""Discover integration plugins by name.

The registry is class-level state, populated either by direct
`register()` calls (used by tests) or by the entry-points discovery in
`app.integrations.__init__` at module import time.
"""

from __future__ import annotations

from typing import ClassVar

from app.integrations.base import IntegrationPlugin


class IntegrationNotFoundError(Exception):
    """No plugin registered for the given integration name."""


class IntegrationRegistry:
    """Class-level registry of IntegrationPlugin instances."""

    _plugins: ClassVar[dict[str, IntegrationPlugin]] = {}

    @classmethod
    def register(cls, plugin: IntegrationPlugin) -> None:
        """Add `plugin` under its `.name`.

        Rejects empty, whitespace-only, or non-string names and duplicates.
        """
        if not isinstance(plugin.name, str):
            raise TypeError(
                f"IntegrationPlugin name must be a string; got {type(plugin.name).__name__}"
            )
        if not plugin.name.strip():
            raise ValueError(
                f"IntegrationPlugin requires a non-empty name; got {plugin.name!r}"
            )
        if plugin.name in cls._plugins:
            raise ValueError(
                f"Plugin {plugin.name!r} already registered"
            )
        cls._plugins[plugin.name] = plugin

    @classmethod
    def get(cls, name: str) -> IntegrationPlugin:
        """Return the plugin registered under `name` or raise."""
        plugin = cls._plugins.get(name)
        if plugin is None:
            raise IntegrationNotFoundError(
                f"Unknown integration {name!r}. Registered: {sorted(cls._plugins)}"
            )
        return plugin

    @classmethod
    def all(cls) -> dict[str, IntegrationPlugin]:
        """Return a shallow copy of the registry (callers may mutate safely)."""
        return dict(cls._plugins)

    @classmethod
    def names(cls) -> list[str]:
        """Return registered plugin names, sorted alphabetically."""
        return sorted(cls._plugins)
