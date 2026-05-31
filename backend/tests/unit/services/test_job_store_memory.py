"""MemoryJobStore Protocol-Conformance Tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.models.job import Job, JobState
from app.services.job_store import JobStore, MemoryJobStore


def _make_job(printer_id, state=JobState.QUEUED, finished_at=None):
    return Job(
        printer_id=printer_id,
        template_key="t",
        payload={},
        state=state.value,
        finished_at=finished_at,
    )


@pytest.mark.asyncio
async def test_memory_store_save_and_get_round_trip():
    store = MemoryJobStore()
    job = _make_job(uuid4())
    await store.save_queued(job)
    fetched = await store.get(job.id)
    assert fetched is job


@pytest.mark.asyncio
async def test_memory_store_implements_protocol():
    store = MemoryJobStore()
    assert isinstance(store, JobStore)


@pytest.mark.asyncio
async def test_memory_store_mark_interrupted_only_printing():
    store = MemoryJobStore()
    p1 = uuid4()
    queued = _make_job(p1, state=JobState.QUEUED)
    printing = _make_job(p1, state=JobState.PRINTING)
    await store.save_queued(queued)
    await store.save_queued(printing)

    affected = await store.mark_interrupted(p1)
    assert affected == 1
    assert (await store.get(queued.id)).state == JobState.QUEUED.value
    interrupted = await store.get(printing.id)
    assert interrupted.state == JobState.FAILED_RESTART.value
    assert interrupted.error == "printer_interrupted"
    assert interrupted.finished_at is not None


@pytest.mark.asyncio
async def test_memory_store_list_pending_returns_queued_and_paused_not_terminal():
    store = MemoryJobStore()
    p1, p2 = uuid4(), uuid4()
    q1 = _make_job(p1, state=JobState.QUEUED)
    pr1 = _make_job(p1, state=JobState.PRINTING)
    d1 = _make_job(p1, state=JobState.DONE)
    q2 = _make_job(p2, state=JobState.QUEUED)
    for j in (q1, pr1, d1, q2):
        await store.save_queued(j)

    p1_pending = await store.list_pending(p1)
    assert {j.id for j in p1_pending} == {q1.id, pr1.id}


@pytest.mark.asyncio
async def test_memory_store_evict_terminal_older_than():
    store = MemoryJobStore()
    old = _make_job(uuid4(), state=JobState.DONE, finished_at=datetime.now(UTC) - timedelta(days=40))
    young = _make_job(uuid4(), state=JobState.DONE, finished_at=datetime.now(UTC) - timedelta(days=5))
    queued = _make_job(uuid4(), state=JobState.QUEUED)
    for j in (old, young, queued):
        await store.save_queued(j)

    deleted = await store.evict_terminal_older_than(timedelta(days=30))
    assert deleted == 1
    assert await store.get(old.id) is None
    assert await store.get(young.id) is not None
    assert await store.get(queued.id) is not None
