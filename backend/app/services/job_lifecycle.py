"""Job-lifecycle finite-state machine for the print queue.

Brother PT/QL printers have no multi-job queue (TCP/9100 is a single stream).
The hub serialises jobs per printer and tracks state explicitly. This module
owns the state model only; the worker that drives transitions lives in
`app.services.print_queue`.

State diagram:

    QUEUED ──> PRINTING ──> COMPLETED
       │           └──────> FAILED
       │
       ├──> PAUSED ──> QUEUED
       │       └─────> CANCELLED
       │
       ├──> CANCELLED
       └──> FAILED

Mid-print cancel and mid-print pause are NOT supported (Brother spec —
the printer ignores commands once the raster stream starts).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class JobState(StrEnum):
    QUEUED = "queued"
    PAUSED = "paused"
    PRINTING = "printing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Terminal states are absorbing — no transitions out.
# PRINTING is one-way to COMPLETED or FAILED (Brother spec: no mid-print stop).
_VALID_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.QUEUED: frozenset(
        {
            JobState.PRINTING,
            JobState.PAUSED,
            JobState.CANCELLED,
            JobState.FAILED,
        }
    ),
    JobState.PAUSED: frozenset({JobState.QUEUED, JobState.CANCELLED}),
    JobState.PRINTING: frozenset({JobState.COMPLETED, JobState.FAILED}),
    JobState.COMPLETED: frozenset(),
    JobState.FAILED: frozenset(),
    JobState.CANCELLED: frozenset(),
}

_TERMINAL_STATES: frozenset[JobState] = frozenset(
    {
        JobState.COMPLETED,
        JobState.FAILED,
        JobState.CANCELLED,
    }
)


class InvalidStateTransitionError(Exception):
    """Raised when JobStateMachine.transition() is called with an illegal target."""


@dataclass
class Job:
    """A single print job. In-memory MVP; persistence comes in Phase 5."""

    id: str
    printer_id: str
    state: JobState = JobState.QUEUED
    submitted_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    image_payload: bytes | None = None
    tape_mm: int | None = None
    options: dict[str, Any] = field(default_factory=dict)
    error_msg: str | None = None
    error_flags: int | None = None
    retry_count: int = 0
    # asyncio.Event is allowed on a dataclass field because asyncio fields on
    # Jobs are only awaited from within an event loop; constructing them at
    # import time is OK since asyncio.Event does not require a running loop.
    _done_event: asyncio.Event = field(default_factory=asyncio.Event)


class JobStateMachine:
    """Stateless gate-keeper for Job.state mutations.

    All state changes MUST flow through `transition()`. Direct assignment to
    `job.state` bypasses the validity check and the timestamp/event side
    effects — don't do that in production code.
    """

    @staticmethod
    def transition(job: Job, new_state: JobState) -> None:
        """Move `job` to `new_state` if the transition is valid.

        Raises:
            InvalidStateTransitionError: if `new_state` is not reachable from
                `job.state`. The exception message names both states so log
                entries are self-contained.
        """
        if new_state not in _VALID_TRANSITIONS[job.state]:
            raise InvalidStateTransitionError(
                f"Illegal transition {job.state.value} -> {new_state.value}"
            )

        job.state = new_state

        if new_state == JobState.PRINTING and job.started_at is None:
            job.started_at = datetime.now()

        if new_state in _TERMINAL_STATES:
            job.finished_at = datetime.now()
            job._done_event.set()
