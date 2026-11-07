"""Initial state snapshot for SSE streams.

On connect a stream emits the current state of a printer once, so a client does
not have to wait for the next real event. Items are plain dicts
(``channel``, ``type``, ``ts`` as ``datetime``, ``data``); the callers decide how
to frame them.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.job import Job, JobState
from app.repositories import jobs as jobs_repo
from app.repositories import printer_status_cache as status_cache_repo
from app.services.producers.ipp_status_producer import page_status_event_data

_log = logging.getLogger(__name__)

# Active jobs included in a snapshot, per printer.
SNAPSHOT_JOB_LIMIT = 5


async def build_snapshot(session: AsyncSession, printer_id: uuid.UUID) -> list[dict[str, Any]]:
    """Return synthetic events describing the current state of ``printer_id``.

    Contains ``printer.status`` and ``printer.tape_changed`` from the status cache
    and one ``job.state_changed`` per active (QUEUED|PRINTING) job, at most
    ``SNAPSHOT_JOB_LIMIT``. Read failures are logged and skipped, never raised.
    """
    snapshot: list[dict[str, Any]] = []
    now = datetime.now(UTC)
    # Re-parsed so only the canonical UUID text is ever logged or used in a channel name.
    printer_id = uuid.UUID(str(printer_id))
    pid = str(printer_id)

    try:
        cache = await status_cache_repo.get(session, printer_id)
        if cache is not None and cache.parsed:
            parsed = cache.parsed
            ts = cache.captured_at or now
            snapshot.append(
                {
                    "channel": f"printer:{pid}:state",
                    "type": "printer.status",
                    "ts": ts,
                    "data": (
                        page_status_event_data(parsed)
                        if parsed.get("kind") == "page"
                        else {
                            "hr_printer_status": parsed.get("hr_printer_status", "unknown"),
                            "error_flags": parsed.get("error_flags", []),
                            "online": parsed.get("online", False),
                        }
                    ),
                }
            )
            # Only when the tape width is known: a null width would overwrite the
            # client's correct tape state with "no tape loaded".
            loaded_tape_mm = parsed.get("loaded_tape_mm")
            if loaded_tape_mm is not None:
                snapshot.append(
                    {
                        "channel": f"printer:{pid}:tape",
                        "type": "printer.tape_changed",
                        "ts": ts,
                        "data": {
                            "from_mm": None,
                            "to_mm": loaded_tape_mm,
                            "tape_label": f"{loaded_tape_mm}mm",
                        },
                    }
                )
    except Exception:
        _log.debug("build_snapshot: status cache read failed for %r", pid)

    try:
        # COUNT over all non-terminal states so queue_depth stays accurate beyond the list limit.
        non_terminal = (JobState.QUEUED.value, JobState.PRINTING.value)
        count_stmt = (
            select(func.count())
            .select_from(Job)
            .where(col(Job.printer_id) == printer_id)
            .where(col(Job.state).in_(non_terminal))
        )
        queue_depth: int = (await session.execute(count_stmt)).scalar_one()

        active_jobs = await jobs_repo.list_by_filter(
            session, printer_id=printer_id, state=JobState.QUEUED.value, limit=SNAPSHOT_JOB_LIMIT
        )
        active_jobs += await jobs_repo.list_by_filter(
            session, printer_id=printer_id, state=JobState.PRINTING.value, limit=SNAPSHOT_JOB_LIMIT
        )
        for job in active_jobs[:SNAPSHOT_JOB_LIMIT]:
            snapshot.append(
                {
                    "channel": f"printer:{pid}:queue",
                    "type": "job.state_changed",
                    "ts": job.created_at,
                    "data": {
                        "job_id": str(job.id),
                        "from_state": job.state,
                        "to_state": job.state,
                        "queue_depth": queue_depth,
                        "error_code": None,
                    },
                }
            )
    except Exception:
        _log.debug("build_snapshot: job query failed for %r", pid)

    return snapshot
