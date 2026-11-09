"""``query_identity`` (#231): serial and MAC in one request, never raising; preflight unchanged."""

from __future__ import annotations

import pytest
from app.printer_backends.snmp_helper import (
    HR_PRINTER_DETECTED_ERROR_STATE_OID,
    HR_PRINTER_STATUS_OID,
    PRT_INPUT_MEDIA_TYPE_OID,
    ObservedIdentity,
    query_identity,
    query_preflight,
)
from pysnmp.proto import rfc1902, rfc1905

pytestmark = pytest.mark.asyncio

SERIAL_OID = "1.3.6.1.2.1.43.5.1.1.17.1"
MAC_OID = "1.3.6.1.2.1.2.2.1.6.1"


@pytest.fixture(autouse=True)
def _plain_oids(monkeypatch: pytest.MonkeyPatch) -> None:
    """``ObjectType(ObjectIdentity(oid))`` becomes the plain OID string, so a fake ``get_cmd``
    can read which OIDs were asked for (an unresolved pysnmp ObjectType cannot be inspected)."""
    monkeypatch.setattr("app.printer_backends.snmp_helper.ObjectIdentity", lambda oid: oid)
    monkeypatch.setattr("app.printer_backends.snmp_helper.ObjectType", lambda ident: ident)


def _oid_of(object_type: object) -> str:
    """The OID a ``get_cmd`` argument asks for (args = engine, community, transport, ctx, *OIDs)."""
    return str(object_type)


async def test_query_identity_reads_serial_and_mac(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[list[str]] = []

    async def fake_get_cmd(*args: object, **_kw: object) -> object:
        oids = [_oid_of(ot) for ot in args[4:]]
        sent.append(oids)
        return (
            None,
            None,
            0,
            [
                (args[4], rfc1902.OctetString("E1234567ABC")),
                (args[5], rfc1902.OctetString(hexValue="008077123456")),
            ],
        )

    monkeypatch.setattr("app.printer_backends.snmp_helper.get_cmd", fake_get_cmd)
    out = await query_identity("192.0.2.10")
    assert out == ObservedIdentity(serial="E1234567ABC", ipp_uuid=None, mac="00:80:77:12:34:56")
    assert len(sent) == 1 and len(sent[0]) == 2  # one request, two OIDs
    assert sent[0] == [SERIAL_OID, MAC_OID]


@pytest.mark.parametrize("failure", ["raises", "indication", "error_status", "no_such_object"])
async def test_query_identity_failure_is_empty_and_never_raised(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    async def fake_get_cmd(*args: object, **_kw: object) -> object:
        if failure == "raises":
            raise OSError("boom")
        if failure == "indication":
            return ("requestTimedOut", None, 0, [])
        if failure == "error_status":
            return (None, 2, 1, [])
        return (
            None,
            None,
            0,
            [(args[4], rfc1905.NoSuchObject()), (args[5], rfc1905.NoSuchObject())],
        )

    monkeypatch.setattr("app.printer_backends.snmp_helper.get_cmd", fake_get_cmd)
    out = await query_identity("192.0.2.10")
    assert out == ObservedIdentity(serial=None, ipp_uuid=None, mac=None)


async def test_preflight_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[list[str]] = []

    async def fake_get_cmd(*args: object, **_kw: object) -> object:
        sent.append([_oid_of(ot) for ot in args[4:]])
        return (
            None,
            None,
            0,
            [
                (args[4], rfc1902.Integer(3)),
                (args[5], rfc1902.OctetString(b"\x00\x00")),
                (args[6], rfc1902.OctetString('12mm(0.47")')),
            ],
        )

    monkeypatch.setattr("app.printer_backends.snmp_helper.get_cmd", fake_get_cmd)
    status = await query_preflight("192.0.2.10")
    assert status.loaded_tape_mm == 12
    assert sent == [
        [HR_PRINTER_STATUS_OID, HR_PRINTER_DETECTED_ERROR_STATE_OID, PRT_INPUT_MEDIA_TYPE_OID]
    ]
