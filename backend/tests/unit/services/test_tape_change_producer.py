# backend/tests/unit/services/test_tape_change_producer.py
from __future__ import annotations

from unittest.mock import MagicMock

from app.printer_backends.snmp_helper import PreflightStatus
from app.services.event_bus import BusEvent, EventBus
from app.services.producers.tape_change_producer import TapeChangeProducer


def _status(tape_mm: int | None = 12) -> PreflightStatus:
    return PreflightStatus(
        hr_printer_status="idle",
        loaded_tape_mm=tape_mm,
        error_flags=[],
    )


def test_no_publish_when_tape_unchanged() -> None:
    bus = MagicMock(spec=EventBus)
    bus.next_event_id.return_value = 1
    registry = MagicMock()
    producer = TapeChangeProducer(bus=bus, tape_registry=registry)
    producer.on_probe_result("printer-uuid", _status(12), _status(12))
    bus.publish.assert_not_called()


def test_publishes_on_tape_change() -> None:
    bus = MagicMock(spec=EventBus)
    bus.next_event_id.return_value = 1
    registry = MagicMock()
    registry.lookup_pt.side_effect = Exception("not found")
    producer = TapeChangeProducer(bus=bus, tape_registry=registry)
    producer.on_probe_result("printer-uuid", _status(12), _status(24))
    bus.publish.assert_called_once()
    event: BusEvent = bus.publish.call_args[0][1]
    assert event.event_type == "printer.tape_changed"
    assert event.data["from_mm"] == 12
    assert event.data["to_mm"] == 24


def test_from_mm_is_none_when_old_is_none() -> None:
    bus = MagicMock(spec=EventBus)
    bus.next_event_id.return_value = 1
    registry = MagicMock()
    registry.lookup_pt.side_effect = Exception("not found")
    producer = TapeChangeProducer(bus=bus, tape_registry=registry)
    producer.on_probe_result("printer-uuid", None, _status(24))
    event: BusEvent = bus.publish.call_args[0][1]
    assert event.data["from_mm"] is None
    assert event.data["to_mm"] == 24


def test_tape_removed_publishes_to_mm_none() -> None:
    bus = MagicMock(spec=EventBus)
    bus.next_event_id.return_value = 1
    registry = MagicMock()
    producer = TapeChangeProducer(bus=bus, tape_registry=registry)
    producer.on_probe_result("printer-uuid", _status(12), _status(None))
    event: BusEvent = bus.publish.call_args[0][1]
    assert event.data["to_mm"] is None


def test_channel_is_tape_channel() -> None:
    bus = MagicMock(spec=EventBus)
    bus.next_event_id.return_value = 1
    registry = MagicMock()
    registry.lookup_pt.side_effect = Exception("not found")
    producer = TapeChangeProducer(bus=bus, tape_registry=registry)
    producer.on_probe_result("my-printer", _status(12), _status(24))
    channel = bus.publish.call_args[0][0]
    assert channel == "printer:my-printer:tape"
