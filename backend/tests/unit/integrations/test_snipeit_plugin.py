import httpx
import pytest
import respx
from app.integrations.snipeit.plugin import SnipeITNotFoundError, SnipeITPlugin


def test_not_found_error_is_app_lookup_not_found() -> None:
    """All concrete NotFoundErrors must inherit from AppLookupNotFoundError.

    Ensures the aggregator can catch any client's not-found in a single clause.
    """
    from app.integrations.spoolman.plugin import SpoolmanNotFoundError
    from app.services.errors import AppLookupNotFoundError
    from app.services.grocy_client import GrocyNotFoundError

    assert issubclass(SnipeITNotFoundError, AppLookupNotFoundError)
    assert issubclass(GrocyNotFoundError, AppLookupNotFoundError)
    assert issubclass(SpoolmanNotFoundError, AppLookupNotFoundError)


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

    client = SnipeITPlugin(base_url="https://snipe-it.example", api_key="test-key")
    data = await client.lookup("ASSET-12345")

    assert data.title == "MacBook Pro 16"
    assert data.primary_id == "ASSET-12345"
    assert data.qr_payload == "https://snipe-it.example/hardware/123"
    assert data.source_app == "snipeit"
    assert data.secondary == ("S/N: C02XYZ",)


@pytest.mark.asyncio
@respx.mock
async def test_lookup_asset_404_raises_not_found() -> None:
    respx.get("https://snipe-it.example/api/v1/hardware/bytag/UNKNOWN").mock(
        return_value=httpx.Response(404)
    )

    client = SnipeITPlugin(base_url="https://snipe-it.example", api_key="test-key")

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

    client = SnipeITPlugin(base_url="https://snipe-it.example", api_key="test-key")
    data = await client.lookup("A-1")

    assert data.secondary == ()


@pytest.mark.asyncio
@respx.mock
async def test_lookup_strips_trailing_slash_from_base_url() -> None:
    """base_url='https://snipe-it.example/' must not produce a double slash."""
    respx.get("https://snipe-it.example/api/v1/hardware/bytag/A-1").mock(
        return_value=httpx.Response(200, json={"id": 1, "asset_tag": "A-1", "name": "Thing"})
    )
    client = SnipeITPlugin(base_url="https://snipe-it.example/", api_key="test-key")
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
    client = SnipeITPlugin(base_url="https://snipe-it.example", api_key="test-key")
    with pytest.raises(ValueError, match="missing required field 'id'"):
        await client.lookup("A-1")


@pytest.mark.asyncio
@respx.mock
async def test_lookup_5xx_raises_httpx_error() -> None:
    """A 500 from upstream must surface as httpx.HTTPStatusError (no swallowing)."""
    respx.get("https://snipe-it.example/api/v1/hardware/bytag/A-1").mock(
        return_value=httpx.Response(500)
    )
    client = SnipeITPlugin(base_url="https://snipe-it.example", api_key="test-key")
    with pytest.raises(httpx.HTTPStatusError):
        await client.lookup("A-1")


@pytest.mark.asyncio
@respx.mock
async def test_lookup_url_encodes_asset_tag() -> None:
    """Asset tags with special chars (/, ?, space) must be percent-encoded."""
    respx.get("https://snipe-it.example/api/v1/hardware/bytag/A%2F1%20test").mock(
        return_value=httpx.Response(
            200,
            json={"id": 1, "asset_tag": "A/1 test", "name": "Thing"},
        )
    )
    client = SnipeITPlugin(base_url="https://snipe-it.example", api_key="test-key")
    data = await client.lookup("A/1 test")
    assert data.title == "Thing"


@pytest.mark.asyncio
@respx.mock
async def test_lookup_sends_bearer_auth_header() -> None:
    """lookup() must send Authorization: Bearer … and Accept: application/json."""
    route = respx.get("https://snipe-it.example/api/v1/hardware/bytag/A-1").mock(
        return_value=httpx.Response(200, json={"id": 1, "asset_tag": "A-1", "name": "T"})
    )
    client = SnipeITPlugin(base_url="https://snipe-it.example", api_key="secret-key-42")
    await client.lookup("A-1")

    assert route.called
    sent_request = route.calls.last.request
    assert sent_request.headers["Authorization"] == "Bearer secret-key-42"
    assert sent_request.headers["Accept"] == "application/json"
