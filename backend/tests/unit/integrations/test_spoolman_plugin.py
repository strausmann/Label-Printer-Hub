from unittest.mock import patch

import httpx
import pytest
import respx
from app.integrations.spoolman.plugin import SpoolmanNotFoundError, SpoolmanPlugin

from tests.unit.integrations._bound import bound

# ---------------------------------------------------------------------------
# Settings fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _stub_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the plugin at a fake host. respx mocks the actual HTTP."""
    monkeypatch.setenv("PRINTER_HUB_SPOOLMAN_URL", "https://spoolman.example")
    monkeypatch.setenv("PRINTER_HUB_SPOOLMAN_TIMEOUT", "5.0")
    from app.config import get_settings

    get_settings.cache_clear()


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
    client = bound(SpoolmanPlugin)
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
    client = bound(SpoolmanPlugin)
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
    client = bound(SpoolmanPlugin)
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
    client = bound(SpoolmanPlugin)
    data = await client.lookup("1")
    assert data.title == "Unknown PLA"


@pytest.mark.asyncio
@respx.mock
async def test_lookup_strips_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    respx.get("https://spoolman.example/api/v1/spool/7").mock(
        return_value=httpx.Response(
            200, json={"id": 7, "filament": {"vendor": {"name": "V"}, "name": "M"}}
        )
    )
    from app.config import get_settings

    monkeypatch.setenv("PRINTER_HUB_SPOOLMAN_URL", "https://spoolman.example/")
    get_settings.cache_clear()
    client = bound(SpoolmanPlugin)
    data = await client.lookup("7")
    assert data.qr_payload == "https://spoolman.example/spool/show/7"


@pytest.mark.asyncio
@respx.mock
async def test_lookup_accepts_a_long_numeric_spool_id() -> None:
    respx.get("https://spoolman.example/api/v1/spool/1234567890").mock(
        return_value=httpx.Response(
            200, json={"id": 1, "filament": {"vendor": {"name": "V"}, "name": "M"}}
        )
    )
    client = bound(SpoolmanPlugin)
    data = await client.lookup("1234567890")
    # The mock matched, so we got LabelData back.
    assert data.source_app == "spoolman"
    assert data.primary_id == "#1"


@pytest.mark.asyncio
@respx.mock
async def test_lookup_5xx_raises_httpx_error() -> None:
    respx.get("https://spoolman.example/api/v1/spool/1").mock(return_value=httpx.Response(503))
    client = bound(SpoolmanPlugin)
    with pytest.raises(httpx.HTTPStatusError):
        await client.lookup("1")


@pytest.mark.asyncio
@respx.mock
async def test_lookup_missing_id_raises_value_error() -> None:
    respx.get("https://spoolman.example/api/v1/spool/1").mock(
        return_value=httpx.Response(200, json={"filament": {"vendor": {"name": "V"}, "name": "M"}})
    )
    client = bound(SpoolmanPlugin)
    with pytest.raises(ValueError, match="missing required field 'id'"):
        await client.lookup("1")


@pytest.mark.asyncio
@respx.mock
async def test_lookup_spool_with_null_filament() -> None:
    """Spoolman with filament: null must produce 'Unknown Unknown' title without crashing."""
    respx.get("https://spoolman.example/api/v1/spool/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "filament": None})
    )
    client = bound(SpoolmanPlugin)
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
    client = bound(SpoolmanPlugin)
    await client.lookup("1")

    assert route.called
    sent = route.calls.last.request
    assert "Authorization" not in sent.headers
    assert "GROCY-API-KEY" not in sent.headers
    assert sent.headers["Accept"] == "application/json"


@pytest.mark.asyncio
@respx.mock
async def test_lookup_reuses_http_client_across_calls() -> None:
    """The plugin must reuse a single AsyncClient — no new connection per lookup().

    Two consecutive lookups must use the SAME AsyncClient instance so TCP/TLS
    connections are pooled rather than re-established on every call.
    """
    respx.get("https://spoolman.example/api/v1/spool/10").mock(
        return_value=httpx.Response(
            200, json={"id": 10, "filament": {"vendor": {"name": "V"}, "name": "M"}}
        )
    )
    respx.get("https://spoolman.example/api/v1/spool/11").mock(
        return_value=httpx.Response(
            200, json={"id": 11, "filament": {"vendor": {"name": "V"}, "name": "M"}}
        )
    )

    instances: list[httpx.AsyncClient] = []
    real_init = httpx.AsyncClient.__init__

    def capturing_init(self: httpx.AsyncClient, *args: object, **kwargs: object) -> None:
        real_init(self, *args, **kwargs)
        instances.append(self)

    with patch.object(httpx.AsyncClient, "__init__", capturing_init):
        plugin = bound(SpoolmanPlugin)
        await plugin.lookup("10")
        await plugin.lookup("11")

    await plugin.aclose()

    assert len(instances) == 1, (
        f"Expected exactly one AsyncClient to be created (connection pooling), "
        f"but {len(instances)} were created"
    )


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "bad", ["..", ".", "a/b", "%2e%2e", "A/1", "a b", "", " ", "1.5", "-1", "#5", "9" * 21, "é"]
)
async def test_lookup_rejects_non_numeric_ids_without_a_request(bad: str) -> None:
    """Spool ids are integers: anything else (dot-segments included) never leaves the hub."""
    anything = respx.route().mock(return_value=httpx.Response(200, json={"id": 1}))
    with pytest.raises(SpoolmanNotFoundError):
        await bound(SpoolmanPlugin).lookup(bad)
    assert not anything.called


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("body", [[], "text", 5])
async def test_lookup_non_object_response_is_a_clean_error(body: object) -> None:
    respx.get("https://spoolman.example/api/v1/spool/1").mock(
        return_value=httpx.Response(200, json=body)
    )
    with pytest.raises(ValueError, match="not an object"):
        await bound(SpoolmanPlugin).lookup("1")
