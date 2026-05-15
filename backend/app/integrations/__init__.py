"""Integration plugin discovery.

Importing this package triggers `_discover_plugins`, which scans the
`label_hub.integrations` entry-points group and registers every declared
plugin with `IntegrationRegistry`. Bundled plugins (snipeit, spoolman,
grocy) declare their entry-points in this repo's `pyproject.toml`.
Third-party plugins installed via pip register the same way without any
change to the core repo.

Loading is defensive: a broken third-party package logs an error and is
skipped, the remaining plugins still register.
"""

from __future__ import annotations

import importlib.metadata
import logging

from app.integrations.base import IntegrationPlugin
from app.integrations.registry import IntegrationRegistry

_logger = logging.getLogger(__name__)


def _discover_plugins() -> None:
    """Load every plugin under the 'label_hub.integrations' entry-points group.

    Each entry point is loaded independently — a failure in one does not
    prevent the others from registering. Four failure modes are handled:

    1. The entry-point's `ep.load()` raises (broken third-party package).
    2. Instantiating the loaded class raises (constructor error).
    3. The loaded object does not satisfy the IntegrationPlugin Protocol
       (missing attributes or wrong shape).
    4. The plugin's `name` collides with an already-registered plugin, or
       has the wrong type (Registry rejects with ValueError / TypeError).
    """
    for ep in importlib.metadata.entry_points(group="label_hub.integrations"):
        try:
            plugin_cls = ep.load()
        except Exception:
            _logger.exception("Failed to load entry-point %r", ep.name)
            continue

        try:
            instance = plugin_cls()
        except Exception:
            _logger.exception(
                "Failed to instantiate entry-point %r (class %s)",
                ep.name,
                getattr(plugin_cls, "__name__", repr(plugin_cls)),
            )
            continue

        if not isinstance(instance, IntegrationPlugin):
            _logger.error(
                "Entry-point %r exports %r which does not satisfy IntegrationPlugin "
                "(missing required attributes name/display_name/lookup)",
                ep.name,
                type(instance).__name__,
            )
            continue

        try:
            IntegrationRegistry.register(instance)
        except (ValueError, TypeError) as e:
            _logger.error(
                "Entry-point %r could not register: %s", ep.name, e
            )


_discover_plugins()
