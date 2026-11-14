# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

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
async def test_finished_jobs_leave_memory_on_the_short_tick_not_the_daily_cycle() -> None:
    """Eviction has its own tick (263-70): a job that finishes after the daily cycle ran is
    still dropped, and stop() ends both loops."""
    import asyncio
    from datetime import UTC, datetime
    from uuid import uuid4

    from app.services.job_lifecycle import Job, JobState
    from app.services.print_queue import PrintQueue

    queue = PrintQueue([])
    waiting = Job(id=str(uuid4()), printer_id=uuid4())
    queue._jobs = {waiting.id: waiting}
    store = AsyncMock()
    store.evict_terminal_older_than.return_value = 0
    task = CleanupTask(
        store=store,
        retention_days=30,
        interval=timedelta(seconds=99),  # the daily cycle runs once, at start
        queue=queue,
        evict_interval=timedelta(milliseconds=10),
    )
    await task.start()
    try:
        await asyncio.sleep(0.05)  # the cycle at start has run and found nothing to drop
        old = Job(id=str(uuid4()), printer_id=waiting.printer_id, state=JobState.COMPLETED)
        old.finished_at = datetime(2020, 1, 1, tzinfo=UTC)
        queue._jobs[old.id] = old
        async with asyncio.timeout(5):
            while old.id in queue._jobs:
                await asyncio.sleep(0.01)
        assert set(queue._jobs) == {waiting.id}
        assert store.evict_terminal_older_than.await_count == 1  # no second daily cycle
    finally:
        loops = [task._task, task._evict_task]
        await task.stop(timeout_s=1.0)
    assert all(t is not None and t.done() for t in loops)
    assert task._evict_task is None and task._task is None


@pytest.mark.asyncio
async def test_stop_ends_the_daily_loop_even_when_the_eviction_loop_died() -> None:
    """A non-timeout end of the eviction task (it raised) must not leave the daily loop
    running or make the lifespan's ``finally`` stop early: stop() logs it and goes on."""
    import asyncio

    from app.services.print_queue import PrintQueue

    store = AsyncMock()
    store.evict_terminal_older_than.return_value = 0
    task = CleanupTask(
        store=store, retention_days=30, interval=timedelta(seconds=99), queue=PrintQueue([])
    )

    async def broken() -> None:
        raise RuntimeError("evict loop broke")

    task._evict_loop = broken  # type: ignore[method-assign]
    await task.start()
    daily = task._task
    await asyncio.sleep(0)  # the broken loop has ended with its exception
    await task.stop(timeout_s=1.0)  # must not raise
    assert daily is not None and daily.done()
    assert task._task is None and task._evict_task is None
