# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The periodic sweep of sheet reservations whose job ended while the hub ran (266-04).

A sheet page's cells are settled by its outcome handler when the job ends. When that call is
lost or raises, the cells stay ``reserved``; until now only the next start repaired them (the
startup ``sweep_orphan_reservations``). Meanwhile the sheet cannot be discarded (``sheet_busy``)
and the cells cannot be used.

This sweep applies the startup sweep's rules every ``interval_s`` seconds, narrowed for a hub
that serves requests at the same time:

- a job the queue still tracks in memory (``queue.has_job``) is left alone, whatever its row
  says: it may still be running, or its outcome call may be on its way;
- a job whose row changed less than ``min_age_s`` ago is left alone: it ended a moment ago and
  its own outcome call settles it;
- a cell without a ``jobs`` row is left alone: a running hub may be saving that job right now
  (C26); the startup sweep decides those.

The queue is asked at decision time, after the cells and jobs were read under the write lock,
so a job taken up after the read is still spared.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from app.models.job import Job
from app.services.event_bus import EventBus
from app.sheets.outcome import SessionFactory, SweepReport, sweep_reservations

logger = logging.getLogger(__name__)

__all__ = ["SheetReservationSweep"]


class _Queue(Protocol):
    def has_job(self, job_id: str | UUID) -> bool: ...


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


class SheetReservationSweep:
    """Settle the cells of jobs that ended, but whose outcome call never settled them."""

    def __init__(
        self,
        session_factory: SessionFactory,
        queue: _Queue,
        bus: EventBus | None,
        *,
        interval_s: int = 300,
        min_age_s: int = 600,
    ) -> None:
        if interval_s <= 0:
            raise ValueError("interval_s must be > 0")  # 0 would loop write transactions
        if min_age_s < 0:
            raise ValueError("min_age_s must be >= 0")
        self._factory = session_factory
        self._queue = queue
        self._bus = bus
        self._interval_s = interval_s
        self._min_age = timedelta(seconds=min_age_s)
        self._stopping = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the loop; its first sweep runs after one interval (the startup sweep ran)."""
        if self._task is not None:
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._loop(), name="sheet-reservation-sweep")

    async def stop(self, timeout_s: float = 5.0) -> None:
        """Stop the loop; a sweep in progress finishes, or is cancelled after ``timeout_s``."""
        task, self._task = self._task, None
        if task is None:
            return
        self._stopping.set()
        try:
            await asyncio.wait_for(task, timeout=timeout_s)
        except TimeoutError:
            logger.warning("sheet reservation sweep did not stop in %ss, cancelled", timeout_s)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def run_once(self) -> SweepReport:
        """One sweep. Raises what the database raises."""
        cutoff = datetime.now(UTC) - self._min_age

        def keep(job: Job) -> bool:
            return self._queue.has_job(job.id) or _aware(job.updated_at) > cutoff

        return await sweep_reservations(
            self._factory,
            bus=self._bus,
            keep=keep,
            settle_jobless=False,
            name="reservation sweep",
        )

    async def _loop(self) -> None:
        while not self._stopping.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stopping.wait(), timeout=self._interval_s)
            if self._stopping.is_set():
                return
            try:
                await self.run_once()
            except Exception:
                logger.exception("sheet reservation sweep failed; the next run tries again")
