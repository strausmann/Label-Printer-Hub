import httpx
import pytest
import respx
from app.services.spoolman_client import SpoolmanClient, SpoolmanNotFoundError


@pytest.mark.asyncio
@respx.mock
async def test_lookup_spool_returns_label_data() -> None:
    respx.get("https://spoolman.example/api/v1/spool/42").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 42,
                "filament": {
                    "vendor": {"name": "BambuLab"},
                    "name": "PLA Black",
                    "color_hex": "000000",
                },
                "remaining_weight": 850.5,
            },
        )
    )
    client = SpoolmanClient(base_url="https://spoolman.example")
    data = await client.lookup("42")

    assert data.title == "BambuLab PLA Black"
    assert data.primary_id == "#42"
    assert data.qr_payload == "https://spoolman.example/spool/show/42"
    assert data.source_app == "spoolman"
    assert data.secondary == ("851g remaining",)


@pytest.mark.asyncio
@respx.mock
async def test_lookup_spool_404_raises() -> None:
    respx.get("https://spoolman.example/api/v1/spool/999").mock(return_value=httpx.Response(404))
    client = SpoolmanClient(base_url="https://spoolman.example")
    with pytest.raises(SpoolmanNotFoundError, match="999"):
        await client.lookup("999")


@pytest.mark.asyncio
@respx.mock
async def test_lookup_spool_without_remaining_weight() -> None:
    respx.get("https://spoolman.example/api/v1/spool/1").mock(
        return_value=httpx.Response(
            200,
            json={"id": 1, "filament": {"vendor": {"name": "V"}, "name": "M"}},
        )
    )
    client = SpoolmanClient(base_url="https://spoolman.example")
    data = await client.lookup("1")
    assert data.secondary == ()


@pytest.mark.asyncio
@respx.mock
async def test_lookup_spool_with_missing_vendor_name() -> None:
    respx.get("https://spoolman.example/api/v1/spool/1").mock(
        return_value=httpx.Response(
            200,
            json={"id": 1, "filament": {"name": "PLA"}},
        )
    )
    client = SpoolmanClient(base_url="https://spoolman.example")
    data = await client.lookup("1")
    assert data.title == "Unknown PLA"


@pytest.mark.asyncio
@respx.mock
async def test_lookup_strips_trailing_slash() -> None:
    respx.get("https://spoolman.example/api/v1/spool/7").mock(
        return_value=httpx.Response(
            200, json={"id": 7, "filament": {"vendor": {"name": "V"}, "name": "M"}}
        )
    )
    client = SpoolmanClient(base_url="https://spoolman.example/")
    data = await client.lookup("7")
    assert data.qr_payload == "https://spoolman.example/spool/show/7"


@pytest.mark.asyncio
@respx.mock
async def test_lookup_url_encodes_spool_id() -> None:
    respx.get("https://spoolman.example/api/v1/spool/A%2F1").mock(
        return_value=httpx.Response(
            200, json={"id": 1, "filament": {"vendor": {"name": "V"}, "name": "M"}}
        )
    )
    client = SpoolmanClient(base_url="https://spoolman.example")
    data = await client.lookup("A/1")
    # If encoding worked the mock matched and we got LabelData back.
    assert data.source_app == "spoolman"
    assert data.primary_id == "#1"


@pytest.mark.asyncio
@respx.mock
async def test_lookup_5xx_raises_httpx_error() -> None:
    respx.get("https://spoolman.example/api/v1/spool/1").mock(return_value=httpx.Response(503))
    client = SpoolmanClient(base_url="https://spoolman.example")
    with pytest.raises(httpx.HTTPStatusError):
        await client.lookup("1")


@pytest.mark.asyncio
@respx.mock
async def test_lookup_missing_id_raises_value_error() -> None:
    respx.get("https://spoolman.example/api/v1/spool/1").mock(
        return_value=httpx.Response(200, json={"filament": {"vendor": {"name": "V"}, "name": "M"}})
    )
    client = SpoolmanClient(base_url="https://spoolman.example")
    with pytest.raises(ValueError, match="missing required field 'id'"):
        await client.lookup("1")


@pytest.mark.asyncio
@respx.mock
async def test_lookup_spool_with_null_filament() -> None:
    """Spoolman with filament: null must produce 'Unknown Unknown' title without crashing."""
    respx.get("https://spoolman.example/api/v1/spool/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "filament": None})
    )
    client = SpoolmanClient(base_url="https://spoolman.example")
    data = await client.lookup("1")
    assert data.title == "Unknown Unknown"


@pytest.mark.asyncio
@respx.mock
async def test_lookup_sends_no_auth_header() -> None:
    """Spoolman intentionally requires no auth — verify no Authorization header."""
    route = respx.get("https://spoolman.example/api/v1/spool/1").mock(
        return_value=httpx.Response(
            200, json={"id": 1, "filament": {"vendor": {"name": "V"}, "name": "M"}}
        )
    )
    client = SpoolmanClient(base_url="https://spoolman.example")
    await client.lookup("1")

    assert route.called
    sent = route.calls.last.request
    assert "Authorization" not in sent.headers
    assert "GROCY-API-KEY" not in sent.headers
    assert sent.headers["Accept"] == "application/json"
