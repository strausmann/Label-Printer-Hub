# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""``evict_finished`` keeps the queue's in-memory job table bounded (263-70).

The bound is checked on counts and on what the queue still tracks, never on timing: every
``finished_at`` is set by the test, and ``now`` is passed in.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.services.job_lifecycle import Job, JobState
from app.services.job_retention import evict_finished
from app.services.print_queue import PrintQueue, TapeRun

_PRINTER = UUID("cccccccc-0000-0000-0000-000000000001")
_NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
_HOUR = 3600


def _queue() -> PrintQueue:
    return PrintQueue([])


def _track(
    queue: PrintQueue, state: JobState, *, ended_s_ago: float | None = None, payload: bool = True
) -> Job:
    job = Job(
        id=str(uuid4()),
        printer_id=_PRINTER,
        state=state,
        image_payload=b"png" * 1000 if payload else None,
    )
    if ended_s_ago is not None:
        job.finished_at = _NOW - timedelta(seconds=ended_s_ago)
    queue._jobs[job.id] = job
    return job


def test_finished_jobs_are_evicted() -> None:
    queue = _queue()
    old = [
        _track(queue, state, ended_s_ago=2 * _HOUR)
        for state in (JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED)
    ]
    assert evict_finished(queue, now=_NOW, keep_s=_HOUR) == 3
    assert queue._jobs == {}
    for job in old:
        assert queue.has_job(job.id) is False


def test_job_finished_less_than_keep_s_ago_is_kept() -> None:
    queue = _queue()
    fresh = _track(queue, JobState.COMPLETED, ended_s_ago=_HOUR - 1)
    assert evict_finished(queue, now=_NOW, keep_s=_HOUR) == 0
    assert queue.has_job(fresh.id)


@pytest.mark.parametrize("state", [JobState.QUEUED, JobState.PAUSED, JobState.PRINTING])
def test_running_and_queued_jobs_are_kept(state: JobState) -> None:
    queue = _queue()
    # An old submit time and an old (stale) finished_at must not matter: only the state does.
    job = _track(queue, state, ended_s_ago=10 * _HOUR)
    job.submitted_at = _NOW - timedelta(days=3)
    assert evict_finished(queue, now=_NOW, keep_s=_HOUR) == 0
    assert queue._jobs == {job.id: job}
    assert job.image_payload is not None


def test_memory_stays_bounded_over_many_jobs() -> None:
    queue = _queue()
    keep = [_track(queue, JobState.QUEUED) for _ in range(5)]
    for _ in range(500):
        _track(queue, JobState.COMPLETED, ended_s_ago=2 * _HOUR)
    assert len(queue._jobs) == 505
    assert evict_finished(queue, now=_NOW, keep_s=_HOUR) == 500
    assert set(queue._jobs) == {job.id for job in keep}  # and their images with them


def test_forget_job_only_drops_terminal_jobs() -> None:
    queue = _queue()
    done = _track(queue, JobState.COMPLETED, ended_s_ago=0)
    waiting = _track(queue, JobState.QUEUED)
    assert queue.forget_job(UUID(waiting.id)) is False
    assert queue.forget_job(uuid4()) is False
    assert queue.forget_job(UUID(done.id)) is True
    assert queue.forget_job(UUID(done.id)) is False  # gone
    assert queue.has_job(waiting.id)


def test_labels_of_a_held_run_are_not_forgotten() -> None:
    """A stopped run reprints from its labels: they stay while the run does."""
    queue = _queue()
    failed = _track(queue, JobState.FAILED, ended_s_ago=2 * _HOUR)
    run_id = uuid4()
    queue._runs[run_id] = TapeRun(
        run_id=run_id,
        printer_id=_PRINTER,
        tape_mm=24,
        options={},
        job_ids=[failed.id],
        payloads={},
        sub_jobs=[(0, 1)],
        state="stopped",
    )
    assert evict_finished(queue, now=_NOW, keep_s=_HOUR) == 0
    del queue._runs[run_id]
    assert evict_finished(queue, now=_NOW, keep_s=_HOUR) == 1


async def test_job_whose_cancel_was_not_persisted_is_never_evicted() -> None:
    """``cancel()`` keeps the job cancelled in memory when the store write fails; its row may
    still be ``queued``. The known id is what keeps a recovery from printing it, so the job
    must stay in memory however old it is."""
    from unittest.mock import AsyncMock

    from app.services.job_store import MemoryJobStore

    store = MemoryJobStore()
    store.mark_cancelled = AsyncMock(side_effect=RuntimeError("database is locked"))  # type: ignore[method-assign]
    queue = PrintQueue([], store=store)
    job = _track(queue, JobState.QUEUED)
    with pytest.raises(RuntimeError):
        await queue.cancel(job.id)
    assert job.state == JobState.CANCELLED
    job.finished_at = _NOW - timedelta(days=2)
    assert evict_finished(queue, now=_NOW, keep_s=_HOUR) == 0
    assert queue.forget_job(UUID(job.id)) is False
    assert queue.has_job(job.id)
