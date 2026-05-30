from __future__ import annotations

import pytest
from app.printer_backends.exceptions import SnmpDiscoveryError, SnmpQueryError
from app.printer_backends.snmp_helper import (
    BROTHER_PJL_OID,
    HR_PRINTER_DETECTED_ERROR_STATE_OID,
    HR_PRINTER_STATUS_OID,
    PRT_INPUT_MEDIA_TYPE_OID,
    LiveStatus,
    PreflightStatus,
    decode_error_flags,
    parse_loaded_tape_mm,
    query_live_status,
    query_loaded_tape_mm,
    query_model_pjl,
    query_preflight,
)


async def test_snmp_engine_is_singleton_across_query_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multiple SNMP query calls must use the SAME SnmpEngine instance.

    Creating a new SnmpEngine per call loads MIBs and initialises the
    async dispatcher on every invocation, adding significant overhead.
    A module-level singleton eliminates this cost.
    """
    from pysnmp.proto import rfc1902

    engines_seen: list[object] = []

    async def capturing_get_cmd(*args: object, **_kwargs: object) -> object:
        # args[0] is the SnmpEngine passed by the helper function
        engines_seen.append(args[0])
        first_oid = args[4]
        return (None, None, 0, [(first_oid, rfc1902.OctetString('12mm(0.47")'))])

    monkeypatch.setattr("app.printer_backends.snmp_helper.get_cmd", capturing_get_cmd)
    await query_loaded_tape_mm("192.0.2.1", community="public", timeout_s=1.0)
    await query_loaded_tape_mm("192.0.2.1", community="public", timeout_s=1.0)

    assert len(engines_seen) == 2, "Expected get_cmd to be called twice"
    assert engines_seen[0] is engines_seen[1], (
        "Both calls must pass the SAME SnmpEngine instance (singleton), "
        f"but got {type(engines_seen[0])} and {type(engines_seen[1])} at different addresses"
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
    pjl = await query_model_pjl("192.0.2.10", community="public", timeout_s=1.0)
    assert pjl == expected_pjl


async def test_query_model_pjl_timeout_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_cmd(*_a, **_kw):
        return ("requestTimedOut", None, 0, [])

    monkeypatch.setattr("app.printer_backends.snmp_helper.get_cmd", fake_get_cmd)
    with pytest.raises(SnmpDiscoveryError, match=r"timed out|requestTimedOut"):
        await query_model_pjl("192.0.2.10", community="public", timeout_s=1.0)


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
    ls = await query_live_status("192.0.2.10", community="public", timeout_s=1.0)
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
        await query_live_status("192.0.2.10", community="public", timeout_s=1.0)


def test_prt_input_media_type_oid_constant() -> None:
    assert PRT_INPUT_MEDIA_TYPE_OID == "1.3.6.1.2.1.43.8.2.1.12.1.1"


@pytest.mark.parametrize(
    "text,expected",
    [
        ('12mm(0.47")', 12),
        ('24mm(0.94")', 24),
        ("12mm", 12),
        ('9mm(0.35")', 9),
        ("36mm", 36),
        ("", None),
        ("None", None),
        ("no tape", None),
        ("\x00", None),
    ],
)
def test_parse_loaded_tape_mm(text: str, expected: int | None) -> None:
    assert parse_loaded_tape_mm(text) == expected


async def test_query_loaded_tape_mm_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from pysnmp.proto import rfc1902

    async def fake_get_cmd(*args, **_kwargs):
        first_oid = args[4]
        return (None, None, 0, [(first_oid, rfc1902.OctetString('12mm(0.47")'))])

    monkeypatch.setattr("app.printer_backends.snmp_helper.get_cmd", fake_get_cmd)
    mm = await query_loaded_tape_mm("192.0.2.10", community="public", timeout_s=1.0)
    assert mm == 12


async def test_query_loaded_tape_mm_no_tape(monkeypatch: pytest.MonkeyPatch) -> None:
    from pysnmp.proto import rfc1902

    async def fake_get_cmd(*args, **_kwargs):
        first_oid = args[4]
        return (None, None, 0, [(first_oid, rfc1902.OctetString(""))])

    monkeypatch.setattr("app.printer_backends.snmp_helper.get_cmd", fake_get_cmd)
    mm = await query_loaded_tape_mm("192.0.2.10", community="public", timeout_s=1.0)
    assert mm is None


async def test_query_loaded_tape_mm_timeout_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.printer_backends.exceptions import SnmpQueryError

    async def fake_get_cmd(*_a, **_kw):
        return ("requestTimedOut", None, 0, [])

    monkeypatch.setattr("app.printer_backends.snmp_helper.get_cmd", fake_get_cmd)
    with pytest.raises(SnmpQueryError):
        await query_loaded_tape_mm("192.0.2.10", community="public", timeout_s=1.0)


async def test_query_preflight_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from pysnmp.proto import rfc1902

    async def fake_get_cmd(*args, **_kwargs):
        # args[4..6] are the three ObjectType wrappers for status, errors, media-type
        oids = [args[i] for i in (4, 5, 6)]
        return (
            None,
            None,
            0,
            [
                (oids[0], rfc1902.Integer(3)),  # idle
                (oids[1], rfc1902.OctetString(b"\x00\x00")),  # no errors
                (oids[2], rfc1902.OctetString('12mm(0.47")')),
            ],
        )

    monkeypatch.setattr("app.printer_backends.snmp_helper.get_cmd", fake_get_cmd)
    pf = await query_preflight("192.0.2.10", community="public", timeout_s=1.0)
    assert isinstance(pf, PreflightStatus)
    assert pf.hr_printer_status == "idle"
    assert pf.loaded_tape_mm == 12
    assert pf.error_flags == []


async def test_query_preflight_propagates_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from pysnmp.proto import rfc1902

    async def fake_get_cmd(*args, **_kwargs):
        oids = [args[i] for i in (4, 5, 6)]
        return (
            None,
            None,
            0,
            [
                (oids[0], rfc1902.Integer(3)),
                (oids[1], rfc1902.OctetString(b"\x08\x00")),  # doorOpen bit
                (oids[2], rfc1902.OctetString('12mm(0.47")')),
            ],
        )

    monkeypatch.setattr("app.printer_backends.snmp_helper.get_cmd", fake_get_cmd)
    pf = await query_preflight("192.0.2.10", community="public", timeout_s=1.0)
    assert "doorOpen" in pf.error_flags


def test_get_engine_lazy_init_returns_snmp_engine() -> None:
    """_get_engine() must return a SnmpEngine instance (lazy initialisation)."""
    import app.printer_backends.snmp_helper as helper
    from pysnmp.hlapi.v3arch.asyncio import SnmpEngine

    # Reset module-level state so we get a clean lazy-init path
    helper._SNMP_ENGINE = None
    engine = helper._get_engine()
    assert isinstance(engine, SnmpEngine)


def test_get_engine_returns_same_instance_when_loop_is_open() -> None:
    """_get_engine() must be idempotent: same instance returned on repeated calls.

    Wrapped in asyncio.run() because _get_engine() consults the current event
    loop — without a running loop, asyncio.get_event_loop() emits a deprecation
    or raises RuntimeError (Py 3.12+), causing the cached engine to be
    discarded between calls. CI surfaced this; locally it passed because
    pytest-asyncio's loop-policy left a usable loop attached.
    """
    import asyncio

    import app.printer_backends.snmp_helper as helper

    async def _check() -> None:
        helper._SNMP_ENGINE = None
        engine_a = helper._get_engine()
        engine_b = helper._get_engine()
        assert engine_a is engine_b

    asyncio.run(_check())


def test_get_engine_reinitialises_after_closed_loop() -> None:
    """When the cached engine's event loop is closed, _get_engine() creates a fresh one.

    This guards against the test-suite scenario where a fresh asyncio event loop is
    created between test sessions, leaving the module-level singleton bound to a
    closed loop.
    """
    import asyncio

    import app.printer_backends.snmp_helper as helper

    # Obtain an initial engine (may already exist from earlier tests)
    helper._SNMP_ENGINE = None
    engine_a = helper._get_engine()
    assert engine_a is not None

    # Simulate a closed event loop by temporarily closing the current one
    loop = asyncio.new_event_loop()
    loop.close()
    # Force the helper to detect a closed loop by substituting it as the running loop.
    # We do this by calling asyncio.set_event_loop with the closed loop, then resetting.
    asyncio.set_event_loop(loop)
    try:
        engine_b = helper._get_engine()
        # Engine must be a new instance because the loop is closed
        assert engine_b is not engine_a, (
            "_get_engine() must create a new SnmpEngine when the event loop is closed"
        )
    finally:
        # Restore a working event loop for subsequent tests
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
