# backend/tests/unit/services/test_status_probe_producer.py
from __future__ import annotations

import asyncio
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


# ---------------------------------------------------------------------------
# Finding #4 — tape-only change must NOT trigger an endless tape_changed loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tape_only_change_emits_exactly_one_tape_event() -> None:
    """Tape width change with unchanged hr_printer_status must fire tape_changed once.

    Bug (Finding #4): _has_changed() compared only hr_printer_status and
    error_flags.  When tape width changed but status was unchanged,
    _has_changed() returned False, _last was NOT updated, so on the next
    probe the tape producer saw the same 'from_mm' again and emitted another
    tape_changed event — creating an infinite loop.

    Fix: _last is updated after EVERY probe, regardless of whether a change
    was detected.  This test probes [tape=12, tape=24, tape=24] and asserts
    that on_probe_result is called exactly twice after the first probe (probes
    2 and 3) and that the 'from_mm' for the second tape call is 24 (not 12).
    """
    bus = _make_bus()
    # Use a real callable tape_producer to capture on_probe_result calls
    tape_calls: list[tuple[PreflightStatus | None, PreflightStatus]] = []

    class _FakeTapeProducer:
        def on_probe_result(
            self,
            printer_id: str,
            old: PreflightStatus | None,
            new: PreflightStatus,
        ) -> None:
            tape_calls.append((old, new))

    probe_idx = 0
    probes = [
        _status(hr="idle", tape=12),
        _status(hr="idle", tape=24),
        _status(hr="idle", tape=24),
    ]

    async def _cycle_probes(*args: object, **kwargs: object) -> PreflightStatus:
        nonlocal probe_idx
        s = probes[probe_idx]
        probe_idx += 1
        return s

    with patch(
        "app.services.producers.status_probe_producer.query_preflight",
        side_effect=_cycle_probes,
    ):
        producer = StatusProbeProducer(
            bus=bus,
            printer_id="p1",
            host="198.51.100.1",
            interval_s=0.01,
            tape_change_producer=_FakeTapeProducer(),
        )
        await producer.start()
        while probe_idx < 3:
            await asyncio.sleep(0.01)
        await producer.stop()

    # on_probe_result called for probes 2 and 3 (probe 1 has no 'old' tape yet)
    assert len(tape_calls) == 3  # all 3 probes trigger on_probe_result
    # On probe 3: old=tape24 (NOT tape12), because _last was updated after probe 2
    _, tape3_new = tape_calls[2]
    assert tape3_new.loaded_tape_mm == 24
    # The 'from' for probe 3 must be 24 (the tape set after probe 2), not 12
    old_for_probe3, _ = tape_calls[2]
    assert old_for_probe3 is not None
    assert old_for_probe3.loaded_tape_mm == 24, (
        f"probe 3 from_mm must be 24 (not 12), got {old_for_probe3.loaded_tape_mm} "
        "— this indicates _last was not updated after probe 2"
    )


# ---------------------------------------------------------------------------
# Finding #5 — online→offline transition must always publish
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_online_to_offline_publishes_even_when_hr_status_unchanged() -> None:
    """Going offline must publish printer.status online=False even when
    hr_printer_status hasn't changed.

    Bug (Finding #5): when a probe succeeds with hr_printer_status='other'
    and then fails (offline sentinel also uses 'other'), _has_changed()
    returned False and the offline event was never published.

    Fix: online state is tracked separately; _last is updated after every
    probe regardless of whether the change check fired.
    """
    bus = _make_bus()
    tape_producer = MagicMock()

    probe_idx = 0
    # First probe: online, hr='other' (e.g. printer warming up)
    # Second call: exception → offline sentinel (also hr='other', no errors)
    probes_and_exceptions: list[PreflightStatus | Exception] = [
        _status(hr="other", tape=None),
        Exception("SNMP timeout"),
    ]

    async def _probe(*args: object, **kwargs: object) -> PreflightStatus:
        nonlocal probe_idx
        item = probes_and_exceptions[probe_idx]
        probe_idx += 1
        if isinstance(item, Exception):
            raise item
        return item

    with patch(
        "app.services.producers.status_probe_producer.query_preflight",
        side_effect=_probe,
    ):
        producer = StatusProbeProducer(
            bus=bus,
            printer_id="p1",
            host="198.51.100.1",
            interval_s=0.01,
            tape_change_producer=tape_producer,
        )
        await producer.start()
        while probe_idx < 2:
            await asyncio.sleep(0.01)
        await producer.stop()

    # Must have published at least 2 events: online=True then online=False
    assert bus.publish.call_count >= 2, (
        f"expected at least 2 publishes (online + offline), got {bus.publish.call_count}"
    )
    events = [call[0][1] for call in bus.publish.call_args_list]
    online_values = [e.data["online"] for e in events]
    assert True in online_values, "first event must have online=True"
    assert False in online_values, (
        "offline transition must be published even when hr_printer_status is unchanged"
    )


@pytest.mark.asyncio
async def test_offline_to_online_publishes_even_when_hr_status_unchanged() -> None:
    """Recovering from offline must publish printer.status online=True even when
    hr_printer_status stays 'other'.

    Same root cause as Finding #5: the online state change must be detected
    independently of hr_printer_status.
    """
    bus = _make_bus()
    tape_producer = MagicMock()

    probe_idx = 0
    probes_and_exceptions: list[PreflightStatus | Exception] = [
        Exception("SNMP timeout"),      # offline
        _status(hr="other", tape=None),  # online recovery, same hr
    ]

    async def _probe(*args: object, **kwargs: object) -> PreflightStatus:
        nonlocal probe_idx
        item = probes_and_exceptions[probe_idx]
        probe_idx += 1
        if isinstance(item, Exception):
            raise item
        return item

    with patch(
        "app.services.producers.status_probe_producer.query_preflight",
        side_effect=_probe,
    ):
        producer = StatusProbeProducer(
            bus=bus,
            printer_id="p1",
            host="198.51.100.1",
            interval_s=0.01,
            tape_change_producer=tape_producer,
        )
        await producer.start()
        while probe_idx < 2:
            await asyncio.sleep(0.01)
        await producer.stop()

    assert bus.publish.call_count >= 2, (
        f"expected at least 2 publishes (offline + online recovery), got {bus.publish.call_count}"
    )
    events = [call[0][1] for call in bus.publish.call_args_list]
    online_values = [e.data["online"] for e in events]
    assert False in online_values, "first event must have online=False"
    assert True in online_values, (
        "online recovery must be published even when hr_printer_status is unchanged"
    )
