# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The two store writes of a deferred job (#281): ``set_queued_payload`` and
``mark_queued_failed_restart``, in the memory and the SQLite store.

Both must change a row only while it is ``queued``: a deferred job the user cancelled
during its preflight is never completed, and an ended job never becomes ``failed_restart``.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from app.models.job import Job, JobState
from app.services.job_store import JobStore, MemoryJobStore
from app.services.job_store_sqlite import SQLiteJobStore

pytestmark = pytest.mark.asyncio

QUEUED_PAYLOAD = {"deferred": True, "content_type": "qr_two_lines"}
COMPLETED = {**QUEUED_PAYLOAD, "rendered_tape_mm": 12, "tape_mm": 12}


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest, async_session_factory: Any) -> JobStore:
    if request.param == "memory":
        return MemoryJobStore()
    return SQLiteJobStore(async_session_factory)


async def _saved(store: JobStore) -> Job:
    job = Job(printer_id=uuid4(), template_key=None, payload=dict(QUEUED_PAYLOAD))
    await store.save_queued(job)
    return job


async def test_set_queued_payload_writes_a_queued_row(store: JobStore) -> None:
    job = await _saved(store)
    assert await store.set_queued_payload(job.id, COMPLETED) is True
    row = await store.get(job.id)
    assert row is not None
    assert row.payload == COMPLETED
    assert row.state == JobState.QUEUED.value


async def test_set_queued_payload_leaves_a_cancelled_row(store: JobStore) -> None:
    job = await _saved(store)
    await store.mark_cancelled(job.id)
    assert await store.set_queued_payload(job.id, COMPLETED) is False
    row = await store.get(job.id)
    assert row is not None
    assert row.state == JobState.CANCELLED.value
    assert "rendered_tape_mm" not in row.payload


async def test_set_queued_payload_of_an_unknown_job_is_false(store: JobStore) -> None:
    assert await store.set_queued_payload(uuid4(), COMPLETED) is False


async def test_mark_queued_failed_restart_ends_a_queued_row(store: JobStore) -> None:
    job = await _saved(store)
    await store.mark_queued_failed_restart(job.id, "deferred_interrupted")
    row = await store.get(job.id)
    assert row is not None
    assert (row.state, row.error) == (JobState.FAILED_RESTART.value, "deferred_interrupted")
    assert row.finished_at is not None


async def test_mark_queued_failed_restart_leaves_other_states(store: JobStore) -> None:
    cancelled = await _saved(store)
    await store.mark_cancelled(cancelled.id)
    printing = await _saved(store)
    await store.mark_printing(printing.id)
    for job, state in ((cancelled, JobState.CANCELLED), (printing, JobState.PRINTING)):
        await store.mark_queued_failed_restart(job.id, "deferred_interrupted")
        row = await store.get(job.id)
        assert row is not None
        assert row.state == state.value
    await store.mark_queued_failed_restart(uuid4(), "deferred_interrupted")  # unknown: no error


async def test_mark_queued_many_failed_restart_ends_only_queued_rows(store: JobStore) -> None:
    queued = [await _saved(store) for _ in range(3)]
    cancelled = await _saved(store)
    await store.mark_cancelled(cancelled.id)
    ids = [j.id for j in queued] + [cancelled.id, uuid4()]
    changed = await store.mark_queued_many_failed_restart(ids, "deferred_interrupted")
    assert sorted(changed) == sorted(j.id for j in queued)
    for job in queued:
        row = await store.get(job.id)
        assert row is not None
        assert (row.state, row.error) == (JobState.FAILED_RESTART.value, "deferred_interrupted")
    row = await store.get(cancelled.id)
    assert row is not None
    assert row.state == JobState.CANCELLED.value
    assert await store.mark_queued_many_failed_restart([], "deferred_interrupted") == []
