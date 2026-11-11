"""Hardware identity (#231): pick, normalise and the store/compare rules of ``record_identity``."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import app.models  # noqa: F401
import pytest
from app.models.printer_identity import PrinterIdentity
from app.printer_backends.snmp_helper import ObservedIdentity, format_mac
from app.services.hardware_identity import (
    HardwareIdentity,
    normalise,
    pick_identity,
    record_identity,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 11, 9, 12, 0, 0, tzinfo=UTC)
SERIAL = "E1234567ABC"
OTHER_SERIAL = "E7654321XYZ"
UUID_URN = "URN:UUID:12345678-1234-5678-1234-567812345678"
UUID_BARE = "12345678-1234-5678-1234-567812345678"
MAC_X = "00:80:77:12:34:56"
MAC_Y = "00:80:77:ab:cd:ef"


def _obs(
    serial: str | None = None, ipp_uuid: str | None = None, mac: str | None = None
) -> ObservedIdentity:
    return ObservedIdentity(serial=serial, ipp_uuid=ipp_uuid, mac=mac)


async def _row(factory: async_sessionmaker[AsyncSession], pid: UUID) -> PrinterIdentity | None:
    async with factory() as s:
        return await s.get(PrinterIdentity, pid)


async def _record(factory, pid: UUID, observed: ObservedIdentity, now: datetime = T0) -> str:
    return await record_identity(pid, observed, now, session_factory=factory)


# ---------------------------------------------------------------- pick / normalise


async def test_pick_identity_order() -> None:
    everything = _obs(SERIAL, UUID_BARE, MAC_X)
    assert pick_identity(everything) == HardwareIdentity("serial", SERIAL)
    assert pick_identity(_obs(None, UUID_BARE, MAC_X)) == HardwareIdentity("ipp_uuid", UUID_BARE)
    assert pick_identity(_obs(None, None, MAC_X)) == HardwareIdentity("mac", MAC_X)
    assert pick_identity(_obs()) is None


async def test_normalise() -> None:
    out = normalise(_obs("  " + SERIAL + "\n", UUID_URN, "00-80-77-12-34-56"))
    assert out == _obs(SERIAL, UUID_BARE, MAC_X)
    assert normalise(_obs("   ", "", "")) == _obs()
    # Some agents pad the OCTET STRING with NULs; they are not part of the serial.
    assert normalise(_obs(SERIAL + "\x00\x00\x00")) == _obs(SERIAL)
    assert normalise(_obs("\x00\x00")) == _obs()
    assert normalise(_obs(mac="00:00:00:00:00:00")) == _obs()
    assert normalise(_obs(mac="not a mac")) == _obs()
    assert format_mac(b"\x00\x80\x77\x12\x34\x56") == "00:80:77:12:34:56"
    assert format_mac(b"\x00" * 6) == "00:00:00:00:00:00"  # zero is dropped by normalise
    assert format_mac(b"\x00\x80") is None  # not a MAC


# ---------------------------------------------------------------- record_identity


async def test_none_writes_nothing(async_session_factory) -> None:
    pid = uuid4()
    assert await _record(async_session_factory, pid, _obs()) == "none"
    assert await _row(async_session_factory, pid) is None


async def test_first_observation_is_stored(async_session_factory) -> None:
    pid = uuid4()
    assert await _record(async_session_factory, pid, _obs(SERIAL, None, MAC_X)) == "stored"
    row = await _row(async_session_factory, pid)
    assert row is not None
    assert (row.hardware_id, row.hardware_id_kind) == (SERIAL, "serial")
    assert row.hardware_id_seen_at is not None
    assert (row.observed_id, row.observed_kind, row.mismatch_since) == (None, None, None)


async def test_same_identity_is_seen(async_session_factory) -> None:
    pid = uuid4()
    await _record(async_session_factory, pid, _obs(SERIAL))
    assert await _record(async_session_factory, pid, _obs(SERIAL)) == "seen"


async def test_probe_without_identity_keeps_stored(async_session_factory) -> None:
    pid = uuid4()
    await _record(async_session_factory, pid, _obs(SERIAL))
    before = await _row(async_session_factory, pid)
    assert await _record(async_session_factory, pid, _obs(), T0 + timedelta(hours=1)) == "none"
    after = await _row(async_session_factory, pid)
    assert after is not None and before is not None
    assert (after.hardware_id, after.hardware_id_kind) == (SERIAL, "serial")
    assert after.hardware_id_seen_at == before.hardware_id_seen_at


async def test_stored_kind_absent_is_kept(async_session_factory) -> None:
    pid = uuid4()
    await _record(async_session_factory, pid, _obs(SERIAL))
    # A firmware hiccup: the serial OID is silent once, the MAC answers.
    assert await _record(async_session_factory, pid, _obs(None, None, MAC_X)) == "kept"
    row = await _row(async_session_factory, pid)
    assert row is not None and (row.hardware_id, row.hardware_id_kind) == (SERIAL, "serial")


async def test_different_value_of_the_stored_kind(async_session_factory) -> None:
    pid = uuid4()
    await _record(async_session_factory, pid, _obs(SERIAL))
    assert await _record(async_session_factory, pid, _obs(OTHER_SERIAL)) == "different"
    row = await _row(async_session_factory, pid)
    assert row is not None and row.hardware_id == SERIAL  # acted on in Task 15


async def test_mac_to_serial_upgrade_requires_matching_mac(async_session_factory) -> None:
    pid = uuid4()
    await _record(async_session_factory, pid, _obs(None, None, MAC_X))
    # Same MAC, now with a serial: upgrade.
    assert await _record(async_session_factory, pid, _obs(SERIAL, None, MAC_X)) == "kind_upgraded"
    row = await _row(async_session_factory, pid)
    assert row is not None and (row.hardware_id, row.hardware_id_kind) == (SERIAL, "serial")

    other = uuid4()
    await _record(async_session_factory, other, _obs(None, None, MAC_X))
    # A serial with another MAC is another device.
    assert await _record(async_session_factory, other, _obs(SERIAL, None, MAC_Y)) == "different"
    row = await _row(async_session_factory, other)
    assert row is not None and (row.hardware_id, row.hardware_id_kind) == (MAC_X, "mac")

    third = uuid4()
    await _record(async_session_factory, third, _obs(None, None, MAC_X))
    # A serial without a MAC cannot be compared: keep, do not upgrade.
    assert await _record(async_session_factory, third, _obs(SERIAL, None, None)) == "kept"
    row = await _row(async_session_factory, third)
    assert row is not None and (row.hardware_id, row.hardware_id_kind) == (MAC_X, "mac")


async def test_uuid_to_serial_upgrade_needs_the_uuid(async_session_factory) -> None:
    pid = uuid4()
    await _record(async_session_factory, pid, _obs(None, UUID_BARE, MAC_X))
    assert await _record(async_session_factory, pid, _obs(SERIAL, UUID_URN, None)) == (
        "kind_upgraded"
    )


async def test_swap_with_first_contact_as_mac(async_session_factory) -> None:
    pid = uuid4()
    # Printer A: the serial OID was silent at first contact, so only its MAC was stored.
    await _record(async_session_factory, pid, _obs(None, None, MAC_X))
    # Device B now sits behind the address and reports a serial and its own MAC.
    outcome = await _record(async_session_factory, pid, _obs(OTHER_SERIAL, None, MAC_Y))
    assert outcome == "different"
    assert outcome != "kind_upgraded"


async def test_seen_at_throttled(async_session_factory) -> None:
    pid = uuid4()
    await _record(async_session_factory, pid, _obs(SERIAL), T0)
    first = await _row(async_session_factory, pid)
    assert first is not None
    stamp = first.hardware_id_seen_at

    assert (
        await _record(async_session_factory, pid, _obs(SERIAL), T0 + timedelta(seconds=300))
        == "seen"
    )
    assert (
        await _record(async_session_factory, pid, _obs(SERIAL), T0 + timedelta(seconds=599))
        == "seen"
    )
    unchanged = await _row(async_session_factory, pid)
    assert unchanged is not None and unchanged.hardware_id_seen_at == stamp  # no write yet

    later = T0 + timedelta(seconds=601)
    assert await _record(async_session_factory, pid, _obs(SERIAL), later) == "seen"
    refreshed = await _row(async_session_factory, pid)
    assert refreshed is not None and refreshed.hardware_id_seen_at != stamp
    assert refreshed.hardware_id_seen_at.replace(tzinfo=UTC) == later


async def test_identity_never_logged(
    async_session_factory, caplog: pytest.LogCaptureFixture
) -> None:
    # Our own loggers at the lowest level. (The SQL driver's DEBUG log carries bound parameters
    # for every row it writes; that is the driver's log, not an identity log of ours.)
    caplog.set_level(logging.DEBUG, logger="app")
    pid = uuid4()
    secret_values = [SERIAL, OTHER_SERIAL, UUID_BARE, MAC_X, MAC_Y]
    await _record(async_session_factory, pid, _obs(SERIAL, UUID_URN, MAC_X))  # stored
    await _record(
        async_session_factory, pid, _obs(SERIAL, UUID_URN, MAC_X), T0 + timedelta(hours=1)
    )
    await _record(async_session_factory, pid, _obs(OTHER_SERIAL, None, MAC_Y))  # different
    other = uuid4()
    await _record(async_session_factory, other, _obs(None, None, MAC_X))
    await _record(async_session_factory, other, _obs(SERIAL, UUID_URN, MAC_X))  # kind_upgraded
    await _record(async_session_factory, other, _obs(None, None, MAC_Y))  # kept / different
    ours = [r for r in caplog.records if r.name.startswith("app")]
    assert ours, "the outcomes are logged (by kind)"
    text = "\n".join(r.getMessage() for r in ours).lower()
    for value in secret_values:
        assert value.lower() not in text
    assert "12345678" not in text
