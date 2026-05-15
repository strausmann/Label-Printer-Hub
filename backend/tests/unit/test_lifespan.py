from __future__ import annotations

import pytest
from app.config import get_settings
from app.main import create_app
from app.printer_backends import BackendRegistry
from app.printer_models.registry import ModelRegistry
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def clean_registries():
    BackendRegistry._factories.clear()
    BackendRegistry._discovered = False
    ModelRegistry._models.clear()
    ModelRegistry._discovered = False
    get_settings.cache_clear()
    yield
    BackendRegistry._factories.clear()
    BackendRegistry._discovered = False
    ModelRegistry._models.clear()
    ModelRegistry._discovered = False
    get_settings.cache_clear()


async def test_lifespan_starts_with_mock_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRINTER_HUB_PRINTER_BACKEND", "mock")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_MODEL", "PT-P750W")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_DISCOVER_VIA_SNMP", "false")
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/healthz")
        assert r.status_code in (200, 404)


async def test_unknown_backend_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRINTER_HUB_PRINTER_BACKEND", "zebra-zpl")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_MODEL", "PT-P750W")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_DISCOVER_VIA_SNMP", "false")
    app = create_app()
    with pytest.raises(Exception, match="zebra-zpl"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            await c.get("/healthz")


async def test_unknown_model_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRINTER_HUB_PRINTER_BACKEND", "mock")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_MODEL", "Imaginary-9000")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_DISCOVER_VIA_SNMP", "false")
    app = create_app()
    with pytest.raises(Exception, match="Imaginary-9000"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            await c.get("/healthz")


async def test_snmp_discovery_resolves_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """SNMP returns a stubbed PJL string; lifespan resolves it via find_by_pjl."""
    monkeypatch.setenv("PRINTER_HUB_PRINTER_BACKEND", "mock")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_DISCOVER_VIA_SNMP", "true")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_MODEL", "")
    monkeypatch.setenv("PRINTER_HUB_PT750W_HOST", "192.0.2.10")

    async def fake_query(host: str, *, community: str = "public", timeout_s: float = 3.0):
        return "MFG:Brother;CMD:PJL;MDL:PT-P750W;CLS:PRINTER;DES:Brother PT-P750W;"

    monkeypatch.setattr("app.main.query_model_pjl", fake_query)
    from app.printer_models.pt import PTP750WDriver  # noqa: F401  registers

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/healthz")
        assert r.status_code in (200, 404)


async def test_snmp_discovery_fallback_to_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    """SNMP fails but printer_model is configured → fall back, warn, succeed."""
    monkeypatch.setenv("PRINTER_HUB_PRINTER_BACKEND", "mock")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_DISCOVER_VIA_SNMP", "true")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_MODEL", "PT-P750W")
    monkeypatch.setenv("PRINTER_HUB_PT750W_HOST", "192.0.2.10")

    from app.printer_backends.exceptions import SnmpDiscoveryError

    async def fake_query(*_a, **_kw):
        raise SnmpDiscoveryError("timed out")

    monkeypatch.setattr("app.main.query_model_pjl", fake_query)

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/healthz")
        assert r.status_code in (200, 404)


async def test_snmp_discovery_no_fallback_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """SNMP fails AND printer_model is empty → SnmpDiscoveryError propagates."""
    monkeypatch.setenv("PRINTER_HUB_PRINTER_BACKEND", "mock")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_DISCOVER_VIA_SNMP", "true")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_MODEL", "")
    monkeypatch.setenv("PRINTER_HUB_PT750W_HOST", "192.0.2.10")

    from app.printer_backends.exceptions import SnmpDiscoveryError

    async def fake_query(*_a, **_kw):
        raise SnmpDiscoveryError("timed out")

    monkeypatch.setattr("app.main.query_model_pjl", fake_query)

    app = create_app()
    with pytest.raises(SnmpDiscoveryError):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            await c.get("/healthz")
