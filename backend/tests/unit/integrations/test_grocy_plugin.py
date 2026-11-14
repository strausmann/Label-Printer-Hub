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


# ---------------------------------------------------------------------------
# Battery and chore details (fields per Grocy's OpenAPI file and its PHP services)
# ---------------------------------------------------------------------------

_BATTERY = {
    "battery": {
        "id": "4",
        "name": "Remote AAA",
        "description": "Warranty ends 2027",
        "used_in": "TV remote",
        "userfields": {"secret": "do not pass through"},
    },
    "last_charged": "2026-03-13 18:12:28",
    "charge_cycles_count": 4,
    "next_estimated_charge_time": "2026-09-01 08:00:00",
}
_CHORE = {
    "chore": {"id": "7", "name": "Water the plants", "description": ""},
    "last_tracked": "2026-11-10 09:30:00",
    "tracked_count": 12,
    "next_estimated_execution_time": "2026-11-17 09:30:00",
    "next_execution_assigned_user": {"id": 2, "username": "anna", "display_name": "Anna B."},
}


@pytest.mark.asyncio
@respx.mock
async def test_battery_details_are_mapped_field_by_field() -> None:
    route = respx.get("https://grocy.example/api/batteries/4").mock(
        return_value=httpx.Response(200, json=_BATTERY)
    )
    result = await bound(GrocyPlugin).battery("4")

    assert route.calls.last.request.headers["GROCY-API-KEY"] == "grocy-key"
    assert result.model_dump(mode="json") == {
        "id": "4",
        "name": "Remote AAA",
        "description": "Warranty ends 2027",
        "url": "https://grocy.example/battery/4",
        "last_charged": "2026-03-13T18:12:28",
        "next_estimated_charge": "2026-09-01T08:00:00",
        "charge_cycles": 4,
    }


@pytest.mark.asyncio
@respx.mock
async def test_battery_never_charged_has_no_dates_and_the_never_marker_is_no_date() -> None:
    body = {
        **_BATTERY,
        "last_charged": None,
        "charge_cycles_count": 0,
        "next_estimated_charge_time": "2999-12-31 23:59:59",
    }
    respx.get("https://grocy.example/api/batteries/4").mock(
        return_value=httpx.Response(200, json=body)
    )
    result = await bound(GrocyPlugin).battery("4")
    assert result.last_charged is None
    assert result.next_estimated_charge is None
    assert result.charge_cycles == 0


@pytest.mark.asyncio
@respx.mock
async def test_chore_details_are_mapped_and_an_empty_description_is_none() -> None:
    respx.get("https://grocy.example/api/chores/7").mock(
        return_value=httpx.Response(200, json=_CHORE)
    )
    result = await bound(GrocyPlugin).chore("7")
    assert result.model_dump(mode="json") == {
        "id": "7",
        "name": "Water the plants",
        "description": None,
        "url": "https://grocy.example/chore/7",
        "last_tracked": "2026-11-10T09:30:00",
        "next_estimated_execution": "2026-11-17T09:30:00",
        "assigned_to": "Anna B.",
    }


@pytest.mark.asyncio
@respx.mock
async def test_chore_without_an_assigned_user_has_none() -> None:
    body = {**_CHORE, "next_execution_assigned_user": None}
    respx.get("https://grocy.example/api/chores/7").mock(
        return_value=httpx.Response(200, json=body)
    )
    assert (await bound(GrocyPlugin).chore("7")).assigned_to is None


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("status", [400, 404])
async def test_battery_and_chore_unknown_id_is_not_found(status: int) -> None:
    respx.get("https://grocy.example/api/batteries/99").mock(return_value=httpx.Response(status))
    respx.get("https://grocy.example/api/chores/99").mock(return_value=httpx.Response(status))
    with pytest.raises(GrocyNotFoundError):
        await bound(GrocyPlugin).battery("99")
    with pytest.raises(GrocyNotFoundError):
        await bound(GrocyPlugin).chore("99")


