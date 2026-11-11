# backend/tests/unit/services/test_print_queue_producer.py
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import UUID

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


# ---------------------------------------------------------------------------
# Finding #6 — queue_depth must reflect actual queue size at emit time
# ---------------------------------------------------------------------------


def test_handle_transition_queue_depth_reflects_actual_depth() -> None:
    """queue_depth in the event data must be the actual queue depth passed by
    the caller, NOT the hard-coded 0 from the original buggy implementation.

    Bug (Finding #6): PrintQueueProducer.handle_transition always emitted
    queue_depth=0 with the comment 'enriched by SSE endpoint before emit'
    (which the SSE endpoint never did). The fix passes the real depth from
    the worker at transition time.
    """
    bus = MagicMock(spec=EventBus)
    bus.next_event_id.return_value = 1
    producer = PrintQueueProducer(bus=bus)
    job = _make_job()

    producer.handle_transition(job, JobState.QUEUED, JobState.PRINTING, queue_depth=3)

    event: BusEvent = bus.publish.call_args[0][1]
    assert event.data["queue_depth"] == 3, (
        f"expected queue_depth=3, got {event.data['queue_depth']}"
    )


def test_handle_transition_queue_depth_zero_when_empty() -> None:
    """queue_depth=0 is correct when the queue is empty."""
    bus = MagicMock(spec=EventBus)
    bus.next_event_id.return_value = 1
    producer = PrintQueueProducer(bus=bus)
    job = _make_job()

    producer.handle_transition(job, JobState.PRINTING, JobState.COMPLETED, queue_depth=0)

    event: BusEvent = bus.publish.call_args[0][1]
    assert event.data["queue_depth"] == 0


def test_page_job_event_carries_kind_at_printer_and_summary() -> None:
    bus = MagicMock(spec=EventBus)
    bus.next_event_id.return_value = 1
    producer = PrintQueueProducer(bus=bus)
    job = Job(id="j", printer_id="p", kind="sheet_page", summary={"sheet": "A123", "cells": 4})
    job.at_printer = "stopped"
    job.at_printer_reasons = ["media-jam"]

    producer.handle_transition(job, JobState.PRINTING, JobState.PRINTING)

    data = bus.publish.call_args[0][1].data
    assert data["kind"] == "sheet_page"
    assert data["at_printer"] == "stopped"
    assert data["at_printer_reasons"] == ["media-jam"]
    assert data["summary"] == {"sheet": "A123", "cells": 4}


def test_tape_job_event_has_no_page_fields() -> None:
    bus = MagicMock(spec=EventBus)
    bus.next_event_id.return_value = 1
    producer = PrintQueueProducer(bus=bus)

    producer.handle_transition(_make_job(), JobState.QUEUED, JobState.PRINTING)

    data = bus.publish.call_args[0][1].data
    assert "kind" not in data and "at_printer" not in data and "summary" not in data


def test_handle_run_change_publishes_ids_and_state_only() -> None:
    bus = MagicMock(spec=EventBus)
    bus.next_event_id.return_value = 7
    run_id = UUID("00000000-0000-4000-8000-000000000001")
    printer_id = UUID("00000000-0000-4000-8000-000000000002")

    PrintQueueProducer(bus=bus).handle_run_change(run_id, printer_id, "awaiting_confirmation")

    channel = f"printer:{printer_id}:queue"
    bus.publish.assert_called_once()
    assert bus.publish.call_args.args[0] == channel
    event: BusEvent = bus.publish.call_args.args[1]
    assert (event.event_type, event.event_id, event.channel) == ("run.state_changed", 7, channel)
    assert event.data == {
        "run_id": str(run_id),
        "printer_id": str(printer_id),
        "state": "awaiting_confirmation",
    }


def test_handle_run_change_swallows_a_bus_error() -> None:
    bus = MagicMock(spec=EventBus)
    bus.next_event_id.side_effect = RuntimeError("bus down")
    PrintQueueProducer(bus=bus).handle_run_change(UUID(int=1), UUID(int=2), "stopped")
