"""CleanupTask runs evict_terminal_older_than periodically."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from app.services.cleanup_task import CleanupTask


@pytest.mark.asyncio
async def test_cleanup_validates_retention_days() -> None:
    store = AsyncMock()
    with pytest.raises(ValueError, match="retention_days must be >= 1"):
        CleanupTask(store=store, retention_days=0)


@pytest.mark.asyncio
async def test_cleanup_initial_run_on_start() -> None:
    store = AsyncMock()
    store.evict_terminal_older_than.return_value = 3
    task = CleanupTask(store=store, retention_days=30, interval=timedelta(seconds=99))
    await task.start()
    # stop() wartet intern auf den laufenden Task — nach stop() ist der
    # erste evict_terminal_older_than-Call garantiert erfolgt.
    await task.stop(timeout_s=1.0)

    store.evict_terminal_older_than.assert_awaited()
    args, _ = store.evict_terminal_older_than.call_args
    assert args[0] == timedelta(days=30)


@pytest.mark.asyncio
async def test_cleanup_fail_soft_on_exception() -> None:
    store = AsyncMock()
    store.evict_terminal_older_than.side_effect = RuntimeError("boom")
    task = CleanupTask(store=store, retention_days=30, interval=timedelta(seconds=99))
    await task.start()
    await task.stop(timeout_s=1.0)
    # No exception propagated; loop survives


@pytest.mark.asyncio
async def test_cleanup_purges_expired_sessions() -> None:
    store = AsyncMock()
    store.evict_terminal_older_than.return_value = 0
    purge = AsyncMock(return_value=2)
    task = CleanupTask(
        store=store, retention_days=30, interval=timedelta(seconds=99), session_purge=purge
    )
    await task.start()
    await task.stop(timeout_s=1.0)
    purge.assert_awaited()


@pytest.mark.asyncio
async def test_cleanup_session_purge_failure_does_not_stop_job_eviction() -> None:
    store = AsyncMock()
    store.evict_terminal_older_than.return_value = 0
    purge = AsyncMock(side_effect=RuntimeError("boom"))
    task = CleanupTask(
        store=store, retention_days=30, interval=timedelta(seconds=99), session_purge=purge
    )
    await task.start()
    await task.stop(timeout_s=1.0)
    store.evict_terminal_older_than.assert_awaited()
    purge.assert_awaited()


@pytest.mark.asyncio
async def test_cleanup_drops_finished_jobs_from_the_queue_each_cycle() -> None:
    """Each cycle also evicts finished jobs from the queue's memory (263-70)."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from app.services.job_lifecycle import Job, JobState
    from app.services.print_queue import PrintQueue

    queue = PrintQueue([])
    old = Job(id=str(uuid4()), printer_id=uuid4(), state=JobState.COMPLETED)
    old.finished_at = datetime(2020, 1, 1, tzinfo=UTC)
    waiting = Job(id=str(uuid4()), printer_id=old.printer_id)
    queue._jobs = {old.id: old, waiting.id: waiting}
    store = AsyncMock()
    store.evict_terminal_older_than.return_value = 0
    task = CleanupTask(store=store, retention_days=30, interval=timedelta(seconds=99), queue=queue)
    await task.start()
    await task.stop(timeout_s=1.0)
    assert set(queue._jobs) == {waiting.id}
