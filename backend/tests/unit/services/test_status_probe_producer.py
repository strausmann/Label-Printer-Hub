# backend/tests/unit/services/test_status_probe_producer.py
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.printer_backends.snmp_helper import PreflightStatus
from app.services.event_bus import BusEvent, EventBus
from app.services.producers.status_probe_producer import StatusProbeProducer


def _make_bus() -> MagicMock:
    bus = MagicMock(spec=EventBus)
    bus.next_event_id.return_value = 1
    return bus


def _status(hr: str = "idle", tape: int | None = 12) -> PreflightStatus:
    return PreflightStatus(hr_printer_status=hr, loaded_tape_mm=tape, error_flags=[])


@pytest.mark.asyncio
async def test_first_probe_always_publishes() -> None:
    bus = _make_bus()
    tape_producer = MagicMock()
    with patch(
        "app.services.producers.status_probe_producer.query_preflight",
        new_callable=AsyncMock,
        return_value=_status("idle"),
    ):
        producer = StatusProbeProducer(
            bus=bus,
            printer_id="p1",
            host="198.51.100.1",
            interval_s=0.001,
            tape_change_producer=tape_producer,
        )
        await producer.start()
        await asyncio.sleep(0.05)
        await producer.stop()

    assert bus.publish.call_count >= 1
    event: BusEvent = bus.publish.call_args_list[0][0][1]
    assert event.event_type == "printer.status"
    assert event.data["online"] is True


@pytest.mark.asyncio
async def test_no_publish_when_status_unchanged() -> None:
    bus = _make_bus()
    tape_producer = MagicMock()
    call_count = 0

    async def _same_status(*args: object, **kwargs: object) -> PreflightStatus:
        nonlocal call_count
        call_count += 1
        return _status("idle")

    with patch(
        "app.services.producers.status_probe_producer.query_preflight",
        side_effect=_same_status,
    ):
        producer = StatusProbeProducer(
            bus=bus,
            printer_id="p1",
            host="198.51.100.1",
            interval_s=0.01,
            tape_change_producer=tape_producer,
        )
        await producer.start()
        # Wait for at least 2 probe cycles
        while call_count < 2:
            await asyncio.sleep(0.01)
        await producer.stop()

    # First publish on first probe; no more after that (status unchanged)
    assert bus.publish.call_count == 1


@pytest.mark.asyncio
async def test_publishes_on_status_change() -> None:
    bus = _make_bus()
    tape_producer = MagicMock()
    statuses = [_status("idle"), _status("printing")]
    idx = 0

    async def _cycle(*args: object, **kwargs: object) -> PreflightStatus:
        nonlocal idx
        s = statuses[min(idx, len(statuses) - 1)]
        idx += 1
        return s

    with patch(
        "app.services.producers.status_probe_producer.query_preflight",
        side_effect=_cycle,
    ):
        producer = StatusProbeProducer(
            bus=bus,
            printer_id="p1",
            host="198.51.100.1",
            interval_s=0.01,
            tape_change_producer=tape_producer,
        )
        await producer.start()
        while idx < 2:
            await asyncio.sleep(0.01)
        await producer.stop()

    assert bus.publish.call_count == 2


@pytest.mark.asyncio
async def test_snmp_exception_publishes_offline_event() -> None:
    bus = _make_bus()
    tape_producer = MagicMock()
    with patch(
        "app.services.producers.status_probe_producer.query_preflight",
        new_callable=AsyncMock,
        side_effect=Exception("timeout"),
    ):
        producer = StatusProbeProducer(
            bus=bus,
            printer_id="p1",
            host="198.51.100.1",
            interval_s=0.001,
            tape_change_producer=tape_producer,
        )
        await producer.start()
        await asyncio.sleep(0.05)
        await producer.stop()

    assert bus.publish.call_count >= 1
    event: BusEvent = bus.publish.call_args_list[0][0][1]
    assert event.data["online"] is False
