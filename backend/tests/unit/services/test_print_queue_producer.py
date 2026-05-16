# backend/tests/unit/services/test_print_queue_producer.py
from __future__ import annotations

from unittest.mock import MagicMock

from app.services.event_bus import BusEvent, EventBus
from app.services.job_lifecycle import Job, JobState
from app.services.producers.print_queue_producer import PrintQueueProducer


def _make_job(printer_id: str = "printer-uuid-1") -> Job:
    return Job(
        id="job-uuid-1",
        printer_id=printer_id,
        tape_mm=12,
    )


def test_handle_transition_publishes_to_correct_channel() -> None:
    bus = MagicMock(spec=EventBus)
    bus.next_event_id.return_value = 1
    producer = PrintQueueProducer(bus=bus)
    job = _make_job()

    producer.handle_transition(job, JobState.QUEUED, JobState.PRINTING)

    bus.publish.assert_called_once()
    call_args = bus.publish.call_args
    channel = call_args[0][0]
    event: BusEvent = call_args[0][1]
    assert channel == f"printer:{job.printer_id}:queue"
    assert event.channel == channel
    assert event.event_type == "job.state_changed"


def test_handle_transition_data_has_from_and_to_state() -> None:
    bus = MagicMock(spec=EventBus)
    bus.next_event_id.return_value = 5
    producer = PrintQueueProducer(bus=bus)
    job = _make_job()

    producer.handle_transition(job, JobState.QUEUED, JobState.PRINTING)

    event: BusEvent = bus.publish.call_args[0][1]
    assert event.data["from_state"] == "queued"
    assert event.data["to_state"] == "printing"
    assert event.data["job_id"] == "job-uuid-1"
    assert event.data["queue_depth"] == 0
    assert event.data["error_code"] is None


def test_handle_transition_failed_state_includes_error_code() -> None:
    bus = MagicMock(spec=EventBus)
    bus.next_event_id.return_value = 2
    producer = PrintQueueProducer(bus=bus)
    job = _make_job()
    job.error_code = "tape_mismatch"

    producer.handle_transition(job, JobState.PRINTING, JobState.FAILED)

    event: BusEvent = bus.publish.call_args[0][1]
    assert event.data["error_code"] == "tape_mismatch"


def test_handle_transition_uses_next_event_id() -> None:
    bus = MagicMock(spec=EventBus)
    bus.next_event_id.return_value = 42
    producer = PrintQueueProducer(bus=bus)
    job = _make_job()

    producer.handle_transition(job, JobState.QUEUED, JobState.PRINTING)

    channel = f"printer:{job.printer_id}:queue"
    bus.next_event_id.assert_called_once_with(channel)
    event: BusEvent = bus.publish.call_args[0][1]
    assert event.event_id == 42
