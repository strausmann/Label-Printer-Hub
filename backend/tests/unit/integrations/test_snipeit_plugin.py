from unittest.mock import patch

import httpx
import pytest
import respx
from app.integrations.snipeit.plugin import SnipeITNotFoundError, SnipeITPlugin

from tests.unit.integrations._bound import bound

# ---------------------------------------------------------------------------
# Settings fixture — env vars are read by the plugin constructor via get_settings()
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _stub_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the plugin at a fake host. respx mocks the actual HTTP."""
    monkeypatch.setenv("PRINTER_HUB_SNIPEIT_URL", "https://snipe-it.example")
    monkeypatch.setenv("PRINTER_HUB_SNIPEIT_API_KEY", "test-key")
    monkeypatch.setenv("PRINTER_HUB_SNIPEIT_TIMEOUT", "5.0")
    # Clear the lru_cache so the plugin picks up the patched env vars.
    from app.config import get_settings

    get_settings.cache_clear()


def test_not_found_error_is_app_lookup_not_found() -> None:
    """All concrete NotFoundErrors must inherit from AppLookupNotFoundError.

    Ensures the aggregator can catch any client's not-found in a single clause.
    """
    from app.integrations.grocy.plugin import GrocyNotFoundError
    from app.integrations.spoolman.plugin import SpoolmanNotFoundError
    from app.services.errors import AppLookupNotFoundError

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

    client = bound(SnipeITPlugin)
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

    client = bound(SnipeITPlugin)

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

    client = bound(SnipeITPlugin)
    data = await client.lookup("A-1")

    assert data.secondary == ()


@pytest.mark.asyncio
@respx.mock
async def test_lookup_strips_trailing_slash_from_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """base_url='https://snipe-it.example/' must not produce a double slash."""
    respx.get("https://snipe-it.example/api/v1/hardware/bytag/A-1").mock(
        return_value=httpx.Response(200, json={"id": 1, "asset_tag": "A-1", "name": "Thing"})
    )
    # Trailing slash is injected via env var — the plugin must strip it.
    from app.config import get_settings

    monkeypatch.setenv("PRINTER_HUB_SNIPEIT_URL", "https://snipe-it.example/")
    get_settings.cache_clear()
    client = bound(SnipeITPlugin)
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
    client = bound(SnipeITPlugin)
    with pytest.raises(ValueError, match="missing required field 'id'"):
        await client.lookup("A-1")


@pytest.mark.asyncio
@respx.mock
async def test_lookup_5xx_raises_httpx_error() -> None:
    """A 500 from upstream must surface as httpx.HTTPStatusError (no swallowing)."""
    respx.get("https://snipe-it.example/api/v1/hardware/bytag/A-1").mock(
        return_value=httpx.Response(500)
    )
    client = bound(SnipeITPlugin)
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
    client = bound(SnipeITPlugin)
    data = await client.lookup("A/1 test")
    assert data.title == "Thing"


@pytest.mark.asyncio
@respx.mock
async def test_lookup_sends_bearer_auth_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """lookup() must send Authorization: Bearer … and Accept: application/json."""
    from app.config import get_settings

    monkeypatch.setenv("PRINTER_HUB_SNIPEIT_API_KEY", "secret-key-42")
    get_settings.cache_clear()

    route = respx.get("https://snipe-it.example/api/v1/hardware/bytag/A-1").mock(
        return_value=httpx.Response(200, json={"id": 1, "asset_tag": "A-1", "name": "T"})
    )
    client = bound(SnipeITPlugin)
    await client.lookup("A-1")

    assert route.called
    sent_request = route.calls.last.request
    assert sent_request.headers["Authorization"] == "Bearer secret-key-42"
    assert sent_request.headers["Accept"] == "application/json"


@pytest.mark.asyncio
@respx.mock
async def test_lookup_reuses_http_client_across_calls() -> None:
    """The plugin must reuse a single AsyncClient — no new connection per lookup().

    Two consecutive lookups must use the SAME AsyncClient instance so TCP/TLS
    connections are pooled rather than re-established on every call.
    """
    respx.get("https://snipe-it.example/api/v1/hardware/bytag/A-1").mock(
        return_value=httpx.Response(200, json={"id": 1, "asset_tag": "A-1", "name": "T"})
    )
    respx.get("https://snipe-it.example/api/v1/hardware/bytag/A-2").mock(
        return_value=httpx.Response(200, json={"id": 2, "asset_tag": "A-2", "name": "U"})
    )

    instances: list[httpx.AsyncClient] = []
    real_init = httpx.AsyncClient.__init__

    def capturing_init(self: httpx.AsyncClient, *args: object, **kwargs: object) -> None:
        real_init(self, *args, **kwargs)
        instances.append(self)

    with patch.object(httpx.AsyncClient, "__init__", capturing_init):
        plugin = bound(SnipeITPlugin)
        await plugin.lookup("A-1")
        await plugin.lookup("A-2")

    await plugin.aclose()

    assert len(instances) == 1, (
        f"Expected exactly one AsyncClient to be created (connection pooling), "
        f"but {len(instances)} were created"
    )


# ---------------------------------------------------------------------------
# E-INT: locations (`loc:<id>`) and numeric asset ids
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_lookup_location_by_loc_prefix() -> None:
    route = respx.get("https://snipe-it.example/api/v1/locations/17").mock(
        return_value=httpx.Response(
            200, json={"id": 17, "name": "Basement shelf 3", "address": "Cellar"}
        )
    )
    data = await bound(SnipeITPlugin).lookup("loc:17")

    assert route.called
    assert data.title == "Basement shelf 3"
    assert data.primary_id == "loc:17"
    assert data.qr_payload == "https://snipe-it.example/locations/17"
    assert data.source_app == "snipeit"
    assert data.secondary == ("Cellar",)


@pytest.mark.asyncio
@respx.mock
async def test_lookup_location_never_touches_the_asset_endpoints() -> None:
    respx.get("https://snipe-it.example/api/v1/locations/3").mock(
        return_value=httpx.Response(200, json={"id": 3, "name": "Rack"})
    )
    asset = respx.get(url__regex=r"https://snipe-it\.example/api/v1/hardware/.*")
    await bound(SnipeITPlugin).lookup("loc:3")
    assert not asset.called


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(404),
        httpx.Response(200, json={"status": "error", "messages": "Location does not exist."}),
    ],
)
async def test_lookup_unknown_location_raises_not_found(response: httpx.Response) -> None:
    respx.get("https://snipe-it.example/api/v1/locations/99").mock(return_value=response)
    with pytest.raises(SnipeITNotFoundError, match="99"):
        await bound(SnipeITPlugin).lookup("loc:99")


@pytest.mark.asyncio
@respx.mock
async def test_lookup_location_5xx_raises_httpx_error() -> None:
    respx.get("https://snipe-it.example/api/v1/locations/1").mock(return_value=httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        await bound(SnipeITPlugin).lookup("loc:1")


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("bad", ["loc:", "loc:abc", "loc:1/2", "loc:-4"])
async def test_lookup_location_with_a_malformed_id_is_not_found_without_a_request(bad: str) -> None:
    anything = respx.route().mock(return_value=httpx.Response(200, json={"id": 1}))
    with pytest.raises(SnipeITNotFoundError):
        await bound(SnipeITPlugin).lookup(bad)
    assert not anything.called


@pytest.mark.asyncio
@respx.mock
async def test_lookup_numeric_value_falls_back_to_the_asset_id() -> None:
    respx.get("https://snipe-it.example/api/v1/hardware/bytag/42").mock(
        return_value=httpx.Response(
            200, json={"status": "error", "messages": "Asset does not exist."}
        )
    )
    by_id = respx.get("https://snipe-it.example/api/v1/hardware/42").mock(
        return_value=httpx.Response(200, json={"id": 42, "asset_tag": "HH-0042", "name": "Drill"})
    )
    data = await bound(SnipeITPlugin).lookup("42")

    assert by_id.called
    assert data.title == "Drill"
    assert data.qr_payload == "https://snipe-it.example/hardware/42"


@pytest.mark.asyncio
@respx.mock
async def test_lookup_numeric_asset_tag_wins_over_the_id() -> None:
    respx.get("https://snipe-it.example/api/v1/hardware/bytag/1001").mock(
        return_value=httpx.Response(200, json={"id": 7, "asset_tag": "1001", "name": "Tagged"})
    )
    by_id = respx.get("https://snipe-it.example/api/v1/hardware/1001")
    data = await bound(SnipeITPlugin).lookup("1001")

    assert data.title == "Tagged"
    assert not by_id.called


@pytest.mark.asyncio
@respx.mock
async def test_lookup_numeric_unknown_everywhere_is_not_found() -> None:
    respx.get("https://snipe-it.example/api/v1/hardware/bytag/5").mock(
        return_value=httpx.Response(404)
    )
    respx.get("https://snipe-it.example/api/v1/hardware/5").mock(return_value=httpx.Response(404))
    with pytest.raises(SnipeITNotFoundError, match="5"):
        await bound(SnipeITPlugin).lookup("5")


@pytest.mark.asyncio
@respx.mock
async def test_lookup_non_numeric_tag_never_tries_the_id_endpoint() -> None:
    respx.get("https://snipe-it.example/api/v1/hardware/bytag/NOPE").mock(
        return_value=httpx.Response(404)
    )
    by_id = respx.get("https://snipe-it.example/api/v1/hardware/NOPE")
    with pytest.raises(SnipeITNotFoundError):
        await bound(SnipeITPlugin).lookup("NOPE")
    assert not by_id.called
