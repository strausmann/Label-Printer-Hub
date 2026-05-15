"""Tests for AppLookupService — Registry-based dispatch."""

from collections.abc import Generator

import pytest
from app.integrations.registry import IntegrationRegistry
from app.schemas.label_data import LabelData
from app.services.lookup_service import AppLookupService, UnknownAppError


class _StubPlugin:
    def __init__(self, name: str) -> None:
        self.name = name
        self.display_name = name.title()

    async def lookup(self, identifier: str) -> LabelData:
        return LabelData(
            title=f"stub-{self.name}",
            primary_id=identifier,
            qr_payload=f"https://example/{identifier}",
            source_app=self.name,
        )


@pytest.fixture(autouse=True)
def _populate_registry() -> Generator[None, None, None]:
    IntegrationRegistry._plugins.clear()
    IntegrationRegistry.register(_StubPlugin("snipeit"))
    IntegrationRegistry.register(_StubPlugin("spoolman"))
    IntegrationRegistry.register(_StubPlugin("grocy"))
    yield
    IntegrationRegistry._plugins.clear()


@pytest.mark.asyncio
async def test_lookup_dispatches_to_registered_plugin() -> None:
    svc = AppLookupService()
    result = await svc.lookup("snipeit", "ASSET-1")
    assert result.source_app == "snipeit"
    assert result.primary_id == "ASSET-1"


@pytest.mark.asyncio
async def test_lookup_routes_grocy() -> None:
    svc = AppLookupService()
    result = await svc.lookup("grocy", "42")
    assert result.source_app == "grocy"
    assert result.primary_id == "42"


@pytest.mark.asyncio
async def test_lookup_routes_spoolman() -> None:
    svc = AppLookupService()
    result = await svc.lookup("spoolman", "7")
    assert result.source_app == "spoolman"
    assert result.primary_id == "7"


@pytest.mark.asyncio
async def test_lookup_unknown_app_raises_unknownapperror() -> None:
    svc = AppLookupService()
    with pytest.raises(UnknownAppError, match="nope"):
        await svc.lookup("nope", "x")


@pytest.mark.asyncio
async def test_lookup_propagates_app_lookup_not_found_unchanged() -> None:
    """AppLookupNotFoundError from a plugin must propagate — the service does not swallow it."""
    from app.services.errors import AppLookupNotFoundError

    class _RaisingPlugin:
        name = "failing"
        display_name = "Failing"

        async def lookup(self, identifier: str) -> LabelData:
            raise AppLookupNotFoundError(f"Entity {identifier!r} not found")

    IntegrationRegistry.register(_RaisingPlugin())
    svc = AppLookupService()

    with pytest.raises(AppLookupNotFoundError, match="X"):
        await svc.lookup("failing", "X")


def test_available_apps_reflects_registry() -> None:
    assert AppLookupService().available_apps == ["grocy", "snipeit", "spoolman"]


def test_unknown_app_error_does_not_inherit_from_app_lookup_not_found() -> None:
    """UnknownAppError is a configuration mismatch, NOT an entity-not-found."""
    from app.services.errors import AppLookupNotFoundError

    assert not issubclass(UnknownAppError, AppLookupNotFoundError)
