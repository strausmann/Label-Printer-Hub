from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from app.services.backend_router import (
    BackendRouter,
    CutDefaults,
    PrinterYAMLConfig,
    UnknownBackendError,
)


def _pt(slug: str = "brother-p750w") -> PrinterYAMLConfig:
    return PrinterYAMLConfig(
        slug=slug,
        name=slug,
        backend="ptouch",
        model="PT-P750W",
        host="1.1.1.1",
    )


def _ql(slug: str = "brother-ql820") -> PrinterYAMLConfig:
    return PrinterYAMLConfig(
        slug=slug,
        name=slug,
        backend="brother_ql",
        model="QL-820NWB",
        host="2.2.2.2",
        cut_defaults=CutDefaults(half_cut=False, cut_at_end=True),
    )


def test_router_builds_ptouch_backend():
    router = BackendRouter([_pt()])
    backend = router.get("brother-p750w")
    assert backend is not None
    assert backend.backend_id == "ptouch"


def test_router_unknown_slug_returns_none():
    router = BackendRouter([_pt()])
    assert router.get("does-not-exist") is None


def test_router_all_returns_all_backends():
    router = BackendRouter([_pt("a"), _ql("b")])
    backends = router.all()
    assert len(backends) == 2
    backend_ids = {b.backend_id for b in backends}
    assert backend_ids == {"ptouch", "brother_ql"}


def test_router_unknown_backend_string_raises():
    with pytest.raises(UnknownBackendError):
        BackendRouter._build_one(
            PrinterYAMLConfig.model_construct(
                slug="x",
                name="x",
                backend="cups",
                model="x",
                host="x",
                port=9100,
            )
        )


def test_router_register_service_and_service_for():
    """R4-A-C2-Fix: service_for(slug) gibt registrierten PrintService zurück."""
    from app.services.print_service import PrintService

    router = BackendRouter([_pt()])
    mock_service = MagicMock(spec=PrintService)
    router.register_service("brother-p750w", mock_service)
    assert router.service_for("brother-p750w") is mock_service


def test_router_service_for_unknown_slug_raises():
    """service_for raises KeyError für unbekannten slug."""
    router = BackendRouter([_pt()])
    with pytest.raises(KeyError):
        router.service_for("does-not-exist")
