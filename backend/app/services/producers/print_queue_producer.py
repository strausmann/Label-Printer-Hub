# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Publishes job.state_changed events to the EventBus on job state transitions.

The PrintQueue accepts an ``on_state_change`` callback in its constructor.
This producer's ``handle_transition`` method is passed as that callback so it
runs inside the worker loop without any async overhead — ``EventBus.publish``
is synchronous.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

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
            data: dict[str, object] = {
                "job_id": str(job.id),
                "from_state": from_state.value,
                "to_state": to_state.value,
                "queue_depth": queue_depth,
                "error_code": getattr(job, "error_code", None),
            }
            if job.kind is not None:
                # Page jobs (spec 16). from == to: the job moved at the printer
                # (``at_printer`` waiting/printing/stopped) without a queue transition.
                data["kind"] = job.kind
                data["at_printer"] = job.at_printer
                data["at_printer_reasons"] = list(job.at_printer_reasons)
                data["summary"] = job.summary
            event = BusEvent(
                channel=channel,
                event_id=self._bus.next_event_id(channel),
                event_type="job.state_changed",
                timestamp=datetime.now(UTC),
                data=data,
            )
            self._bus.publish(channel, event)
        except Exception:
            _log.exception("PrintQueueProducer.handle_transition failed for job=%s", job.id)

    def handle_run_change(self, run_id: UUID, printer_id: UUID, state: str) -> None:
        """Publish a ``run.state_changed`` event: a tape run entered or left the held list (#277).

        ``state`` is the run's state (``awaiting_confirmation``, ``stopped``, ``printing``) or
        ``discarded`` / ``finished`` when the run is gone. The data carries ids and the state
        only, no label content. Must not raise.
        """
        channel = f"printer:{printer_id}:queue"
        try:
            event = BusEvent(
                channel=channel,
                event_id=self._bus.next_event_id(channel),
                event_type="run.state_changed",
                timestamp=datetime.now(UTC),
                data={"run_id": str(run_id), "printer_id": str(printer_id), "state": state},
            )
            self._bus.publish(channel, event)
        except Exception:
            _log.exception("PrintQueueProducer.handle_run_change failed for run=%s", run_id)
