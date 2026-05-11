from datetime import datetime

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
