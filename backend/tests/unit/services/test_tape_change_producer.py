# backend/tests/unit/services/test_tape_change_producer.py
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
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


# ---------------------------------------------------------------------------
# F6 — describe_tape delegation via PrinterModel Protocol (Finding F6)
# ---------------------------------------------------------------------------


def test_producer_delegates_tape_label_to_model_describe_tape() -> None:
    """TapeChangeProducer must delegate tape-class lookup to a PrinterModel
    rather than hard-coding PT-series registry calls (Finding F6).

    When a model is supplied, TapeChangeProducer must call
    ``model.describe_tape(width_mm)`` and use the returned label string
    instead of calling ``tape_registry.lookup_pt`` directly.
    """
    from app.services.producers.tape_change_producer import TapeDescription

    bus = MagicMock(spec=EventBus)
    bus.next_event_id.return_value = 1
    registry = MagicMock()

    model = MagicMock()
    model.describe_tape.return_value = TapeDescription(label="24mm TZe")

    producer = TapeChangeProducer(bus=bus, tape_registry=registry, model=model)
    producer.on_probe_result("printer-uuid", _status(12), _status(24))

    # describe_tape must be called with the new tape width
    model.describe_tape.assert_called_once_with(24)
    # lookup_pt must NOT be called — the model owns the lookup
    registry.lookup_pt.assert_not_called()

    event: BusEvent = bus.publish.call_args[0][1]
    assert event.data["tape_label"] == "24mm TZe"


def test_producer_falls_back_to_registry_when_no_model_provided() -> None:
    """Without a model, TapeChangeProducer falls back to tape_registry.lookup_pt
    (backward-compatible behaviour for callers not yet supplying a model).
    """
    bus = MagicMock(spec=EventBus)
    bus.next_event_id.return_value = 1
    registry = MagicMock()
    registry.lookup_pt.side_effect = Exception("not found")

    # model=None → old path
    producer = TapeChangeProducer(bus=bus, tape_registry=registry)
    producer.on_probe_result("printer-uuid", _status(12), _status(24))

    registry.lookup_pt.assert_called_once()
    event: BusEvent = bus.publish.call_args[0][1]
    # Fallback: width string when registry raises
    assert event.data["tape_label"] == "24mm"


def test_pt_model_describe_tape_returns_laminated_tze_label() -> None:
    """PTP750WDriver.describe_tape(width_mm) must return a TapeDescription
    with a non-empty label for a known PT-Series laminated TZe tape.
    """
    from app.printer_models.pt import PTP750WDriver
    from app.services.producers.tape_change_producer import TapeDescription

    backend = MagicMock()
    backend.host = "192.0.2.100"
    driver = PTP750WDriver(backend=backend)

    desc = driver.describe_tape(12)

    assert isinstance(desc, TapeDescription)
    assert desc.label  # non-empty string
    assert "12" in desc.label  # the width should appear in the label


def test_pt_model_describe_tape_unknown_width_returns_fallback() -> None:
    """PTP750WDriver.describe_tape() must return a fallback label (e.g. '99mm')
    for an unknown tape width rather than raising.
    """
    from app.printer_models.pt import PTP750WDriver
    from app.services.producers.tape_change_producer import TapeDescription

    backend = MagicMock()
    backend.host = "192.0.2.100"
    driver = PTP750WDriver(backend=backend)

    desc = driver.describe_tape(99)

    assert isinstance(desc, TapeDescription)
    assert "99" in desc.label


@pytest.mark.parametrize("width_mm", [4, 6, 9, 12, 18, 24])
def test_pt_model_describe_tape_all_standard_widths(width_mm: int) -> None:
    """PTP750WDriver.describe_tape() must succeed for all standard TZe widths."""
    from app.printer_models.pt import PTP750WDriver

    backend = MagicMock()
    backend.host = "192.0.2.100"
    driver = PTP750WDriver(backend=backend)

    desc = driver.describe_tape(width_mm)
    assert str(width_mm) in desc.label
