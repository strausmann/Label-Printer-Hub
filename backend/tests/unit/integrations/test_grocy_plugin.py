# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

from unittest.mock import patch

import httpx
import pytest
import respx
from app.integrations.grocy.plugin import GrocyNotFoundError, GrocyPlugin

from tests.unit.integrations._bound import bound

# ---------------------------------------------------------------------------
# Settings fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _stub_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the plugin at a fake host. respx mocks the actual HTTP."""
    monkeypatch.setenv("LABELYARD_GROCY_URL", "https://grocy.example")
    monkeypatch.setenv("LABELYARD_GROCY_API_KEY", "grocy-key")
    monkeypatch.setenv("LABELYARD_GROCY_TIMEOUT", "5.0")
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

    client = bound(GrocyPlugin)
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
    # A digits-only value is then tried as a barcode (E-INT); unknown there too.
    respx.get("https://grocy.example/api/stock/products/by-barcode/999").mock(
        return_value=httpx.Response(400, json={"error_message": "Unknown barcode"})
    )
    client = bound(GrocyPlugin)
    with pytest.raises(GrocyNotFoundError, match="999"):
        await client.lookup("999")


@pytest.mark.asyncio
@respx.mock
async def test_lookup_product_404_also_raises_not_found() -> None:
    """A future Grocy version returning a proper 404 must also map to GrocyNotFoundError."""
    respx.get("https://grocy.example/api/objects/products/999").mock(
        return_value=httpx.Response(404)
    )
    respx.get("https://grocy.example/api/stock/products/by-barcode/999").mock(
        return_value=httpx.Response(404)
    )
    client = bound(GrocyPlugin)
    with pytest.raises(GrocyNotFoundError):
        await client.lookup("999")


@pytest.mark.asyncio
@respx.mock
async def test_lookup_strips_trailing_slash_from_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    respx.get("https://grocy.example/api/objects/products/7").mock(
        return_value=httpx.Response(200, json={"id": 7, "name": "X"})
    )
    from app.config import get_settings

    monkeypatch.setenv("LABELYARD_GROCY_URL", "https://grocy.example/")
    get_settings.cache_clear()
    client = bound(GrocyPlugin)
    data = await client.lookup("7")
    assert data.qr_payload == "https://grocy.example/product/7"


@pytest.mark.asyncio
@respx.mock
async def test_lookup_url_encodes_product_id() -> None:
    # A non-numeric value is a barcode (E-INT) and is percent-encoded the same way.
    respx.get("https://grocy.example/api/stock/products/by-barcode/A-1_x").mock(
        return_value=httpx.Response(200, json={"product": {"id": 1, "name": "Encoded"}})
    )
    client = bound(GrocyPlugin)
    data = await client.lookup("A-1_x")
    assert data.title == "Encoded"


@pytest.mark.asyncio
@respx.mock
async def test_lookup_5xx_raises_httpx_error() -> None:
    respx.get("https://grocy.example/api/objects/products/1").mock(return_value=httpx.Response(500))
    client = bound(GrocyPlugin)
    with pytest.raises(httpx.HTTPStatusError):
        await client.lookup("1")


@pytest.mark.asyncio
@respx.mock
async def test_lookup_missing_id_raises_value_error() -> None:
    """Grocy response without 'id' field must fail loudly."""
    respx.get("https://grocy.example/api/objects/products/1").mock(
        return_value=httpx.Response(200, json={"name": "Broken"})  # no id
    )
    client = bound(GrocyPlugin)
    with pytest.raises(ValueError, match="missing required field 'id'"):
        await client.lookup("1")


@pytest.mark.asyncio
@respx.mock
async def test_lookup_sends_grocy_api_key_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """Outgoing request must carry GROCY-API-KEY header (not Bearer)."""
    from app.config import get_settings

    monkeypatch.setenv("LABELYARD_GROCY_API_KEY", "my-grocy-key-42")
    get_settings.cache_clear()

    route = respx.get("https://grocy.example/api/objects/products/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "x"})
    )
    client = bound(GrocyPlugin)
    await client.lookup("1")

    assert route.called
    sent = route.calls.last.request
    assert sent.headers["GROCY-API-KEY"] == "my-grocy-key-42"
    assert sent.headers["Accept"] == "application/json"
    # Crucially: NO Authorization header — Grocy doesn't use Bearer.
    assert "Authorization" not in sent.headers


@pytest.mark.asyncio
@respx.mock
async def test_lookup_reuses_http_client_across_calls() -> None:
    """The plugin must reuse a single AsyncClient — no new connection per lookup().

    Two consecutive lookups must use the SAME AsyncClient instance so TCP/TLS
    connections are pooled rather than re-established on every call.
    """
    respx.get("https://grocy.example/api/objects/products/10").mock(
        return_value=httpx.Response(200, json={"id": 10, "name": "Apfel"})
    )
    respx.get("https://grocy.example/api/objects/products/11").mock(
        return_value=httpx.Response(200, json={"id": 11, "name": "Birne"})
    )

    instances: list[httpx.AsyncClient] = []
    real_init = httpx.AsyncClient.__init__

    def capturing_init(self: httpx.AsyncClient, *args: object, **kwargs: object) -> None:
        real_init(self, *args, **kwargs)
        instances.append(self)

    with patch.object(httpx.AsyncClient, "__init__", capturing_init):
        plugin = bound(GrocyPlugin)
        await plugin.lookup("10")
        await plugin.lookup("11")

    await plugin.aclose()

    assert len(instances) == 1, (
        f"Expected exactly one AsyncClient to be created (connection pooling), "
        f"but {len(instances)} were created"
    )


