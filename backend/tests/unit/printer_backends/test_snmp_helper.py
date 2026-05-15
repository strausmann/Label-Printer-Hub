from __future__ import annotations

import pytest
from app.printer_backends.exceptions import SnmpDiscoveryError, SnmpQueryError
from app.printer_backends.snmp_helper import (
    BROTHER_PJL_OID,
    HR_PRINTER_DETECTED_ERROR_STATE_OID,
    HR_PRINTER_STATUS_OID,
    LiveStatus,
    decode_error_flags,
    query_live_status,
    query_model_pjl,
)


def test_oid_constants() -> None:
    assert BROTHER_PJL_OID == "1.3.6.1.4.1.2435.2.3.9.1.1.7.0"
    assert HR_PRINTER_STATUS_OID == "1.3.6.1.2.1.25.3.5.1.1.1"
    assert HR_PRINTER_DETECTED_ERROR_STATE_OID == "1.3.6.1.2.1.25.3.5.1.2.1"


def test_decode_error_flags_no_paper() -> None:
    assert "noPaper" in decode_error_flags(b"\x40\x00")


def test_decode_error_flags_door_open() -> None:
    assert "doorOpen" in decode_error_flags(b"\x08\x00")


def test_decode_error_flags_jammed() -> None:
    assert "jammed" in decode_error_flags(b"\x04\x00")


def test_decode_error_flags_empty_when_no_bits() -> None:
    assert decode_error_flags(b"\x00\x00") == []


async def test_query_model_pjl_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    expected_pjl = "MFG:Brother;CMD:PJL;MDL:PT-P750W;CLS:PRINTER;DES:Brother PT-P750W;"

    async def fake_get_cmd(*args, **_kwargs):
        from pysnmp.proto import rfc1902

        # Mimic: (errorIndication, errorStatus, errorIndex, varBinds)
        # args = (engine, community, transport, ctx, *object_types)
        first_oid = args[4]
        return (None, None, 0, [(first_oid, rfc1902.OctetString(expected_pjl))])

    monkeypatch.setattr("app.printer_backends.snmp_helper.get_cmd", fake_get_cmd)
    pjl = await query_model_pjl("10.0.0.5", community="public", timeout_s=1.0)
    assert pjl == expected_pjl


async def test_query_model_pjl_timeout_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_cmd(*_a, **_kw):
        return ("requestTimedOut", None, 0, [])

    monkeypatch.setattr("app.printer_backends.snmp_helper.get_cmd", fake_get_cmd)
    with pytest.raises(SnmpDiscoveryError, match=r"timed out|requestTimedOut"):
        await query_model_pjl("10.0.0.5", community="public", timeout_s=1.0)


async def test_query_live_status_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from pysnmp.proto import rfc1902

    async def fake_get_cmd(*args, **_kwargs):
        # args[4] = first OT (status), args[5] = second OT (error state)
        first_oid = args[4]
        second_oid = args[5]
        return (
            None,
            None,
            0,
            [
                (first_oid, rfc1902.Integer(4)),  # printing
                (second_oid, rfc1902.OctetString(b"\x40\x00")),  # noPaper bit
            ],
        )

    monkeypatch.setattr("app.printer_backends.snmp_helper.get_cmd", fake_get_cmd)
    ls = await query_live_status("10.0.0.5", community="public", timeout_s=1.0)
    assert isinstance(ls, LiveStatus)
    assert ls.hr_printer_status == "printing"
    assert "noPaper" in ls.error_flags


async def test_query_live_status_failure_is_separate_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_cmd(*_a, **_kw):
        return ("requestTimedOut", None, 0, [])

    monkeypatch.setattr("app.printer_backends.snmp_helper.get_cmd", fake_get_cmd)
    with pytest.raises(SnmpQueryError):
        await query_live_status("10.0.0.5", community="public", timeout_s=1.0)
