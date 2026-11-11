"""Admin printer payloads for IPP page printers (spec 11.1, plan 2 task 5)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from app.schemas.printer_admin import (
    IppConnection,
    PrinterConnection,
    PrinterCreatePayload,
    PrinterUpdatePayload,
    TrayIn,
)
from pydantic import ValidationError

URI = "ipp://printer.example.invalid/ipp/print"


def _tray(key: str = "auto", **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"key": key, "label": "Tray", "is_default": key == "auto"}
    base.update(over)
    return base


def _ipp(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "Office laser",
        "slug": "office-laser",
        "backend": "ipp",
        "connection": {"uri": URI},
        "trays": [_tray("auto"), _tray("tray-2")],
    }
    base.update(over)
    return base


def _tape(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "Workshop",
        "slug": "workshop",
        "model": "PT-P750W",
        "backend": "ptouch",
        "connection": {"host": "192.0.2.10", "port": 9100},
    }
    base.update(over)
    return base


def test_valid_ipp_payload() -> None:
    p = PrinterCreatePayload.model_validate(_ipp())
    assert isinstance(p.connection, IppConnection)
    assert p.connection.uri == URI
    assert p.connection.tls_verify is True  # OC-17: verification on by default
    assert p.model is None  # filled from the probe
    assert p.trays is not None
    assert [t.key for t in p.trays] == ["auto", "tray-2"]
    assert p.trays[0].enabled is True


def test_ipp_payload_tls_verify_off_allowed() -> None:
    p = PrinterCreatePayload.model_validate(_ipp(connection={"uri": URI, "tls_verify": False}))
    assert isinstance(p.connection, IppConnection)
    assert p.connection.tls_verify is False


@pytest.mark.parametrize(
    "uri",
    [
        "ftp://printer.example.invalid/ipp",
        "ipp://user:secret@printer.example.invalid/ipp",
        "ipp://user@printer.example.invalid/ipp",
        "ipp://printer.example.invalid/ipp#frag",
        "file:///etc/passwd",
        "ipp:///no-host",
        "ipp://printer.example.invalid:0/ipp",
        "ipp://printer.example.invalid/ ipp",
        "ipp://printer.example.invalid/" + "a" * 1100,
    ],
)
def test_ipp_connection_refuses_bad_uri(uri: str) -> None:
    with pytest.raises(ValidationError):
        IppConnection.model_validate({"uri": uri})
    with pytest.raises(ValidationError):
        PrinterCreatePayload.model_validate(_ipp(connection={"uri": uri}))


@pytest.mark.parametrize(
    "uri",
    [
        URI,
        "ipps://printer.example.invalid/ipp/print",
        "http://printer.example.invalid:631/ipp/print",
        "https://printer.example.invalid/ipp/print",
    ],
)
def test_ipp_connection_accepts_the_four_schemes(uri: str) -> None:
    assert IppConnection.model_validate({"uri": uri}).uri == uri


def test_ipp_connection_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        IppConnection.model_validate({"uri": URI, "host": "printer.example.invalid"})


def test_ipp_without_trays_refused() -> None:
    payload = _ipp()
    del payload["trays"]
    with pytest.raises(ValidationError, match="trays"):
        PrinterCreatePayload.model_validate(payload)
    with pytest.raises(ValidationError):
        PrinterCreatePayload.model_validate(_ipp(trays=[]))


def test_too_many_trays_refused() -> None:
    trays = [_tray("auto")] + [_tray(f"t{n}") for n in range(16)]
    with pytest.raises(ValidationError):
        PrinterCreatePayload.model_validate(_ipp(trays=trays))
    assert PrinterCreatePayload.model_validate(_ipp(trays=trays[:16])).trays is not None


def test_two_defaults_refused() -> None:
    trays = [_tray("auto"), _tray("tray-2", is_default=True)]
    with pytest.raises(ValidationError, match="default"):
        PrinterCreatePayload.model_validate(_ipp(trays=trays))


def test_no_default_refused() -> None:
    trays = [_tray("auto", is_default=False), _tray("tray-2")]
    with pytest.raises(ValidationError, match="default"):
        PrinterCreatePayload.model_validate(_ipp(trays=trays))


def test_default_disabled_refused() -> None:
    trays = [_tray("auto", enabled=False), _tray("tray-2")]
    with pytest.raises(ValidationError, match="default"):
        PrinterCreatePayload.model_validate(_ipp(trays=trays))


def test_no_enabled_tray_refused() -> None:
    trays = [_tray("auto", enabled=False, is_default=False), _tray("tray-2", enabled=False)]
    with pytest.raises(ValidationError, match="enabled"):
        PrinterCreatePayload.model_validate(_ipp(trays=trays))


def test_duplicate_tray_keys_refused() -> None:
    trays = [_tray("auto"), _tray("tray-2"), _tray("tray-2")]
    with pytest.raises(ValidationError, match="unique"):
        PrinterCreatePayload.model_validate(_ipp(trays=trays))


@pytest.mark.parametrize("key", ["Main Tray", "Tray1", "-tray", "", "a" * 65, "tray_2", "ä"])
def test_tray_key_pattern(key: str) -> None:
    with pytest.raises(ValidationError):
        TrayIn.model_validate(_tray(key))


@pytest.mark.parametrize("key", ["auto", "tray-1", "main", "a" * 64, "0"])
def test_tray_key_pattern_accepts(key: str) -> None:
    assert TrayIn.model_validate(_tray(key)).key == key


def test_tray_label_and_hint_bounds_and_cleaning() -> None:
    with pytest.raises(ValidationError):
        TrayIn.model_validate(_tray(label="x" * 61))
    with pytest.raises(ValidationError):
        TrayIn.model_validate(_tray(label=" \t "))
    with pytest.raises(ValidationError):
        TrayIn.model_validate(_tray(load_hint="x" * 201))
    tray = TrayIn.model_validate(_tray(label="Lower\ttray\x07", load_hint="written side\r\ndown‮"))
    assert tray.label == "Lower tray"
    assert tray.load_hint == "written side down"
    assert TrayIn.model_validate(_tray(load_hint="  ")).load_hint is None


def test_trays_on_a_tape_printer_refused() -> None:
    with pytest.raises(ValidationError, match="trays"):
        PrinterCreatePayload.model_validate(_tape(trays=[_tray("auto")]))


def test_tape_printer_still_needs_model() -> None:
    payload = _tape()
    del payload["model"]
    with pytest.raises(ValidationError, match="model"):
        PrinterCreatePayload.model_validate(payload)


def test_tape_payload_unchanged() -> None:
    p = PrinterCreatePayload.model_validate(_tape())
    assert isinstance(p.connection, PrinterConnection)
    assert p.trays is None


def test_ipp_backend_needs_an_ipp_connection() -> None:
    with pytest.raises(ValidationError, match="connection"):
        PrinterCreatePayload.model_validate(_ipp(connection={"host": "192.0.2.10", "port": 631}))


def test_tape_backend_refuses_an_ipp_connection() -> None:
    with pytest.raises(ValidationError, match="connection"):
        PrinterCreatePayload.model_validate(_tape(connection={"uri": URI}))


def test_ipp_model_may_be_given() -> None:
    assert PrinterCreatePayload.model_validate(_ipp(model="Laser")).model == "Laser"


def test_update_payload_takes_either_connection_and_trays() -> None:
    p = PrinterUpdatePayload.model_validate({"connection": {"uri": URI}})
    assert isinstance(p.connection, IppConnection)
    p = PrinterUpdatePayload.model_validate({"connection": {"host": "192.0.2.10", "port": 9100}})
    assert isinstance(p.connection, PrinterConnection)
    p = PrinterUpdatePayload.model_validate({"trays": [_tray("auto")]})
    assert p.trays is not None
    assert p.trays[0].key == "auto"
    assert PrinterUpdatePayload.model_validate({}).trays is None


def test_update_payload_tray_rules_apply() -> None:
    with pytest.raises(ValidationError, match="default"):
        PrinterUpdatePayload.model_validate({"trays": [_tray("auto", is_default=False)]})
    with pytest.raises(ValidationError):
        PrinterUpdatePayload.model_validate({"trays": []})


# ---------------------------------------------------------------------------- service helpers


def _summary(**over: Any) -> Any:
    from app.printer_backends.ipp.attributes import summarise

    summary = summarise({})
    return summary.model_copy(update=over)


def test_ipp_model_from_make_and_model_cut_to_120() -> None:
    from app.services.printer_admin_service import _ipp_model

    assert _ipp_model(_summary(make_and_model="  Laser 5  "), "typed") == "Laser 5"
    assert _ipp_model(_summary(make_and_model="x" * 300), None) == "x" * 120
    assert _ipp_model(_summary(make_and_model=None), "typed") == "typed"
    assert _ipp_model(_summary(make_and_model=" "), None) == "IPP printer"


def test_ipp_identity_salt_uses_effective_host_and_port() -> None:
    from app.services.printer_admin_service import _ipp_host_port

    assert _ipp_host_port("ipp://printer.example.invalid/ipp") == ("printer.example.invalid", 631)
    assert _ipp_host_port("https://printer.example.invalid/ipp") == ("printer.example.invalid", 443)
    assert _ipp_host_port("http://printer.example.invalid/ipp") == ("printer.example.invalid", 80)
    assert _ipp_host_port("ipps://printer.example.invalid:8631/") == (
        "printer.example.invalid",
        8631,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (httpx.ConnectError, "ipp_unreachable"),
        (httpx.ReadTimeout, "ipp_unreachable"),
        (httpx.RemoteProtocolError, "ipp_unreachable"),
    ],
)
async def test_probe_maps_transport_failures(
    exc: type[httpx.RequestError], code: str, caplog: pytest.LogCaptureFixture
) -> None:
    from app.services.printer_admin_service import probe_ipp
    from app.sheets.errors import SheetApiError

    def handler(request: httpx.Request) -> httpx.Response:
        raise exc("boom printer.example.invalid", request=request)

    with pytest.raises(SheetApiError) as info:
        await probe_ipp(
            IppConnection(uri=URI),
            queue_timeout_s=30,
            transport_factory=lambda _uri: httpx.MockTransport(handler),
            log_name="laser",
        )
    assert info.value.error_code == code
    assert info.value.status == 502
    assert "printer.example.invalid" not in caplog.text
    assert "laser" in caplog.text


@pytest.mark.asyncio
async def test_probe_maps_invalid_url_to_unreachable() -> None:
    from app.services.printer_admin_service import probe_ipp
    from app.sheets.errors import SheetApiError

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.InvalidURL("bad host")

    with pytest.raises(SheetApiError) as info:
        await probe_ipp(
            IppConnection(uri=URI),
            queue_timeout_s=30,
            transport_factory=lambda _uri: httpx.MockTransport(handler),
            unreachable_status=409,
        )
    assert (info.value.error_code, info.value.status) == ("ipp_unreachable", 409)


@pytest.mark.asyncio
async def test_probe_timeout_is_min_of_five_and_queue_timeout() -> None:
    from unittest.mock import patch

    from app.services import printer_admin_service as svc

    seen: list[float] = []

    class StopError(Exception):
        pass

    def spy(uri: str, **kwargs: Any) -> Any:
        seen.append(kwargs["query_timeout_s"])
        raise StopError

    with patch.object(svc, "IppClient", side_effect=spy):
        for queue_timeout in (30, 3):
            with pytest.raises(StopError):
                await svc.probe_ipp(IppConnection(uri=URI), queue_timeout_s=queue_timeout)
    assert seen == [5.0, 3.0]