@pytest.mark.asyncio
@respx.mock
async def test_battery_and_chore_5xx_surface_as_http_errors() -> None:
    respx.get("https://grocy.example/api/batteries/4").mock(return_value=httpx.Response(503))
    respx.get("https://grocy.example/api/chores/7").mock(return_value=httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        await bound(GrocyPlugin).battery("4")
    with pytest.raises(httpx.HTTPStatusError):
        await bound(GrocyPlugin).chore("7")


@pytest.mark.asyncio
@respx.mock
async def test_battery_and_chore_network_errors_surface() -> None:
    respx.get("https://grocy.example/api/batteries/4").mock(side_effect=httpx.ConnectError("down"))
    respx.get("https://grocy.example/api/chores/7").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(httpx.ConnectError):
        await bound(GrocyPlugin).battery("4")
    with pytest.raises(httpx.ReadTimeout):
        await bound(GrocyPlugin).chore("7")


@pytest.mark.asyncio
async def test_battery_and_chore_without_configuration_raise_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings
    from app.services.errors import IntegrationNotConfiguredError

    monkeypatch.setenv("LABELYARD_GROCY_URL", "")
    monkeypatch.setenv("LABELYARD_GROCY_API_KEY", "")
    get_settings.cache_clear()
    with pytest.raises(IntegrationNotConfiguredError):
        await bound(GrocyPlugin).battery("4")
    with pytest.raises(IntegrationNotConfiguredError):
        await bound(GrocyPlugin).chore("7")


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("bad", ["../users", "4/../../x", "abc", "4?x=1", ""])
async def test_battery_and_chore_reject_non_numeric_ids_without_a_request(bad: str) -> None:
    route = respx.route().mock(return_value=httpx.Response(200, json=_BATTERY))
    with pytest.raises(GrocyNotFoundError):
        await bound(GrocyPlugin).battery(bad)
    with pytest.raises(GrocyNotFoundError):
        await bound(GrocyPlugin).chore(bad)
    assert not route.called


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("body", [[], {"last_charged": None}, {"battery": "x"}])
async def test_battery_response_without_a_battery_object_fails_loudly(body: object) -> None:
    respx.get("https://grocy.example/api/batteries/4").mock(
        return_value=httpx.Response(200, json=body)
    )
    with pytest.raises(ValueError):
        await bound(GrocyPlugin).battery("4")


@pytest.mark.asyncio
@respx.mock
async def test_chore_response_without_a_chore_object_fails_loudly() -> None:
    respx.get("https://grocy.example/api/chores/7").mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(ValueError):
        await bound(GrocyPlugin).chore("7")


@pytest.mark.asyncio
@respx.mock
async def test_battery_and_chore_id_and_link_come_from_the_asked_id_not_the_answer() -> None:
    hostile = {"id": "../../evil", "name": "X"}
    respx.get("https://grocy.example/api/batteries/4").mock(
        return_value=httpx.Response(200, json={**_BATTERY, "battery": hostile})
    )
    respx.get("https://grocy.example/api/chores/7").mock(
        return_value=httpx.Response(200, json={**_CHORE, "chore": hostile})
    )
    battery = await bound(GrocyPlugin).battery("4")
    chore = await bound(GrocyPlugin).chore("7")
    assert (battery.id, battery.url) == ("4", "https://grocy.example/battery/4")
    assert (chore.id, chore.url) == ("7", "https://grocy.example/chore/7")


@pytest.mark.asyncio
@respx.mock
async def test_battery_and_chore_text_is_bounded() -> None:
    long_battery = {"id": 4, "name": "n" * 500, "description": "d" * 5000}
    respx.get("https://grocy.example/api/batteries/4").mock(
        return_value=httpx.Response(200, json={**_BATTERY, "battery": long_battery})
    )
    respx.get("https://grocy.example/api/chores/7").mock(
        return_value=httpx.Response(
            200,
            json={
                **_CHORE,
                "chore": {"id": 7, "name": "c" * 500},
                "next_execution_assigned_user": {"display_name": "u" * 500},
            },
        )
    )
    battery = await bound(GrocyPlugin).battery("4")
    chore = await bound(GrocyPlugin).chore("7")
    assert len(battery.name) == 200
    assert battery.description is not None and len(battery.description) == 2000
    assert len(chore.name) == 200
    assert chore.assigned_to is not None and len(chore.assigned_to) == 200


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("cycles", [True, -1, "4", 2.5, None])
async def test_battery_charge_cycles_must_be_a_real_count(cycles: object) -> None:
    respx.get("https://grocy.example/api/batteries/4").mock(
        return_value=httpx.Response(200, json={**_BATTERY, "charge_cycles_count": cycles})
    )
    assert (await bound(GrocyPlugin).battery("4")).charge_cycles == 0
