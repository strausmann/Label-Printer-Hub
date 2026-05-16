"""Printer-backend layer + plugin registry.

Built-in backends (`ptouch`, `mock`) ship pre-registered via setuptools
entry_points (group `label_hub.printer_backends`). Third-party backends
register the same way from their own pip package, with zero core changes.
"""

from __future__ import annotations

import logging
from importlib.metadata import entry_points
from typing import ClassVar


class UnknownBackendError(Exception):
    """Raised when settings.printer_backend names a backend that is not registered."""


_logger = logging.getLogger(__name__)


class BackendRegistry:
    """Class-level registry of PrinterBackend factory classes."""

    _factories: ClassVar[dict[str, type]] = {}
    _discovered: ClassVar[bool] = False

    @classmethod
    def register(cls, backend_id: str, factory: type) -> None:
        if backend_id in cls._factories:
            raise ValueError(f"backend_id {backend_id!r} is already registered")
        cls._factories[backend_id] = factory

    @classmethod
    def find_by_backend_id(cls, backend_id: str) -> type:
        try:
            return cls._factories[backend_id]
        except KeyError as exc:
            available = ", ".join(sorted(cls._factories)) or "<none registered>"
            raise UnknownBackendError(
                f"Unknown printer_backend {backend_id!r}. Available: {available}"
            ) from exc

    @classmethod
    def ensure_discovered(cls) -> None:
        """Walk the `label_hub.printer_backends` entry-points group once."""
        if cls._discovered:
            return
        cls._discovered = True
        for ep in entry_points(group="label_hub.printer_backends"):
            try:
                factory_cls = ep.load()
            except Exception:
                _logger.exception("Failed to load printer-backend entry-point %r", ep.name)
                continue
            try:
                cls.register(ep.name, factory_cls)
            except (ValueError, TypeError):
                _logger.exception("Failed to register printer-backend %r", ep.name)
