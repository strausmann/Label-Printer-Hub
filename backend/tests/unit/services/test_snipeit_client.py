import httpx
import pytest
import respx
from app.services.snipeit_client import SnipeITClient, SnipeITNotFoundError


@pytest.mark.asyncio
@respx.mock
async def test_lookup_asset_returns_label_data() -> None:
    respx.get("https://snipe-it.example/api/v1/hardware/bytag/ASSET-12345").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 123,
                "asset_tag": "ASSET-12345",
                "name": "MacBook Pro 16",
                "serial": "C02XYZ",
            },
        )
    )

    client = SnipeITClient(base_url="https://snipe-it.example", api_key="test-key")
    data = await client.lookup("ASSET-12345")

    assert data.title == "MacBook Pro 16"
    assert data.primary_id == "ASSET-12345"
    assert data.qr_payload == "https://snipe-it.example/hardware/123"
    assert data.source_app == "snipeit"
    assert data.secondary == ["S/N: C02XYZ"]


@pytest.mark.asyncio
@respx.mock
async def test_lookup_asset_404_raises_not_found() -> None:
    respx.get("https://snipe-it.example/api/v1/hardware/bytag/UNKNOWN").mock(
        return_value=httpx.Response(404)
    )

    client = SnipeITClient(base_url="https://snipe-it.example", api_key="test-key")

    with pytest.raises(SnipeITNotFoundError, match="UNKNOWN"):
        await client.lookup("UNKNOWN")


@pytest.mark.asyncio
@respx.mock
async def test_lookup_asset_without_serial_has_no_secondary_line() -> None:
    """Missing optional serial field must not add a 'S/N: None' line."""
    respx.get("https://snipe-it.example/api/v1/hardware/bytag/A-1").mock(
        return_value=httpx.Response(
            200,
            json={"id": 1, "asset_tag": "A-1", "name": "Thing"},
        )
    )

    client = SnipeITClient(base_url="https://snipe-it.example", api_key="test-key")
    data = await client.lookup("A-1")

    assert data.secondary == []


@pytest.mark.asyncio
@respx.mock
async def test_lookup_strips_trailing_slash_from_base_url() -> None:
    """base_url='https://snipe-it.example/' must not produce a double slash."""
    respx.get("https://snipe-it.example/api/v1/hardware/bytag/A-1").mock(
        return_value=httpx.Response(200, json={"id": 1, "asset_tag": "A-1", "name": "Thing"})
    )
    client = SnipeITClient(base_url="https://snipe-it.example/", api_key="test-key")
    data = await client.lookup("A-1")
    assert data.qr_payload == "https://snipe-it.example/hardware/1"


@pytest.mark.asyncio
@respx.mock
async def test_lookup_missing_id_raises_value_error() -> None:
    """Snipe-IT response without 'id' field must fail loudly.

    Regression guard: must not silently produce …/hardware/None.
    """
    respx.get("https://snipe-it.example/api/v1/hardware/bytag/A-1").mock(
        return_value=httpx.Response(
            200,
            json={"asset_tag": "A-1", "name": "Broken Asset"},  # no 'id'
        )
    )
    client = SnipeITClient(base_url="https://snipe-it.example", api_key="test-key")
    with pytest.raises(ValueError, match="missing required field 'id'"):
        await client.lookup("A-1")


@pytest.mark.asyncio
@respx.mock
async def test_lookup_5xx_raises_httpx_error() -> None:
    """A 500 from upstream must surface as httpx.HTTPStatusError (no swallowing)."""
    respx.get("https://snipe-it.example/api/v1/hardware/bytag/A-1").mock(
        return_value=httpx.Response(500)
    )
    client = SnipeITClient(base_url="https://snipe-it.example", api_key="test-key")
    with pytest.raises(httpx.HTTPStatusError):
        await client.lookup("A-1")
