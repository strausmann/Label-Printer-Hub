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
    prevent the others from registering. Three failure modes are handled:
    the loaded object is not an IntegrationPlugin, ep.load() itself raises,
    or two plugins share a name (collision).
    """
    for ep in importlib.metadata.entry_points(group="label_hub.integrations"):
        try:
            plugin_cls = ep.load()
        except Exception as e:  # third-party load can raise anything
            _logger.error(
                "Failed to load entry-point %r: %s", ep.name, e
            )
            continue

        try:
            instance = plugin_cls()
        except Exception as e:
            _logger.error(
                "Failed to instantiate entry-point %r (class %r): %s",
                ep.name,
                plugin_cls.__name__ if hasattr(plugin_cls, "__name__") else plugin_cls,
                e,
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
        except ValueError as e:
            _logger.error(
                "Entry-point %r could not register: %s", ep.name, e
            )


_discover_plugins()
