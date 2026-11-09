"""BackendRouter membership (#224): printers are registered and unregistered at runtime."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from app.services.backend_router import BackendRouter, PrinterYAMLConfig, SNMPConfig


def _cfg(slug: str, host: str = "192.0.2.10") -> PrinterYAMLConfig:
    return PrinterYAMLConfig(
        slug=slug,
        name=slug,
        backend="ptouch",
        model="PT-P750W",
        host=host,
        snmp=SNMPConfig(discover=False),
    )


def test_backend_router_register_unregister() -> None:
    router = BackendRouter([])
    router.register(_cfg("workshop"))
    assert router.slugs() == ["workshop"]
    assert router.get("workshop") is not None
    assert router.config("workshop") is not None
    service = MagicMock()
    router.register_service("workshop", service)
    assert router.service_for("workshop") is service

    router.unregister("workshop")
    assert router.slugs() == []
    assert router.get("workshop") is None
    assert router.config("workshop") is None
    with pytest.raises(KeyError):
        router.service_for("workshop")
    router.unregister("workshop")  # unknown slug: no-op

    # Registering the slug again after the unregister works (a re-wire).
    router.register(_cfg("workshop", host="192.0.2.11"))
    assert router.config("workshop").host == "192.0.2.11"  # type: ignore[union-attr]


def test_backend_router_register_duplicate_slug_raises() -> None:
    router = BackendRouter([_cfg("workshop")])
    with pytest.raises(ValueError, match="workshop"):
        router.register(_cfg("workshop", host="192.0.2.11"))
    # The first registration is untouched.
    assert router.config("workshop").host == "192.0.2.10"  # type: ignore[union-attr]
