# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

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
    monkeypatch.setenv("LABELYARD_SPOOLMAN_URL", "https://spoolman.example")
    monkeypatch.setenv("LABELYARD_SPOOLMAN_TIMEOUT", "5.0")
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

    monkeypatch.setenv("LABELYARD_SPOOLMAN_URL", "https://spoolman.example/")
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


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "typed",
    [
        "https://spoolman.example/?next=/x",
        "https://spoolman.example/",
        "https://spoolman.example/#frag",
        "https://spoolman.example/sub/?x=1",
    ],
)
async def test_runtime_base_url_uses_same_normalisation_as_probe(
    monkeypatch: pytest.MonkeyPatch, typed: str
) -> None:
    from app.config import get_settings

    monkeypatch.setenv("LABELYARD_SPOOLMAN_URL", typed)
    get_settings.cache_clear()
    base = "https://spoolman.example" + ("/sub" if "/sub" in typed else "")
    route = respx.get(f"{base}/api/v1/spool/7").mock(
        return_value=httpx.Response(200, json={"id": 7, "filament": {"name": "PLA"}})
    )
    data = await bound(SpoolmanPlugin).lookup("7")

    assert route.call_count == 1
    assert data.qr_payload == f"{base}/spool/show/7"


@pytest.mark.asyncio
async def test_malformed_env_url_does_not_break_startup(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app.config import get_settings

    monkeypatch.setenv("LABELYARD_SPOOLMAN_URL", "http://[::1")
    get_settings.cache_clear()
    plugin = bound(SpoolmanPlugin)  # bind() -> _refresh() must not raise

    assert plugin.is_configured() is False
    assert any("spoolman" in r.message and "invalid URL" in r.message for r in caplog.records)
    assert "[::1" not in caplog.text


# ---------------------------------------------------------------------------
# Swatch label data (#346)
# ---------------------------------------------------------------------------

_SWATCH_SPOOL = {
    "id": 27,
    "filament": {
        "vendor": {"name": "Sunlu"},
        "name": "Grau",
        "material": "PLA+",
        "color_hex": "C2C1C0",
        "settings_bed_temp": 60,
    },
    "remaining_weight": 410,
    "location": "Shelf A2",
}


def _mock_spool(payload: dict[str, object] | None = None) -> None:
    respx.get("https://spoolman.example/api/v1/spool/27").mock(
        return_value=httpx.Response(200, json=payload or _SWATCH_SPOOL)
    )


async def _store_lookup(
    monkeypatch: pytest.MonkeyPatch, values: dict[str, object] | None = None
) -> object:
    client = bound(SpoolmanPlugin)
    for key, value in (values or {}).items():
        client._store._values[key] = value  # type: ignore[attr-defined]
    return await client.lookup("27")


@pytest.mark.asyncio
@respx.mock
async def test_lookup_fills_swatch_in_the_hub_language(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_spool()
    data = await _store_lookup(monkeypatch, {"general.language": "de"})
    swatch = data.swatch  # type: ignore[attr-defined]
    assert swatch is not None
    assert swatch.language == "de"
    assert (swatch.vendor, swatch.title, swatch.color_name) == ("Sunlu", "PLA+", "Grau")
    assert swatch.bed_c == 60


@pytest.mark.asyncio
@respx.mock
async def test_unknown_hub_language_becomes_english(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_spool()
    data = await _store_lookup(monkeypatch, {"general.language": "fr"})
    assert data.swatch.language == "en"  # type: ignore[attr-defined]


@pytest.mark.asyncio
@respx.mock
async def test_lookup_reads_the_title_source_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_spool()
    data = await _store_lookup(monkeypatch, {"integrations.spoolman.label.title_source": "name"})
    swatch = data.swatch  # type: ignore[attr-defined]
    assert (swatch.title, swatch.color_name) == ("Grau", "PLA+")


@pytest.mark.asyncio
@respx.mock
async def test_title_source_env_locks_the_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setenv("LABELYARD_SPOOLMAN_LABEL_TITLE_SOURCE", "name")
    get_settings.cache_clear()
    _mock_spool()
    data = await _store_lookup(
        monkeypatch, {"integrations.spoolman.label.title_source": "material"}
    )
    assert data.swatch.title == "Grau"  # type: ignore[attr-defined]
    get_settings.cache_clear()


@pytest.mark.asyncio
@respx.mock
async def test_lookup_reads_the_configured_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {**_SWATCH_SPOOL, "extra": {"pa": "0.027"}}
    _mock_spool(payload)
    data = await _store_lookup(
        monkeypatch, {"integrations.spoolman.label.pressure_advance_field": "pa"}
    )
    assert data.swatch.pressure_advance == pytest.approx(0.027)  # type: ignore[attr-defined]


@pytest.mark.asyncio
@respx.mock
async def test_lookup_still_returns_title_when_the_swatch_cannot_be_built(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    from pydantic import BaseModel, ValidationError

    _mock_spool()
    with patch("app.integrations.spoolman.plugin.build_swatch", return_value=None):
        data = await _store_lookup(monkeypatch)
    assert data.swatch is None  # type: ignore[attr-defined]
    assert data.title == "Sunlu Grau"  # type: ignore[attr-defined]
    assert data.primary_id == "#27"  # type: ignore[attr-defined]
    assert data.qr_payload == "https://spoolman.example/spool/show/27"  # type: ignore[attr-defined]

    class _Strict(BaseModel):
        x: int

    try:
        _Strict.model_validate({"x": "not a number"})
    except ValidationError as exc:
        error = exc

    def _raise(**_kw: object) -> object:
        raise error

    with (
        patch("app.integrations.spoolman.swatch.SpoolSwatch", side_effect=_raise),
        caplog.at_level(logging.INFO, logger="app.integrations.spoolman.swatch"),
    ):
        data = await _store_lookup(monkeypatch)
    assert data.swatch is None  # type: ignore[attr-defined]
    assert data.title == "Sunlu Grau"  # type: ignore[attr-defined]
    assert data.primary_id == "#27"  # type: ignore[attr-defined]
    record = next(r for r in caplog.records if r.levelno == logging.INFO)
    assert "27" in record.getMessage()
    assert "ValidationError" in record.getMessage()
    assert "Sunlu" not in caplog.text
    assert "Shelf" not in caplog.text


@pytest.mark.asyncio
@respx.mock
async def test_lookup_keeps_title_primary_id_and_secondary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_spool()
    data = await _store_lookup(monkeypatch)
    assert data.title == "Sunlu Grau"  # type: ignore[attr-defined]
    assert data.primary_id == "#27"  # type: ignore[attr-defined]
    assert data.secondary == ("410g remaining",)  # type: ignore[attr-defined]
    assert data.swatch is not None  # type: ignore[attr-defined]
