# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Keep the print queue's in-memory job table bounded.

``PrintQueue`` tracks every job it ran in ``_jobs`` (with its rendered image) so that
``wait_for_job`` and the live events can reach it. A terminal job is only needed for a short
while after it ended: the API reads it from the store from then on. ``evict_finished`` drops the
ones that ended more than *keep_s* seconds ago; the cleanup task calls it each cycle.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.print_queue import PrintQueue

logger = logging.getLogger(__name__)

KEEP_FINISHED_S = 3600


def evict_finished(queue: PrintQueue, *, now: datetime, keep_s: int) -> int:
    """Forget terminal jobs that finished at least *keep_s* seconds before *now*.

    Queued, paused and printing jobs are never touched, and neither are the labels of a tape
    run the queue still holds. Returns how many jobs were dropped.
    """
    cutoff = now - timedelta(seconds=keep_s)
    dropped = 0
    for job_id, finished_at in queue.finished_jobs():
        if finished_at <= cutoff and queue.forget_job(job_id):
            dropped += 1
    if dropped:
        logger.info("Dropped %d finished jobs from the queue's memory", dropped)
    return dropped
