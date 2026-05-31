"""Phase 2: periodischer Background-Task der terminal Jobs älter als retention_days löscht."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from app.services.job_store import JobStore

logger = logging.getLogger(__name__)

_DEFAULT_INTERVAL = timedelta(hours=24)


class CleanupTask:
    """Background asyncio task der periodisch store.evict_terminal_older_than(retention) aufruft.

    Lifecycle::

        task = CleanupTask(store=store, retention_days=30)
        await task.start()   # startet den Loop, führt Initial-Run durch
        # ... App läuft ...
        await task.stop()    # signalisiert Stop, wartet auf Loop-Ende

    Der Loop führt beim Start sofort einen ersten Run durch, danach in ``interval``-Abständen.
    Exceptions in _run_once werden geloggt und der Loop läuft weiter (fail-soft).
    """

    def __init__(
        self,
        store: JobStore,
        retention_days: int,
        interval: timedelta = _DEFAULT_INTERVAL,
    ) -> None:
        if retention_days < 1:
            raise ValueError("retention_days must be >= 1")
        self._store = store
        self._retention = timedelta(days=retention_days)
        self._interval = interval
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        """Startet den Background-Loop. Idempotent — zweites start() ist no-op."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._loop(), name="job-cleanup")

    async def stop(self, timeout_s: float = 5.0) -> None:
        """Signalisiert dem Loop zu stoppen und wartet bis zu timeout_s Sekunden.

        Nach Ablauf des Timeouts wird der Task gecancelled.
        """
        self._stopping.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=timeout_s)
            except asyncio.TimeoutError:
                self._task.cancel()
                logger.warning("CleanupTask hat sich nicht in %ss beendet, Task gecancelled", timeout_s)
            self._task = None

    async def _loop(self) -> None:
        """Haupt-Loop: Initial-Run + periodische Wiederholung bis stopping gesetzt wird."""
        await self._run_once()
        while not self._stopping.is_set():
            try:
                await asyncio.wait_for(
                    self._stopping.wait(),
                    timeout=self._interval.total_seconds(),
                )
            except asyncio.TimeoutError:
                await self._run_once()

    async def _run_once(self) -> None:
        """Führt einen einzelnen Eviction-Run durch. Exceptions werden geloggt, nicht propagiert."""
        try:
            deleted = await self._store.evict_terminal_older_than(self._retention)
            if deleted > 0:
                logger.info(
                    "CleanupTask: %d terminal Jobs älter als %d Tage gelöscht",
                    deleted,
                    self._retention.days,
                )
        except Exception:
            logger.exception("CleanupTask: _run_once fehlgeschlagen")
