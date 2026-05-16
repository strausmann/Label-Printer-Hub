"""Publishes job.state_changed events to the EventBus on job state transitions.

The PrintQueue accepts an ``on_state_change`` callback in its constructor.
This producer's ``handle_transition`` method is passed as that callback so it
runs inside the worker loop without any async overhead — ``EventBus.publish``
is synchronous.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.services.event_bus import BusEvent, EventBus
from app.services.job_lifecycle import Job, JobState

_log = logging.getLogger(__name__)


class PrintQueueProducer:
    """Converts job state transitions into EventBus events."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    def handle_transition(
        self,
        job: Job,
        from_state: JobState,
        to_state: JobState,
        queue_depth: int = 0,
    ) -> None:
        """Publish a ``job.state_changed`` event.

        ``queue_depth`` is the number of non-terminal jobs remaining in the
        printer's queue at the moment of the transition.  Callers (PrintQueue
        worker, submit, pause_job, etc.) must supply the actual depth; the
        default of 0 is kept only for backward-compatibility with tests that
        don't exercise the depth field.

        Called synchronously from the PrintQueue worker after each
        ``JobStateMachine.transition`` call. Must not raise — any exception
        would propagate into the worker and risk marking the job FAILED
        incorrectly. Errors are logged and swallowed.
        """
        channel = f"printer:{job.printer_id}:queue"
        try:
            event = BusEvent(
                channel=channel,
                event_id=self._bus.next_event_id(channel),
                event_type="job.state_changed",
                timestamp=datetime.now(UTC),
                data={
                    "job_id": str(job.id),
                    "from_state": from_state.value,
                    "to_state": to_state.value,
                    "queue_depth": queue_depth,
                    "error_code": getattr(job, "error_code", None),
                },
            )
            self._bus.publish(channel, event)
        except Exception:
            _log.exception("PrintQueueProducer.handle_transition failed for job=%s", job.id)
