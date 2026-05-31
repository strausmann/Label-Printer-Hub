"""CleanupTask runs evict_terminal_older_than periodically."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from app.services.cleanup_task import CleanupTask


@pytest.mark.asyncio
async def test_cleanup_validates_retention_days():
    store = AsyncMock()
    with pytest.raises(ValueError, match="retention_days must be >= 1"):
        CleanupTask(store=store, retention_days=0)


@pytest.mark.asyncio
async def test_cleanup_initial_run_on_start():
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
async def test_cleanup_fail_soft_on_exception():
    store = AsyncMock()
    store.evict_terminal_older_than.side_effect = RuntimeError("boom")
    task = CleanupTask(store=store, retention_days=30, interval=timedelta(seconds=99))
    await task.start()
    await task.stop(timeout_s=1.0)
    # No exception propagated; loop survives