# ---------------------------------------------------------------------------
# E-INT: barcode lookup (GET /api/stock/products/by-barcode/{barcode}; verified
# against Grocy's own grocy.openapi.json: 200 ProductDetailsResponse, 400 Unknown barcode)
# ---------------------------------------------------------------------------

_DETAILS = {"product": {"id": 118, "name": "Oat flakes"}, "stock_amount": "2"}


@pytest.mark.asyncio
@respx.mock
async def test_lookup_non_numeric_value_is_a_barcode() -> None:
    route = respx.get("https://grocy.example/api/stock/products/by-barcode/OFF-4001").mock(
        return_value=httpx.Response(200, json=_DETAILS)
    )
    by_id = respx.get(url__regex=r"https://grocy\.example/api/objects/products/.*")
    data = await bound(GrocyPlugin).lookup("OFF-4001")

    assert route.called and not by_id.called
    assert route.calls.last.request.headers["GROCY-API-KEY"] == "grocy-key"
    assert data.title == "Oat flakes"
    assert data.primary_id == "118"
    assert data.qr_payload == "https://grocy.example/product/118"


@pytest.mark.asyncio
@respx.mock
async def test_lookup_numeric_value_is_an_id_first() -> None:
    by_id = respx.get("https://grocy.example/api/objects/products/118").mock(
        return_value=httpx.Response(200, json={"id": 118, "name": "Oat flakes"})
    )
    barcode = respx.get(url__regex=r"https://grocy\.example/api/stock/products/by-barcode/.*")
    data = await bound(GrocyPlugin).lookup("118")

    assert by_id.called and not barcode.called
    assert data.primary_id == "118"


@pytest.mark.asyncio
@respx.mock
async def test_lookup_numeric_barcode_falls_back_after_an_unknown_id() -> None:
    """An EAN is a pure integer too: no product has that id, so it is tried as a barcode."""
    respx.get("https://grocy.example/api/objects/products/4001234567890").mock(
        return_value=httpx.Response(400, json={"error_message": "No such product"})
    )
    route = respx.get("https://grocy.example/api/stock/products/by-barcode/4001234567890").mock(
        return_value=httpx.Response(200, json=_DETAILS)
    )
    data = await bound(GrocyPlugin).lookup("4001234567890")

    assert route.called
    assert data.title == "Oat flakes"


@pytest.mark.asyncio
@respx.mock
async def test_lookup_unknown_barcode_raises_not_found() -> None:
    respx.get("https://grocy.example/api/stock/products/by-barcode/NOPE").mock(
        return_value=httpx.Response(400, json={"error_message": "Unknown barcode"})
    )
    with pytest.raises(GrocyNotFoundError, match="NOPE"):
        await bound(GrocyPlugin).lookup("NOPE")


@pytest.mark.asyncio
@respx.mock
async def test_lookup_numeric_unknown_in_both_ways_raises_not_found() -> None:
    respx.get("https://grocy.example/api/objects/products/777").mock(
        return_value=httpx.Response(400)
    )
    respx.get("https://grocy.example/api/stock/products/by-barcode/777").mock(
        return_value=httpx.Response(400)
    )
    with pytest.raises(GrocyNotFoundError, match="777"):
        await bound(GrocyPlugin).lookup("777")


@pytest.mark.asyncio
@respx.mock
async def test_lookup_barcode_5xx_surfaces() -> None:
    respx.get("https://grocy.example/api/stock/products/by-barcode/A-1").mock(
        return_value=httpx.Response(500)
    )
    with pytest.raises(httpx.HTTPStatusError):
        await bound(GrocyPlugin).lookup("A-1")


@pytest.mark.asyncio
@respx.mock
async def test_lookup_barcode_response_without_a_product_id_fails_loudly() -> None:
    respx.get("https://grocy.example/api/stock/products/by-barcode/X1").mock(
        return_value=httpx.Response(200, json={"product": {"name": "No id"}})
    )
    with pytest.raises(ValueError, match="missing required field 'id'"):
        await bound(GrocyPlugin).lookup("X1")


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "bad",
    [
        "..",
        ".",
        "...",
        "a/b",
        "%2e%2e",
        "a.b",
        "a b",
        "",
        "  ",
        "x" * 65,
        "a\\b",
        "a?b",
        "a#b",
        "é1",
    ],
)
async def test_lookup_rejects_unsafe_barcodes_without_a_request(bad: str) -> None:
    """Dots survive quote() and httpx collapses dot-segments: '..' would hit another endpoint."""
    anything = respx.route().mock(return_value=httpx.Response(200, json=_DETAILS))
    with pytest.raises(GrocyNotFoundError):
        await bound(GrocyPlugin).lookup(bad)
    assert not anything.called


@pytest.mark.asyncio
@respx.mock
async def test_lookup_accepts_the_longest_allowed_barcode() -> None:
    code = "A-" * 32
    route = respx.get(f"https://grocy.example/api/stock/products/by-barcode/{code}").mock(
        return_value=httpx.Response(200, json=_DETAILS)
    )
    await bound(GrocyPlugin).lookup(code)
    assert route.called


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("body", [[], {}, {"product": None}, {"product": []}, "text"])
async def test_lookup_barcode_200_without_a_product_object_is_a_clean_error(body: object) -> None:
    respx.get("https://grocy.example/api/stock/products/by-barcode/X1").mock(
        return_value=httpx.Response(200, json=body)
    )
    with pytest.raises(ValueError, match="no product"):
        await bound(GrocyPlugin).lookup("X1")
