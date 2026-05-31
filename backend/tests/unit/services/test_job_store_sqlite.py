"""SQLiteJobStore Protocol-Conformance Tests gegen echte SQLite-Session."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.models.job import Job, JobState
from app.services.job_store import JobStore
from app.services.job_store_sqlite import SQLiteJobStore


@pytest.mark.asyncio
async def test_sqlite_store_implements_protocol(async_session_factory) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteJobStore(async_session_factory)
    assert isinstance(store, JobStore)


@pytest.mark.asyncio
async def test_sqlite_store_save_and_get_round_trip(async_session_factory) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteJobStore(async_session_factory)
    printer_id = uuid4()
    job = Job(printer_id=printer_id, template_key="t", payload={"foo": "bar"})
    await store.save_queued(job)
    fetched = await store.get(job.id)
    assert fetched is not None
    assert fetched.id == job.id
    assert fetched.payload == {"foo": "bar"}
    assert fetched.state == JobState.QUEUED.value


@pytest.mark.asyncio
async def test_sqlite_store_mark_transitions(async_session_factory) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteJobStore(async_session_factory)
    job = Job(printer_id=uuid4(), template_key="t", payload={})
    await store.save_queued(job)

    await store.mark_printing(job.id)
    fetched_printing = await store.get(job.id)
    assert fetched_printing is not None
    assert fetched_printing.state == JobState.PRINTING.value
    assert fetched_printing.started_at is not None

    await store.mark_done(job.id)
    fetched_done = await store.get(job.id)
    assert fetched_done is not None
    assert fetched_done.state == JobState.DONE.value
    assert fetched_done.finished_at is not None


@pytest.mark.asyncio
async def test_sqlite_store_mark_failed(async_session_factory) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteJobStore(async_session_factory)
    job = Job(printer_id=uuid4(), template_key="t", payload={})
    await store.save_queued(job)
    await store.mark_printing(job.id)

    await store.mark_failed(job.id, "tape_empty")
    fetched = await store.get(job.id)
    assert fetched is not None
    assert fetched.state == JobState.FAILED.value
    assert fetched.error == "tape_empty"
    assert fetched.finished_at is not None


@pytest.mark.asyncio
async def test_sqlite_store_mark_interrupted_only_printing(async_session_factory) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteJobStore(async_session_factory)
    p1 = uuid4()
    queued = Job(printer_id=p1, template_key="t", payload={})
    printing = Job(printer_id=p1, template_key="t", payload={})
    await store.save_queued(queued)
    await store.save_queued(printing)
    await store.mark_printing(printing.id)

    affected = await store.mark_interrupted(p1)
    assert affected == 1

    q = await store.get(queued.id)
    p = await store.get(printing.id)
    assert q is not None
    assert p is not None
    assert q.state == JobState.QUEUED.value
    assert p.state == JobState.FAILED_RESTART.value
    assert p.error == "printer_interrupted"


@pytest.mark.asyncio
async def test_sqlite_store_list_pending_fifo(async_session_factory) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteJobStore(async_session_factory)
    p1 = uuid4()
    j1 = Job(printer_id=p1, template_key="t", payload={"order": 1})
    await store.save_queued(j1)
    j2 = Job(printer_id=p1, template_key="t", payload={"order": 2})
    await store.save_queued(j2)
    # Note: SQLModel sets created_at via default_factory at construction;
    # tests rely on save order matching id assignment via uuid.

    pending = await store.list_pending(p1)
    assert [j.id for j in pending] == [j1.id, j2.id]


@pytest.mark.asyncio
async def test_sqlite_store_evict_terminal_older_than(async_session_factory) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteJobStore(async_session_factory)
    p1 = uuid4()
    old = Job(printer_id=p1, template_key="t", payload={})
    young = Job(printer_id=p1, template_key="t", payload={})
    queued = Job(printer_id=p1, template_key="t", payload={})
    await store.save_queued(old)
    await store.mark_printing(old.id)
    await store.mark_done(old.id)
    # backdate finished_at
    async with async_session_factory() as s:
        fetched = await s.get(Job, old.id)
        assert fetched is not None
        fetched.finished_at = datetime.now(UTC) - timedelta(days=40)
        await s.commit()

    await store.save_queued(young)
    await store.mark_printing(young.id)
    await store.mark_done(young.id)
    await store.save_queued(queued)

    deleted = await store.evict_terminal_older_than(timedelta(days=30))
    assert deleted == 1
    assert await store.get(old.id) is None
    assert await store.get(young.id) is not None
    assert await store.get(queued.id) is not None
