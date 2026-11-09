"""Both status producers hand a hardware identity to the sink after a successful probe (#231).

Real temp database (foreign keys on), SNMP and IPP faked; nothing touches the network.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import UUID

import app.db.engine as _eng
import app.models  # noqa: F401
import httpx
import pytest
import pytest_asyncio
from app.models.printer import Printer
from app.models.printer_identity import PrinterIdentity
from app.models.printer_status_cache import PrinterStatusCache
from app.printer_backends.ipp.client import IppClient
from app.printer_backends.snmp_helper import ObservedIdentity, PreflightStatus
from app.services.event_bus import EventBus
from app.services.hardware_identity import record_identity
from app.services.producers.ipp_status_producer import IppPrinterState, IppStatusProducer
from app.services.producers.status_probe_producer import StatusProbeProducer

from tests.helpers.fake_ipp_printer import FAKE_URI, FakeIppPrinter
from tests.integration.api.test_printer_live_wiring import (  # noqa: F401  (fixture + helpers)
    ADMIN,
    URI,
    URI_2,
    Live,
    _create,
    _until,
    _wait_online,
    live,
)

pytestmark = pytest.mark.asyncio

SERIAL = "E1234567ABC"
OTHER_SERIAL = "E7654321XYZ"
PRINTER_UUID = "urn:uuid:12345678-1234-5678-1234-567812345678"
BARE_UUID = "12345678-1234-5678-1234-567812345678"
OK = PreflightStatus(hr_printer_status="idle", loaded_tape_mm=12, error_flags=[])


@pytest_asyncio.fixture
async def printer_id() -> UUID:
    async with _eng.async_session() as s:
        p = Printer(
            name="identity-test",
            model="PT-P750W",
            backend="ptouch",
            connection={"host": "192.0.2.10", "port": 9100},
        )
        s.add(p)
        await s.commit()
        await s.refresh(p)
        return p.id


class Sink:
    """The real ``record_identity`` behind the sink contract, remembering every outcome."""

    def __init__(self) -> None:
        self.outcomes: list[str] = []
        self.calls = 0

    async def __call__(self, printer_id: UUID, observed: ObservedIdentity) -> str:
        self.calls += 1
        outcome = await record_identity(
            printer_id, observed, datetime.now(UTC), session_factory=_eng.async_session
        )
        self.outcomes.append(outcome)
        return outcome


def _snmp_producer(pid: UUID, sink: object) -> StatusProbeProducer:
    return StatusProbeProducer(
        bus=EventBus(),
        printer_id=str(pid),
        host="192.0.2.10",
        identity_sink=sink,  # type: ignore[arg-type]
    )


def _ipp_producer(pid: UUID, fake: FakeIppPrinter, sink: object) -> IppStatusProducer:
    return IppStatusProducer(
        bus=EventBus(),
        printer_id=pid,
        client=IppClient(FAKE_URI, transport=httpx.ASGITransport(app=fake)),
        session_factory=_eng.async_session,
        state=IppPrinterState(),
        pause_control=None,
        interval_s=30.0,
        identity_sink=sink,  # type: ignore[arg-type]
    )


def _snmp_patches(identity: ObservedIdentity | Exception | None, preflight=OK):
    ident = (
        AsyncMock(side_effect=identity)
        if isinstance(identity, Exception)
        else AsyncMock(return_value=identity or ObservedIdentity(None, None, None))
    )
    pre = (
        AsyncMock(side_effect=preflight)
        if isinstance(preflight, Exception)
        else AsyncMock(return_value=preflight)
    )
    return (
        patch("app.services.producers.status_probe_producer.query_preflight", pre),
        patch("app.services.producers.status_probe_producer.query_identity", ident),
    )


async def _identity(pid: UUID) -> PrinterIdentity | None:
    async with _eng.async_session() as s:
        return await s.get(PrinterIdentity, pid)


async def _cache(pid: UUID) -> PrinterStatusCache:
    async with _eng.async_session() as s:
        row = await s.get(PrinterStatusCache, pid)
    assert row is not None
    return row


async def test_first_probe_stores_identity(printer_id: UUID) -> None:
    sink = Sink()
    pre, ident = _snmp_patches(ObservedIdentity(SERIAL, None, "00:80:77:12:34:56"))
    with pre, ident:
        await _snmp_producer(printer_id, sink)._probe_once()
        await _snmp_producer(printer_id, sink)._probe_once()
    row = await _identity(printer_id)
    assert row is not None and (row.hardware_id, row.hardware_id_kind) == (SERIAL, "serial")
    assert sink.outcomes == ["stored", "seen"]


async def test_ipp_probe_stores_printer_uuid(printer_id: UUID) -> None:
    sink = Sink()
    fake = FakeIppPrinter(printer_uuid=PRINTER_UUID)
    producer = _ipp_producer(printer_id, fake, sink)
    assert await producer.probe_once() is not None
    row = await _identity(printer_id)
    assert row is not None and (row.hardware_id, row.hardware_id_kind) == (BARE_UUID, "ipp_uuid")
    assert sink.outcomes == ["stored"]
    await producer.stop()


async def test_status_cache_has_no_identity(printer_id: UUID) -> None:
    sink = Sink()
    producer = _ipp_producer(printer_id, FakeIppPrinter(printer_uuid=PRINTER_UUID), sink)
    await producer.probe_once()
    await producer.stop()
    assert sink.outcomes == ["stored"]  # the uuid was seen ...
    dumped = json.dumps((await _cache(printer_id)).parsed).lower()
    assert BARE_UUID not in dumped  # ... and is nowhere in what the status API serves
    assert "uuid" not in dumped


async def test_ipp_probe_without_uuid_reports_nothing(printer_id: UUID) -> None:
    sink = Sink()
    producer = _ipp_producer(printer_id, FakeIppPrinter(), sink)
    await producer.probe_once()
    await producer.stop()
    assert sink.outcomes == ["none"]
    assert await _identity(printer_id) is None


async def test_identity_query_failure_never_fails_probe(
    printer_id: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = Sink()

    async def boom(*_a: object, **_k: object) -> object:
        raise OSError("snmp down")

    monkeypatch.setattr("app.printer_backends.snmp_helper.get_cmd", boom)
    with patch(
        "app.services.producers.status_probe_producer.query_preflight",
        AsyncMock(return_value=OK),
    ):
        await _snmp_producer(printer_id, sink)._probe_once()
    assert (await _cache(printer_id)).parsed["online"] is True
    assert sink.outcomes == ["none"]  # the observed identity was empty
    assert await _identity(printer_id) is None


async def test_a_failing_sink_never_fails_probe(printer_id: UUID) -> None:
    async def broken(_pid: UUID, _obs: ObservedIdentity) -> str:
        raise RuntimeError("database is locked")

    pre, ident = _snmp_patches(ObservedIdentity(SERIAL, None, None))
    with pre, ident:
        await _snmp_producer(printer_id, broken)._probe_once()
    assert (await _cache(printer_id)).parsed["online"] is True

    fake = FakeIppPrinter(printer_uuid=PRINTER_UUID)
    producer = _ipp_producer(printer_id, fake, broken)
    assert await producer.probe_once() is not None  # still a successful probe
    await producer.stop()


async def test_probe_without_identity_keeps_stored(printer_id: UUID) -> None:
    sink = Sink()
    pre, ident = _snmp_patches(ObservedIdentity(SERIAL, None, None))
    with pre, ident:
        await _snmp_producer(printer_id, sink)._probe_once()
    stored = await _identity(printer_id)
    assert stored is not None
    pre, ident = _snmp_patches(None)  # the agent hiccups: nothing reported
    with pre, ident:
        await _snmp_producer(printer_id, sink)._probe_once()
    after = await _identity(printer_id)
    assert after is not None
    assert (after.hardware_id, after.hardware_id_kind) == (SERIAL, "serial")
    assert after.hardware_id_seen_at == stored.hardware_id_seen_at
    assert sink.outcomes == ["stored", "none"]


async def test_failed_probe_does_not_touch_identity(printer_id: UUID) -> None:
    sink = Sink()
    pre, ident = _snmp_patches(ObservedIdentity(SERIAL, None, None))
    with pre, ident:
        await _snmp_producer(printer_id, sink)._probe_once()
    stored = await _identity(printer_id)
    calls = sink.calls
    pre, ident = _snmp_patches(ObservedIdentity(OTHER_SERIAL, None, None), preflight=OSError("x"))
    with pre, ident as identity_query:
        await _snmp_producer(printer_id, sink)._probe_once()
    assert identity_query.await_count == 0  # not even asked
    assert sink.calls == calls
    assert (await _cache(printer_id)).parsed["online"] is False
    after = await _identity(printer_id)
    assert after is not None and stored is not None
    assert after.hardware_id == SERIAL
    assert after.hardware_id_seen_at == stored.hardware_id_seen_at

    # IPP: an unreachable printer does not reach the sink either
    ipp_sink = Sink()
    producer = _ipp_producer(printer_id, FakeIppPrinter(printer_uuid=PRINTER_UUID), ipp_sink)
    producer._client = IppClient(  # type: ignore[attr-defined]
        FAKE_URI, transport=_Unreachable()
    )
    assert await producer.probe_once() is None
    assert ipp_sink.calls == 0
    await producer.stop()


class _Unreachable(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)


async def test_probe_does_not_change_printer_updated_at(printer_id: UUID) -> None:
    async with _eng.async_session() as s:
        before = (await s.get(Printer, printer_id)).updated_at  # type: ignore[union-attr]
    sink = Sink()
    pre, ident = _snmp_patches(ObservedIdentity(SERIAL, None, "00:80:77:12:34:56"))
    with pre, ident:
        for _ in range(3):
            await _snmp_producer(printer_id, sink)._probe_once()
    assert sink.outcomes == ["stored", "seen", "seen"]
    async with _eng.async_session() as s:
        after = (await s.get(Printer, printer_id)).updated_at  # type: ignore[union-attr]
    assert after == before


# ---------------------------------------------------------------------------- admin re-wire


async def test_connection_change_keeps_identity(live: Live) -> None:  # noqa: F811
    outcomes: list[str] = []

    async def spy(*args: object, **kwargs: object) -> str:
        outcome = await record_identity(*args, **kwargs)  # type: ignore[arg-type]
        outcomes.append(outcome)
        return outcome

    live.fakes[URI].printer_uuid = PRINTER_UUID
    live.fakes[URI_2].printer_uuid = PRINTER_UUID  # the same device, behind another address
    with patch("app.services.printer_runtime.record_identity", spy):
        pid = await _create(live)
        await _wait_online(live, pid)

        await _until(_stored(pid), "identity stored")
        stored = await _identity(pid)
        assert stored is not None and stored.hardware_id == BARE_UUID

        resp = await live.client.put(f"{ADMIN}/office-laser", json={"connection": {"uri": URI_2}})
        assert resp.status_code == 200, resp.text
        after_put = await _identity(pid)
        assert after_put is not None  # update_printer left the row alone
        assert (after_put.hardware_id, after_put.hardware_id_kind) == (BARE_UUID, "ipp_uuid")

        probes = live.gpa(URI_2)
        await _until(_probed_since(live, URI_2, probes + 2), "probes on the new address")
        assert "seen" in outcomes and "different" not in outcomes
        row = await _identity(pid)
        assert row is not None and row.hardware_id == BARE_UUID
        assert (row.observed_id, row.mismatch_since) == (None, None)

        # another device behind the address: different, and the stored identity stays
        outcomes.clear()
        live.fakes[URI_2].printer_uuid = "urn:uuid:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        await _until(_has_outcome(outcomes, "different"), "different outcome")
        row = await _identity(pid)
        assert row is not None and row.hardware_id == BARE_UUID


def _stored(pid: UUID) -> Callable[[], Awaitable[bool]]:
    async def check() -> bool:
        return await _identity(pid) is not None

    return check


def _probed_since(live_: Live, uri: str, n: int) -> Callable[[], Awaitable[bool]]:
    async def check() -> bool:
        return live_.gpa(uri) >= n

    return check


def _has_outcome(outcomes: list[str], wanted: str) -> Callable[[], Awaitable[bool]]:
    async def check() -> bool:
        await asyncio.sleep(0)
        return wanted in outcomes

    return check
