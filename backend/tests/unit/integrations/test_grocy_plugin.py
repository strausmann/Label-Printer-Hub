import httpx
import pytest
import respx
from app.integrations.grocy.plugin import GrocyNotFoundError, GrocyPlugin

# ---------------------------------------------------------------------------
# Settings fixture
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _stub_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the plugin at a fake host. respx mocks the actual HTTP."""
    monkeypatch.setenv("PRINTER_HUB_GROCY_URL", "https://grocy.example")
    monkeypatch.setenv("PRINTER_HUB_GROCY_API_KEY", "grocy-key")
    monkeypatch.setenv("PRINTER_HUB_GROCY_TIMEOUT", "5.0")
    from app.config import get_settings
    get_settings.cache_clear()


@pytest.mark.asyncio
@respx.mock
async def test_lookup_product_returns_label_data() -> None:
    respx.get("https://grocy.example/api/objects/products/42").mock(
        return_value=httpx.Response(
            200,
            json={"id": 42, "name": "Milch 1L", "description": "Vollmilch H-Milch"},
        )
    )

    client = GrocyPlugin()
    data = await client.lookup("42")

    assert data.title == "Milch 1L"
    assert data.primary_id == "42"
    assert data.qr_payload == "https://grocy.example/product/42"
    assert data.source_app == "grocy"
    assert data.secondary == ()


@pytest.mark.asyncio
@respx.mock
async def test_lookup_product_400_raises_not_found() -> None:
    """Grocy returns 400 (not 404) for missing products — special-cased."""
    respx.get("https://grocy.example/api/objects/products/999").mock(
        return_value=httpx.Response(400, json={"error_message": "No such product"})
    )
    client = GrocyPlugin()
    with pytest.raises(GrocyNotFoundError, match="999"):
        await client.lookup("999")


@pytest.mark.asyncio
@respx.mock
async def test_lookup_product_404_also_raises_not_found() -> None:
    """A future Grocy version returning a proper 404 must also map to GrocyNotFoundError."""
    respx.get("https://grocy.example/api/objects/products/999").mock(
        return_value=httpx.Response(404)
    )
    client = GrocyPlugin()
    with pytest.raises(GrocyNotFoundError):
        await client.lookup("999")


@pytest.mark.asyncio
@respx.mock
async def test_lookup_strips_trailing_slash_from_base_url() -> None:
    respx.get("https://grocy.example/api/objects/products/7").mock(
        return_value=httpx.Response(200, json={"id": 7, "name": "X"})
    )
    import os
    os.environ["PRINTER_HUB_GROCY_URL"] = "https://grocy.example/"
    from app.config import get_settings
    get_settings.cache_clear()
    client = GrocyPlugin()
    data = await client.lookup("7")
    assert data.qr_payload == "https://grocy.example/product/7"


@pytest.mark.asyncio
@respx.mock
async def test_lookup_url_encodes_product_id() -> None:
    respx.get("https://grocy.example/api/objects/products/A%2F1").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "Encoded"})
    )
    client = GrocyPlugin()
    data = await client.lookup("A/1")
    assert data.title == "Encoded"


@pytest.mark.asyncio
@respx.mock
async def test_lookup_5xx_raises_httpx_error() -> None:
    respx.get("https://grocy.example/api/objects/products/1").mock(return_value=httpx.Response(500))
    client = GrocyPlugin()
    with pytest.raises(httpx.HTTPStatusError):
        await client.lookup("1")


@pytest.mark.asyncio
@respx.mock
async def test_lookup_missing_id_raises_value_error() -> None:
    """Grocy response without 'id' field must fail loudly."""
    respx.get("https://grocy.example/api/objects/products/1").mock(
        return_value=httpx.Response(200, json={"name": "Broken"})  # no id
    )
    client = GrocyPlugin()
    with pytest.raises(ValueError, match="missing required field 'id'"):
        await client.lookup("1")


@pytest.mark.asyncio
@respx.mock
async def test_lookup_sends_grocy_api_key_header() -> None:
    """Outgoing request must carry GROCY-API-KEY header (not Bearer)."""
    import os
    os.environ["PRINTER_HUB_GROCY_API_KEY"] = "my-grocy-key-42"
    from app.config import get_settings
    get_settings.cache_clear()

    route = respx.get("https://grocy.example/api/objects/products/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "x"})
    )
    client = GrocyPlugin()
    await client.lookup("1")

    assert route.called
    sent = route.calls.last.request
    assert sent.headers["GROCY-API-KEY"] == "my-grocy-key-42"
    assert sent.headers["Accept"] == "application/json"
    # Crucially: NO Authorization header — Grocy doesn't use Bearer.
    assert "Authorization" not in sent.headers
