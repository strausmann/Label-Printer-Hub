"""Phase 2: periodischer Background-Task der terminal Jobs älter als retention_days löscht."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from app.services.job_retention import KEEP_FINISHED_S, evict_finished
from app.services.job_store import JobStore

if TYPE_CHECKING:
    from app.services.print_queue import PrintQueue

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

    Single-Use: nach stop() kann die Instanz nicht restartet werden.
    Lifespan startet eine neue Instanz beim App-Startup.
    """

    def __init__(
        self,
        store: JobStore,
        retention_days: int | Callable[[], int],
        interval: timedelta = _DEFAULT_INTERVAL,
        session_purge: Callable[[], Awaitable[int]] | None = None,
        queue: PrintQueue | None = None,
    ) -> None:
        if isinstance(retention_days, int):
            if retention_days < 1:
                raise ValueError("retention_days must be >= 1")
            fixed = retention_days
            self._retention_days: Callable[[], int] = lambda: fixed
        else:
            # D4: a callable is read on every run, so a settings change applies without restart.
            self._retention_days = retention_days
        self._store = store
        self._interval = interval
        # Browser sessions expired for more than a day are purged on the same schedule.
        self._session_purge = session_purge
        # Finished jobs also leave the queue's memory each cycle (``job_retention``).
        self._queue = queue
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
            except TimeoutError:
                self._task.cancel()
                logger.warning(
                    "CleanupTask hat sich nicht in %ss beendet, Task gecancelled",
                    timeout_s,
                )
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
            except TimeoutError:
                await self._run_once()

    async def _run_once(self) -> None:
        """Führt einen einzelnen Eviction-Run durch. Exceptions werden geloggt, nicht propagiert."""
        try:
            days = int(self._retention_days())
            if days < 1:
                raise ValueError("retention_days must be >= 1")
            deleted = await self._store.evict_terminal_older_than(timedelta(days=days))
            if deleted > 0:
                logger.info(
                    "CleanupTask: %d terminal Jobs älter als %d Tage gelöscht",
                    deleted,
                    days,
                )
        except Exception:
            logger.exception("CleanupTask: _run_once fehlgeschlagen")
        if self._queue is not None:
            try:
                evict_finished(self._queue, now=datetime.now(UTC), keep_s=KEEP_FINISHED_S)
            except Exception:
                logger.exception("CleanupTask: dropping finished jobs from memory failed")
        if self._session_purge is not None:
            try:
                purged = await self._session_purge()
                if purged > 0:
                    logger.info("CleanupTask: %d expired browser sessions purged", purged)
            except Exception:
                logger.exception("CleanupTask: session purge failed")
