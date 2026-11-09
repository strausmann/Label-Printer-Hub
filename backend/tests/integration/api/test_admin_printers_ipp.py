"""Admin configuration of IPP page printers: probe, save rules, trays, URI visibility.

The hub never reaches a real printer here: ``app.state.ipp_transport_factory`` hands the
IPP client a transport into ``FakeIppPrinter`` (or a scripted failure). Keys are real API
keys, so scope checks run as in production. All hosts are ``*.example.invalid``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import app.models  # noqa: F401
import bcrypt
import httpx
import pytest
import pytest_asyncio
from app.models.api_key import ApiKey
from app.models.printer import Printer
from app.models.printer_calibration import PrinterCalibration
from app.models.printer_tray import PrinterTray
from app.printer_backends.ipp.codec import Attr, Group, Message, Tag, decode, encode
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from tests.helpers.fake_ipp_printer import FakeIppPrinter

HOST = "printer.example.invalid"
URI = f"ipp://{HOST}/ipp/print"
URI_2 = "ipps://second-printer.example.invalid/ipp/print"
PROBE = "/api/v1/admin/printers/ipp/probe"
ADMIN = "/api/v1/admin/printers"


def _factory():
    import app.db.engine as _engine_module

    return _engine_module.async_session


async def _key(scopes: list[str]) -> dict[str, str]:
    plaintext = f"lh_pat_{uuid4().hex}"
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=4)).decode()
    async with _factory()() as s:
        s.add(
            ApiKey(
                name=f"ipp-{uuid4().hex[:6]}",
                key_hash=hashed,
                key_prefix=plaintext[:16],
                scopes=scopes,
                allowed_printer_ids=[],
                enabled=True,
                rate_limit_per_minute=600,
            )
        )
        await s.commit()
    return {"X-Label-Hub-Key": plaintext}


def _ipp_status_transport(status: int) -> httpx.MockTransport:
    """A printer that answers every request with the given IPP status code."""

    def handler(request: httpx.Request) -> httpx.Response:
        msg, _ = decode(request.read())
        reply = Message(
            (1, 1),
            status,
            msg.request_id,
            [
                Group(
                    Tag.OPERATION,
                    [
                        Attr("attributes-charset", Tag.CHARSET, ["utf-8"]),
                        Attr("attributes-natural-language", Tag.LANGUAGE, ["en"]),
                    ],
                )
            ],
        )
        return httpx.Response(
            200,
            stream=httpx.ByteStream(encode(reply)),
            headers={"content-type": "application/ipp"},
        )

    return httpx.MockTransport(handler)


def _raw_transport(status: int, content: bytes, headers: dict[str, str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        request.read()
        return httpx.Response(status, stream=httpx.ByteStream(content), headers=headers)

    return httpx.MockTransport(handler)


def _unreachable_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    return httpx.MockTransport(handler)


@dataclass
class Hub:
    client: AsyncClient
    fake: FakeIppPrinter
    app: Any
    uris: list[str] = field(default_factory=list)
    override: Callable[[str], httpx.AsyncBaseTransport] | None = None

    def ops(self) -> list[str]:
        return [op.operation for op in self.fake.received]


@pytest_asyncio.fixture
async def hub() -> AsyncIterator[Hub]:
    from app.integrations import (  # type: ignore[attr-defined]
        IntegrationRegistry,
        _discover_plugins,
    )
    from app.main import create_app

    if not IntegrationRegistry.names():
        _discover_plugins()
    fake = FakeIppPrinter(media_sources=["tray-1", "tray-2"])
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        h = Hub(client=client, fake=fake, app=app)

        def factory(uri: str) -> httpx.AsyncBaseTransport:
            h.uris.append(uri)
            if h.override is not None:
                return h.override(uri)
            return httpx.ASGITransport(app=fake)

        app._app.state.ipp_transport_factory = factory
        yield h


def _trays(*extra: str) -> list[dict[str, Any]]:
    trays = [{"key": "auto", "label": "Automatic", "is_default": True}]
    trays += [{"key": k, "label": f"Tray {k}", "load_hint": "written side down"} for k in extra]
    return trays


def _ipp_payload(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "Office laser",
        "slug": "office-laser",
        "backend": "ipp",
        "connection": {"uri": URI},
        "trays": _trays("tray-2"),
    }
    base.update(over)
    return base


def _tape_payload(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "Workshop",
        "slug": "workshop",
        "model": "PT-P750W",
        "backend": "ptouch",
        "connection": {"host": "192.0.2.10", "port": 9100},
    }
    base.update(over)
    return base


async def _db_printer(slug: str) -> Printer | None:
    async with _factory()() as s:
        return (await s.execute(select(Printer).where(Printer.slug == slug))).scalar_one_or_none()


async def _db_trays(printer_id: UUID) -> list[tuple[str, str, bool, bool]]:
    async with _factory()() as s:
        rows = (
            await s.execute(
                select(PrinterTray)
                .where(PrinterTray.printer_id == printer_id)
                .order_by(PrinterTray.tray_key)
            )
        ).scalars()
        return [(t.tray_key, t.label, t.enabled, t.is_default) for t in rows]


def _error(resp: httpx.Response) -> dict[str, Any]:
    detail = resp.json()["detail"]
    assert isinstance(detail, dict), resp.text
    return detail


# ---------------------------------------------------------------------------- probe


@pytest.mark.asyncio
async def test_probe_returns_summary(hub: Hub) -> None:
    resp = await hub.client.post(PROBE, json={"uri": URI}, headers=await _key(["admin"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["make_and_model"] == "Fake IPP Printer"
    assert body["pdf_supported"] is True
    assert body["media_sources"] == ["tray-1", "tray-2"]
    assert body["state"] == "idle"
    assert hub.ops() == ["Get-Printer-Attributes"]
    assert hub.uris == [URI]
    assert HOST not in resp.text  # the summary never carries the URI


@pytest.mark.asyncio
@pytest.mark.parametrize("scopes", [["print"], ["read"]])
async def test_probe_needs_admin(hub: Hub, scopes: list[str]) -> None:
    resp = await hub.client.post(PROBE, json={"uri": URI}, headers=await _key(scopes))
    assert resp.status_code == 403, resp.text
    assert hub.ops() == []
    assert hub.uris == []


@pytest.mark.asyncio
async def test_probe_without_key_is_refused(hub: Hub) -> None:
    resp = await hub.client.post(PROBE, json={"uri": URI})
    assert resp.status_code in (401, 403), resp.text
    assert hub.uris == []


@pytest.mark.asyncio
async def test_probe_unreachable(hub: Hub) -> None:
    hub.override = lambda _uri: _unreachable_transport()
    resp = await hub.client.post(PROBE, json={"uri": URI}, headers=await _key(["admin"]))
    assert resp.status_code == 502, resp.text
    assert _error(resp)["error_code"] == "ipp_unreachable"
    assert HOST not in resp.text


@pytest.mark.asyncio
async def test_probe_rejected_names_the_ipp_status(hub: Hub) -> None:
    hub.override = lambda _uri: _ipp_status_transport(0x0400)
    resp = await hub.client.post(PROBE, json={"uri": URI}, headers=await _key(["admin"]))
    assert resp.status_code == 502, resp.text
    err = _error(resp)
    assert err["error_code"] == "ipp_rejected"
    assert err["error_detail"] == {"ipp_status": "client-error-bad-request"}
    assert HOST not in resp.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("http_status", "content", "headers"),
    [
        (200, f"<html>printer web page {HOST}</html>".encode(), {"content-type": "text/html"}),
        (302, b"", {"location": "http://internal.example.invalid/"}),
        (200, b"\x01\x01\x00", {"content-type": "application/ipp"}),
    ],
    ids=["html", "redirect", "truncated"],
)
async def test_probe_bad_response_does_not_echo_the_answer(
    hub: Hub, http_status: int, content: bytes, headers: dict[str, str]
) -> None:
    hub.override = lambda _uri: _raw_transport(http_status, content, headers)
    resp = await hub.client.post(PROBE, json={"uri": URI}, headers=await _key(["admin"]))
    assert resp.status_code == 502, resp.text
    assert _error(resp)["error_code"] == "ipp_bad_response"
    assert HOST not in resp.text
    assert "internal.example.invalid" not in resp.text
    assert "html" not in resp.text.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "uri",
    ["ftp://secret-host.example.invalid/x", "ipp://admin:pw@secret-host.example.invalid/x"],
)
async def test_probe_refuses_bad_uri_without_echo(hub: Hub, uri: str) -> None:
    resp = await hub.client.post(PROBE, json={"uri": uri}, headers=await _key(["admin"]))
    assert resp.status_code == 422, resp.text
    assert "secret-host" not in resp.text
    assert "pw" not in resp.text
    assert hub.uris == []


@pytest.mark.asyncio
async def test_probe_hands_tls_verify_to_the_client(hub: Hub) -> None:
    seen: list[bool] = []
    from app.printer_backends.ipp import client as client_module

    real = client_module.IppClient

    def spy(uri: str, **kwargs: Any) -> Any:
        seen.append(kwargs["tls_verify"])
        return real(uri, **kwargs)

    headers = await _key(["admin"])
    with patch("app.services.printer_admin_service.IppClient", side_effect=spy):
        await hub.client.post(PROBE, json={"uri": URI}, headers=headers)
        await hub.client.post(PROBE, json={"uri": URI, "tls_verify": False}, headers=headers)
    assert seen == [True, False]


# ---------------------------------------------------------------------------- create


@pytest.mark.asyncio
async def test_create_stores_trays_and_model(hub: Hub) -> None:
    headers = await _key(["admin"])
    resp = await hub.client.post(ADMIN, json=_ipp_payload(), headers=headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["backend"] == "ipp"
    assert body["model"] == "Fake IPP Printer"
    assert body["connection"] == {"uri": URI, "tls_verify": True}
    assert [t["key"] for t in body["trays"]] == ["auto", "tray-2"]
    assert hub.ops() == ["Get-Printer-Attributes"]
    row = await _db_printer("office-laser")
    assert row is not None
    assert row.cut_defaults_half_cut is False
    assert await _db_trays(row.id) == [
        ("auto", "Automatic", True, True),
        ("tray-2", "Tray tray-2", True, False),
    ]
    detail = await hub.client.get(f"{ADMIN}/office-laser", headers=headers)
    assert [t["load_hint"] for t in detail.json()["trays"]] == [None, "written side down"]


@pytest.mark.asyncio
async def test_create_ignores_cut_defaults_for_ipp(hub: Hub) -> None:
    resp = await hub.client.post(
        ADMIN,
        json=_ipp_payload(cut_defaults={"half_cut": True}),
        headers=await _key(["admin"]),
    )
    assert resp.status_code == 201, resp.text
    row = await _db_printer("office-laser")
    assert row is not None
    assert row.cut_defaults_half_cut is False


@pytest.mark.asyncio
async def test_create_refused_without_pdf(hub: Hub) -> None:
    hub.fake.formats = ["image/urf"]
    resp = await hub.client.post(ADMIN, json=_ipp_payload(), headers=await _key(["admin"]))
    assert resp.status_code == 409, resp.text
    assert _error(resp)["error_code"] == "ipp_pdf_unsupported"
    assert await _db_printer("office-laser") is None


@pytest.mark.asyncio
async def test_create_refused_when_unreachable(hub: Hub) -> None:
    hub.override = lambda _uri: _unreachable_transport()
    resp = await hub.client.post(ADMIN, json=_ipp_payload(), headers=await _key(["admin"]))
    assert resp.status_code == 409, resp.text
    assert _error(resp)["error_code"] == "ipp_unreachable"
    assert HOST not in resp.text
    assert await _db_printer("office-laser") is None


@pytest.mark.asyncio
async def test_create_refused_tray_unknown(hub: Hub) -> None:
    resp = await hub.client.post(
        ADMIN, json=_ipp_payload(trays=_trays("tray-2", "tray-9")), headers=await _key(["admin"])
    )
    assert resp.status_code == 422, resp.text
    err = _error(resp)
    assert err["error_code"] == "tray_unknown"
    assert err["error_detail"] == {"trays": ["tray-9"]}
    assert await _db_printer("office-laser") is None


@pytest.mark.asyncio
async def test_create_auto_only_for_printer_without_sources(hub: Hub) -> None:
    hub.fake.media_sources = []
    headers = await _key(["admin"])
    bad = await hub.client.post(ADMIN, json=_ipp_payload(), headers=headers)
    assert bad.status_code == 422, bad.text
    good = await hub.client.post(ADMIN, json=_ipp_payload(trays=_trays()), headers=headers)
    assert good.status_code == 201, good.text


@pytest.mark.asyncio
async def test_ipp_model_optional_and_filled(hub: Hub) -> None:
    headers = await _key(["admin"])
    resp = await hub.client.post(ADMIN, json=_ipp_payload(model="Typed by hand"), headers=headers)
    assert resp.status_code == 201, resp.text
    assert resp.json()["model"] == "Fake IPP Printer"  # the printer's answer wins
    tape = _tape_payload()
    del tape["model"]
    resp = await hub.client.post(ADMIN, json=tape, headers=headers)
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------- update


async def _created(hub: Hub) -> dict[str, str]:
    headers = await _key(["admin"])
    resp = await hub.client.post(ADMIN, json=_ipp_payload(), headers=headers)
    assert resp.status_code == 201, resp.text
    hub.fake.received.clear()
    hub.uris.clear()
    return headers


@pytest.mark.asyncio
async def test_update_without_uri_change_does_not_probe(hub: Hub) -> None:
    headers = await _created(hub)
    for body in (
        {"name": "Renamed laser"},
        {"connection": {"uri": URI, "tls_verify": False}},
        {
            "trays": [
                {"key": "auto", "label": "Any"},
                {"key": "tray-2", "label": "Lower", "is_default": True},
            ]
        },
    ):
        resp = await hub.client.put(f"{ADMIN}/office-laser", json=body, headers=headers)
        assert resp.status_code == 200, resp.text
    assert hub.fake.received == []
    assert hub.uris == []
    row = await _db_printer("office-laser")
    assert row is not None
    assert row.connection == {"uri": URI, "tls_verify": False}
    assert await _db_trays(row.id) == [
        ("auto", "Any", True, False),
        ("tray-2", "Lower", True, True),
    ]


@pytest.mark.asyncio
async def test_update_name_is_bounded_like_create(hub: Hub) -> None:
    """The footer of a check page is fitted to the name: an unbounded name costs CPU on read."""
    headers = await _created(hub)
    too_long = await hub.client.put(
        f"{ADMIN}/office-laser", json={"name": "n" * 256}, headers=headers
    )
    assert too_long.status_code == 422, too_long.text
    empty = await hub.client.put(f"{ADMIN}/office-laser", json={"name": ""}, headers=headers)
    assert empty.status_code == 422, empty.text
    ok = await hub.client.put(f"{ADMIN}/office-laser", json={"name": "n" * 255}, headers=headers)
    assert ok.status_code == 200, ok.text
    row = await _db_printer("office-laser")
    assert row is not None and row.name == "n" * 255


@pytest.mark.asyncio
async def test_update_with_new_uri_probes(hub: Hub) -> None:
    headers = await _created(hub)
    resp = await hub.client.put(
        f"{ADMIN}/office-laser", json={"connection": {"uri": URI_2}}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert hub.ops() == ["Get-Printer-Attributes"]
    assert hub.uris == [URI_2]
    row = await _db_printer("office-laser")
    assert row is not None
    assert row.connection == {"uri": URI_2, "tls_verify": True}


@pytest.mark.asyncio
async def test_update_with_new_tray_key_probes(hub: Hub) -> None:
    headers = await _created(hub)
    resp = await hub.client.put(
        f"{ADMIN}/office-laser", json={"trays": _trays("tray-1", "tray-2")}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert hub.ops() == ["Get-Printer-Attributes"]
    resp = await hub.client.put(
        f"{ADMIN}/office-laser", json={"trays": _trays("tray-7")}, headers=headers
    )
    assert resp.status_code == 422, resp.text
    assert _error(resp)["error_code"] == "tray_unknown"
    row = await _db_printer("office-laser")
    assert row is not None
    assert [t[0] for t in await _db_trays(row.id)] == ["auto", "tray-1", "tray-2"]


@pytest.mark.asyncio
async def test_update_new_uri_refused_keeps_the_row(hub: Hub) -> None:
    headers = await _created(hub)
    hub.fake.formats = ["image/urf"]
    resp = await hub.client.put(
        f"{ADMIN}/office-laser", json={"connection": {"uri": URI_2}}, headers=headers
    )
    assert resp.status_code == 409, resp.text
    assert _error(resp)["error_code"] == "ipp_pdf_unsupported"
    hub.fake.formats = ["application/pdf"]
    hub.override = lambda _uri: _unreachable_transport()
    resp = await hub.client.put(
        f"{ADMIN}/office-laser", json={"connection": {"uri": URI_2}}, headers=headers
    )
    assert resp.status_code == 409, resp.text
    assert _error(resp)["error_code"] == "ipp_unreachable"
    row = await _db_printer("office-laser")
    assert row is not None
    assert row.connection["uri"] == URI


@pytest.mark.asyncio
async def test_update_connection_validated_by_row_backend(hub: Hub) -> None:
    headers = await _created(hub)
    resp = await hub.client.post(ADMIN, json=_tape_payload(), headers=headers)
    assert resp.status_code == 201, resp.text
    tape_with_uri = await hub.client.put(
        f"{ADMIN}/workshop", json={"connection": {"uri": URI}}, headers=headers
    )
    assert tape_with_uri.status_code == 422, tape_with_uri.text
    assert _error(tape_with_uri)["error_code"] == "invalid_connection"
    ipp_with_host = await hub.client.put(
        f"{ADMIN}/office-laser",
        json={"connection": {"host": "192.0.2.10", "port": 631}},
        headers=headers,
    )
    assert ipp_with_host.status_code == 422, ipp_with_host.text
    assert _error(ipp_with_host)["error_code"] == "invalid_connection"
    tape_with_trays = await hub.client.put(
        f"{ADMIN}/workshop", json={"trays": _trays()}, headers=headers
    )
    assert tape_with_trays.status_code == 422, tape_with_trays.text
    assert _error(tape_with_trays)["error_code"] == "trays_not_allowed"
    assert hub.uris == []
    tape = await _db_printer("workshop")
    assert tape is not None
    assert tape.connection["host"] == "192.0.2.10"


# ---------------------------------------------------------------------------- visibility


@pytest.mark.asyncio
async def test_ipp_uri_hidden_from_read_keys(hub: Hub) -> None:
    admin = await _created(hub)
    await hub.client.post(ADMIN, json=_tape_payload(), headers=admin)
    row = await _db_printer("office-laser")
    assert row is not None
    for headers in (await _key(["read"]), await _key(["print"])):
        listed = await hub.client.get("/api/v1/printers", headers=headers)
        assert listed.status_code == 200, listed.text
        by_slug = {p["slug"]: p for p in listed.json()}
        assert by_slug["office-laser"]["connection"] == {"tls_verify": True}
        assert by_slug["workshop"]["connection"]["host"] == "192.0.2.10"  # unchanged
        one = await hub.client.get(f"/api/v1/printers/{row.id}", headers=headers)
        assert one.status_code == 200, one.text
        assert one.json()["connection"] == {"tls_verify": True}
        assert HOST not in listed.text + one.text
    listed = await hub.client.get("/api/v1/printers", headers=admin)
    by_slug = {p["slug"]: p for p in listed.json()}
    assert by_slug["office-laser"]["connection"]["uri"] == URI
    one = await hub.client.get(f"/api/v1/printers/{row.id}", headers=admin)
    assert one.json()["connection"]["uri"] == URI


# ---------------------------------------------------------------------------- tape routes


@pytest.mark.asyncio
async def test_tape_routes_refuse_page_printer(hub: Hub) -> None:
    await _created(hub)
    body = {
        "items": [
            {
                "content_type": "qr_two_lines",
                "data": {"title": "x", "primary_id": "x", "qr_payload": "q"},
            }
        ]
    }
    resp = await hub.client.post(
        "/api/v1/print/office-laser/batch", json=body, headers=await _key(["print"])
    )
    assert resp.status_code == 409, resp.text
    assert _error(resp)["error_code"] == "media_kind_mismatch"


# ---------------------------------------------------------------------------- lifespan


@pytest.mark.asyncio
async def test_lifespan_ignores_ipp_rows_for_tape_wiring(hub: Hub) -> None:
    async with _factory()() as s:
        s.add(
            Printer(
                name="Office laser",
                slug="office-laser",
                model="Fake IPP Printer",
                backend="ipp",
                connection={"uri": URI, "tls_verify": True, "snmp": {"discover": True}},
            )
        )
        s.add(
            Printer(
                name="Workshop",
                slug="workshop",
                model="PT-P750W",
                backend="ptouch",
                connection={"host": "192.0.2.10", "port": 9100},
            )
        )
        await s.commit()
    resolved: list[str] = []
    probes: list[str] = []

    async def fake_resolve(cfg: Any) -> str:
        resolved.append(cfg.slug)
        return "PT-P750W"

    class FakeProbe:
        def __init__(self, **kwargs: Any) -> None:
            probes.append(kwargs["host"])

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    with (
        patch(
            "app.services.printer_runtime._resolve_model_id_from_config", side_effect=fake_resolve
        ),
        patch("app.services.printer_runtime.StatusProbeProducer", FakeProbe),
    ):
        resp = await hub.client.get("/healthz")
        assert resp.status_code == 200
    state = hub.app._app.state
    assert resolved == ["workshop"]
    assert probes == []
    assert set(state.slug_to_printer_id) == {"workshop"}
    assert state.backend_router.get("office-laser") is None
    # Only the page-printer wiring reaches for the IPP printer at start: one client for the
    # page jobs (Task 7) and one for the status producer (Task 6). The tape wiring does not.
    assert hub.uris == [URI, URI]


@pytest.mark.asyncio
async def test_create_duplicate_slug_is_409_not_500(hub: Hub) -> None:
    headers = await _key(["admin"])
    first = await hub.client.post(ADMIN, json=_ipp_payload(), headers=headers)
    assert first.status_code == 201, first.text
    again = await hub.client.post(ADMIN, json=_ipp_payload(name="Other"), headers=headers)
    assert again.status_code == 409, again.text
    assert again.json()["detail"]["error_code"] == "duplicate_slug"
    row = await _db_printer("office-laser")
    assert row is not None
    assert len(await _db_trays(row.id)) == 2


# ---------------------------------------------------------------------------- calibration vs trays

CAL_BODY = {
    "offset_x_mm": 1.2,
    "offset_y_mm": -0.4,
    "scale_x": 1.001,
    "scale_y": 0.999,
    "rotation_deg": 0.3,
}


async def _db_calibration_keys(printer_id: UUID) -> list[str]:
    async with _factory()() as s:
        rows = (
            await s.execute(
                select(PrinterCalibration.tray_key)
                .where(PrinterCalibration.printer_id == printer_id)
                .order_by(PrinterCalibration.tray_key)
            )
        ).scalars()
        return list(rows)


async def _calibrate(hub: Hub, headers: dict[str, str], tray: str) -> httpx.Response:
    return await hub.client.put(
        f"/api/v1/printers/{await _printer_id()}/calibration/{tray}", json=CAL_BODY, headers=headers
    )


async def _printer_id() -> UUID:
    row = await _db_printer("office-laser")
    assert row is not None
    return row.id


@pytest.mark.asyncio
async def test_removed_tray_loses_its_calibration_and_a_re_added_one_starts_clean(
    hub: Hub,
) -> None:
    headers = await _created(hub)  # trays: auto, tray-2
    assert (await _calibrate(hub, headers, "tray-2")).status_code == 200
    assert (await _calibrate(hub, headers, "auto")).status_code == 200
    pid = await _printer_id()
    resp = await hub.client.put(f"{ADMIN}/office-laser", json={"trays": _trays()}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert await _db_calibration_keys(pid) == ["auto"]  # tray-2 is gone, auto stays
    resp = await hub.client.put(
        f"{ADMIN}/office-laser", json={"trays": _trays("tray-2")}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    got = await hub.client.get(f"/api/v1/printers/{pid}/calibration", headers=headers)
    by_tray = {r["tray"]: r for r in got.json()}
    assert by_tray["tray-2"]["method"] is None  # not the deviation of the old setup
    assert by_tray["auto"]["method"] == "manual"


@pytest.mark.asyncio
async def test_disabled_tray_keeps_its_calibration(hub: Hub) -> None:
    headers = await _created(hub)
    assert (await _calibrate(hub, headers, "tray-2")).status_code == 200
    pid = await _printer_id()
    disabled = [
        {"key": "auto", "label": "Automatic", "is_default": True},
        {"key": "tray-2", "label": "Tray tray-2", "enabled": False},
    ]
    resp = await hub.client.put(f"{ADMIN}/office-laser", json={"trays": disabled}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert await _db_calibration_keys(pid) == ["tray-2"]
    enabled = [{**disabled[0]}, {**disabled[1], "enabled": True}]
    resp = await hub.client.put(f"{ADMIN}/office-laser", json={"trays": enabled}, headers=headers)
    assert resp.status_code == 200, resp.text
    got = await hub.client.get(f"/api/v1/printers/{pid}/calibration", headers=headers)
    assert {r["tray"]: r["method"] for r in got.json()}["tray-2"] == "manual"


@pytest.mark.asyncio
async def test_calibration_put_that_loses_the_race_to_a_tray_removal_leaves_no_row(
    hub: Hub,
) -> None:
    """Deterministic interleaving: the PUT passes its first tray check, then the tray goes.

    The re-check inside the write lock must refuse; a row written anyway would be an
    orphan that comes back when the tray is re-added.
    """
    from app.calibration import service

    headers = await _created(hub)
    pid = await _printer_id()
    real = service._check_tray
    calls = 0

    async def removing_after_first_check(session: Any, printer_id: UUID, tray: str) -> None:
        nonlocal calls
        calls += 1
        await real(session, printer_id, tray)
        if calls == 1:  # the PUT has decided the tray exists; the admin removes it now
            resp = await hub.client.put(
                f"{ADMIN}/office-laser", json={"trays": _trays()}, headers=headers
            )
            assert resp.status_code == 200, resp.text

    with patch.object(service, "_check_tray", removing_after_first_check):
        put = await _calibrate(hub, headers, "tray-2")
    assert put.status_code == 422, put.text
    assert _error(put)["error_code"] == "tray_unknown"
    assert calls == 2
    assert await _db_calibration_keys(pid) == []


@pytest.mark.asyncio
async def test_calibration_put_that_wins_the_race_is_cleaned_by_the_removal(hub: Hub) -> None:
    """The other order: the PUT commits first, the removal then deletes its row."""
    from app.calibration import service

    headers = await _created(hub)
    pid = await _printer_id()
    real_put = service.put

    async def put_then_remove(*args: Any, **kwargs: Any) -> Any:
        out = await real_put(*args, **kwargs)  # committed
        resp = await hub.client.put(
            f"{ADMIN}/office-laser", json={"trays": _trays()}, headers=headers
        )
        assert resp.status_code == 200, resp.text
        return out

    with patch("app.api.routes.calibration.service.put", put_then_remove):
        put = await _calibrate(hub, headers, "tray-2")
    assert put.status_code == 200, put.text
    assert await _db_calibration_keys(pid) == []


@pytest.mark.asyncio
async def test_probe_log_line_cannot_be_forged_through_the_name(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``log_name`` comes from the request: line breaks and control characters stay out."""
    import logging

    from app.schemas.printer_admin import IppConnection
    from app.services.printer_admin_service import probe_ipp
    from app.sheets.errors import IppUnreachableApiError

    with (
        caplog.at_level(logging.WARNING, logger="app.services.printer_admin_service"),
        pytest.raises(IppUnreachableApiError),
    ):
        await probe_ipp(
            IppConnection(uri=URI),
            queue_timeout_s=5,
            transport_factory=lambda _uri: _unreachable_transport(),
            log_name="evil\r\n2026-01-01 ERROR forged entry\x1b[2K",
        )
    (record,) = [r for r in caplog.records if "IPP probe for" in r.getMessage()]
    message = record.getMessage()
    assert "\n" not in message and "\r" not in message and "\x1b" not in message
    assert "evil2026-01-01 ERROR forged entry[2K" in message
