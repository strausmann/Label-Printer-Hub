from datetime import UTC, datetime

import pytest
from app.services.job_lifecycle import (
    InvalidStateTransitionError,
    Job,
    JobState,
    JobStateMachine,
)


def test_job_queued_to_printing() -> None:
    job = Job(id="abc", printer_id="pt750w", state=JobState.QUEUED)
    JobStateMachine.transition(job, JobState.PRINTING)
    assert job.state == JobState.PRINTING
    assert job.started_at is not None


def test_job_printing_to_completed() -> None:
    job = Job(
        id="abc",
        printer_id="pt750w",
        state=JobState.PRINTING,
        started_at=datetime.now(),
    )
    JobStateMachine.transition(job, JobState.COMPLETED)
    assert job.state == JobState.COMPLETED
    assert job.finished_at is not None


def test_invalid_transition_completed_to_printing() -> None:
    job = Job(id="abc", printer_id="pt750w", state=JobState.COMPLETED)
    with pytest.raises(InvalidStateTransitionError, match="completed"):
        JobStateMachine.transition(job, JobState.PRINTING)


def test_cancel_only_from_queued_or_paused() -> None:
    """Brother Raster Spec: no mid-print cancel."""
    job = Job(id="abc", printer_id="pt750w", state=JobState.PRINTING)
    with pytest.raises(InvalidStateTransitionError, match="printing"):
        JobStateMachine.transition(job, JobState.CANCELLED)


def test_pause_from_queued_to_paused() -> None:
    job = Job(id="abc", printer_id="pt750w", state=JobState.QUEUED)
    JobStateMachine.transition(job, JobState.PAUSED)
    assert job.state == JobState.PAUSED


def test_resume_from_paused_to_queued() -> None:
    job = Job(id="abc", printer_id="pt750w", state=JobState.PAUSED)
    JobStateMachine.transition(job, JobState.QUEUED)
    assert job.state == JobState.QUEUED


def test_cancel_from_paused() -> None:
    job = Job(id="abc", printer_id="pt750w", state=JobState.PAUSED)
    JobStateMachine.transition(job, JobState.CANCELLED)
    assert job.state == JobState.CANCELLED


def test_pause_printing_not_allowed() -> None:
    """Brother Raster Spec: no mid-print pause."""
    job = Job(id="abc", printer_id="pt750w", state=JobState.PRINTING)
    with pytest.raises(InvalidStateTransitionError, match="printing"):
        JobStateMachine.transition(job, JobState.PAUSED)


def test_done_event_set_on_terminal_state() -> None:
    """Terminal transitions must signal the _done_event for wait_for_job()."""
    job = Job(id="abc", printer_id="pt750w", state=JobState.PRINTING)
    assert not job._done_event.is_set()
    JobStateMachine.transition(job, JobState.COMPLETED)
    assert job._done_event.is_set()


def test_done_event_not_set_on_pause() -> None:
    """Non-terminal transitions must NOT signal the _done_event."""
    job = Job(id="abc", printer_id="pt750w", state=JobState.QUEUED)
    JobStateMachine.transition(job, JobState.PAUSED)
    assert not job._done_event.is_set()


def test_done_event_set_on_failed() -> None:
    """Transition to FAILED must also set _done_event (parity with COMPLETED)."""
    job = Job(id="abc", printer_id="pt750w", state=JobState.PRINTING)
    JobStateMachine.transition(job, JobState.FAILED)
    assert job._done_event.is_set()
    assert job.finished_at is not None


def test_done_event_set_on_cancelled() -> None:
    """Transition to CANCELLED must also set _done_event (parity with COMPLETED)."""
    job = Job(id="abc", printer_id="pt750w", state=JobState.QUEUED)
    JobStateMachine.transition(job, JobState.CANCELLED)
    assert job._done_event.is_set()
    assert job.finished_at is not None


def test_timestamps_are_utc_aware() -> None:
    """submitted_at, started_at and finished_at must carry UTC tzinfo."""
    job = Job(id="abc", printer_id="pt750w", state=JobState.QUEUED)
    JobStateMachine.transition(job, JobState.PRINTING)
    JobStateMachine.transition(job, JobState.COMPLETED)
    assert job.submitted_at.tzinfo is UTC
    assert job.started_at is not None and job.started_at.tzinfo is UTC
    assert job.finished_at is not None and job.finished_at.tzinfo is UTC


def test_terminal_states_absorb_no_outgoing_transitions() -> None:
    """FAILED and CANCELLED behave like COMPLETED — no further transitions allowed."""
    for terminal in (JobState.FAILED, JobState.CANCELLED):
        job = Job(id="abc", printer_id="pt750w", state=terminal)
        for target in JobState:
            if target == terminal:
                continue
            with pytest.raises(InvalidStateTransitionError):
                JobStateMachine.transition(job, target)
