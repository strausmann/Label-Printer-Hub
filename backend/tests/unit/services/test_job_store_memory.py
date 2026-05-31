"""MemoryJobStore Protocol-Conformance Tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.models.job import Job, JobState
from app.services.job_store import JobStore, MemoryJobStore


def _make_job(
    printer_id: UUID,
    finished_at: datetime | None = None,
) -> Job:
    return Job(
        printer_id=printer_id,
        template_key="t",
        payload={},
        state=JobState.QUEUED.value,
        finished_at=finished_at,
    )


@pytest.mark.asyncio
async def test_memory_store_save_and_get_round_trip() -> None:
    store = MemoryJobStore()
    job = _make_job(uuid4())
    await store.save_queued(job)
    fetched = await store.get(job.id)
    # MemoryJobStore-Semantik: gleiche Referenz. SQLiteJobStore gibt neue Instanz.
    assert fetched is job


@pytest.mark.asyncio
async def test_memory_store_implements_protocol() -> None:
    store = MemoryJobStore()
    assert isinstance(store, JobStore)


@pytest.mark.asyncio
async def test_memory_store_mark_interrupted_only_printing() -> None:
    store = MemoryJobStore()
    p1 = uuid4()
    queued = _make_job(p1)
    printing = _make_job(p1)
    await store.save_queued(queued)
    await store.save_queued(printing)
    await store.mark_printing(printing.id)  # Transition: QUEUED -> PRINTING

    affected = await store.mark_interrupted(p1)
    assert affected == 1

    still_queued = await store.get(queued.id)
    assert still_queued is not None
    assert still_queued.state == JobState.QUEUED.value

    interrupted = await store.get(printing.id)
    assert interrupted is not None
    assert interrupted.state == JobState.FAILED_RESTART.value
    assert interrupted.error == "printer_interrupted"
    assert interrupted.finished_at is not None


@pytest.mark.asyncio
async def test_memory_store_list_pending_returns_queued_and_paused_not_terminal() -> None:
    store = MemoryJobStore()
    p1, p2 = uuid4(), uuid4()
    q1 = _make_job(p1)
    pr1 = _make_job(p1)
    d1 = _make_job(p1)
    q2 = _make_job(p2)
    await store.save_queued(q1)
    await store.save_queued(pr1)
    await store.mark_printing(pr1.id)  # Transition: QUEUED -> PRINTING
    await store.save_queued(d1)
    # Transition: QUEUED -> PRINTING -> DONE (via mark_printing zuerst)
    await store.mark_done(d1.id)
    await store.save_queued(q2)

    p1_pending = await store.list_pending(p1)
    assert {j.id for j in p1_pending} == {q1.id, pr1.id}


@pytest.mark.asyncio
async def test_memory_store_evict_terminal_older_than() -> None:
    store = MemoryJobStore()
    old = _make_job(uuid4(), finished_at=datetime.now(UTC) - timedelta(days=40))
    young = _make_job(uuid4(), finished_at=datetime.now(UTC) - timedelta(days=5))
    queued = _make_job(uuid4())

    # old und young als DONE markieren (finished_at ist bereits gesetzt, mark_done überschreibt es)
    await store.save_queued(old)
    await store.save_queued(young)
    await store.save_queued(queued)
    # Direkt den State auf DONE setzen via mark_printing + mark_done
    # würde finished_at überschreiben.
    # Deshalb: _jobs direkt befüllen für alte Jobs mit vorgegebenen Timestamps.
    store._jobs[old.id].state = JobState.DONE.value
    store._jobs[young.id].state = JobState.DONE.value

    deleted = await store.evict_terminal_older_than(timedelta(days=30))
    assert deleted == 1
    assert await store.get(old.id) is None
    assert await store.get(young.id) is not None
    assert await store.get(queued.id) is not None
