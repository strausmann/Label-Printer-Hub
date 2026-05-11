from unittest.mock import AsyncMock, MagicMock

import pytest
from app.schemas.label_data import LabelData
from app.services.errors import AppLookupNotFoundError
from app.services.lookup_service import (
    AVAILABLE_APPS,
    AppLookupService,
    UnknownAppError,
)


def _make_service(
    *,
    snipeit: MagicMock | None = None,
    grocy: MagicMock | None = None,
    spoolman: MagicMock | None = None,
) -> AppLookupService:
    """Build a service with MagicMock defaults — tests override what they need."""
    return AppLookupService(
        snipeit=snipeit or MagicMock(),
        grocy=grocy or MagicMock(),
        spoolman=spoolman or MagicMock(),
    )


@pytest.mark.asyncio
async def test_lookup_routes_snipeit() -> None:
    snipeit = MagicMock()
    snipeit.lookup = AsyncMock(
        return_value=LabelData(
            title="MacBook",
            primary_id="ASSET-1",
            qr_payload="https://snipe.example/h/1",
            source_app="snipeit",
        )
    )
    service = _make_service(snipeit=snipeit)

    data = await service.lookup("snipeit", "ASSET-1")

    snipeit.lookup.assert_awaited_once_with("ASSET-1")
    assert data.title == "MacBook"


@pytest.mark.asyncio
async def test_lookup_routes_grocy() -> None:
    grocy = MagicMock()
    grocy.lookup = AsyncMock(
        return_value=LabelData(title="Milch", primary_id="42", qr_payload="x", source_app="grocy")
    )
    service = _make_service(grocy=grocy)

    data = await service.lookup("grocy", "42")

    grocy.lookup.assert_awaited_once_with("42")
    assert data.title == "Milch"


@pytest.mark.asyncio
async def test_lookup_routes_spoolman() -> None:
    spoolman = MagicMock()
    spoolman.lookup = AsyncMock(
        return_value=LabelData(
            title="BambuLab PLA", primary_id="#7", qr_payload="x", source_app="spoolman"
        )
    )
    service = _make_service(spoolman=spoolman)

    data = await service.lookup("spoolman", "7")

    spoolman.lookup.assert_awaited_once_with("7")
    assert data.title == "BambuLab PLA"


@pytest.mark.asyncio
async def test_lookup_unknown_app_raises_unknown_app_error() -> None:
    service = _make_service()

    with pytest.raises(UnknownAppError, match="bogus"):
        await service.lookup("bogus", "x")


@pytest.mark.asyncio
async def test_unknown_app_error_message_lists_available_apps() -> None:
    service = _make_service()

    with pytest.raises(UnknownAppError) as excinfo:
        await service.lookup("bogus", "x")

    msg = str(excinfo.value)
    for app in AVAILABLE_APPS:
        assert app in msg, f"Expected {app} in error message, got: {msg}"


@pytest.mark.asyncio
async def test_lookup_propagates_app_lookup_not_found_unchanged() -> None:
    """AppLookupNotFoundError from a client must propagate — the aggregator does not swallow it."""
    snipeit = MagicMock()
    snipeit.lookup = AsyncMock(side_effect=AppLookupNotFoundError("Asset 'X' not found"))
    service = _make_service(snipeit=snipeit)

    with pytest.raises(AppLookupNotFoundError, match="X"):
        await service.lookup("snipeit", "X")


def test_available_apps_constant_matches_registered_clients() -> None:
    """The exported AVAILABLE_APPS constant must agree with the actual registry."""
    service = _make_service()
    assert set(service.available_apps) == set(AVAILABLE_APPS)


def test_unknown_app_error_does_not_inherit_from_app_lookup_not_found() -> None:
    """UnknownAppError is a configuration mismatch, NOT an entity-not-found.

    The aggregator's clients raise AppLookupNotFoundError for missing entities.
    UnknownAppError is operationally distinct (caller bug, not data state) and
    must not be confused with it.
    """
    assert not issubclass(UnknownAppError, AppLookupNotFoundError)
