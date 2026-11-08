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
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.job import Job, JobState
from app.repositories import jobs as jobs_repo
from app.repositories import printer_status_cache as status_cache_repo
from app.services.producers.ipp_status_producer import page_status_event_data

if TYPE_CHECKING:
    from app.services.print_queue import PrintQueue

_log = logging.getLogger(__name__)

# Active jobs included in a snapshot, per printer. A job past the limit gets no frame on connect:
# the UI then says "at the printer" for it without a sub-state and learns it from the next live
# event. Queued jobs are listed before printing ones, so many waiting jobs can crowd one out.
SNAPSHOT_JOB_LIMIT = 5


async def _page_job_fields(queue: PrintQueue | None, job_id: uuid.UUID) -> dict[str, Any]:
    """Where a page job stands at the printer, from the queue's in-memory job (spec 16).

    The sub-state is not persisted, so a client that connects after the last live event can only
    learn it here. Empty for a tape job, an untracked job or a failed lookup: the frame then
    stays what it was and the UI says "at the printer" without guessing.
    """
    if queue is None or not queue.has_job(job_id):
        return {}
    try:
        live = await queue.get(job_id)
    except KeyError:  # evicted between the check and the read
        return {}
    if live.kind is None:
        return {}
    return {
        "kind": live.kind,
        "at_printer": live.at_printer,
        "at_printer_reasons": list(live.at_printer_reasons),
        "summary": live.summary,
    }


async def build_snapshot(
    session: AsyncSession, printer_id: uuid.UUID, queue: PrintQueue | None = None
) -> list[dict[str, Any]]:
    """Return synthetic events describing the current state of ``printer_id``.

    Contains ``printer.status`` and ``printer.tape_changed`` from the status cache
    and one ``job.state_changed`` per active (QUEUED|PRINTING) job, at most
    ``SNAPSHOT_JOB_LIMIT``; a page job's frame also carries ``kind``, ``at_printer``,
    ``at_printer_reasons`` and ``summary`` when ``queue`` tracks it. Read failures are logged
    and skipped, never raised.
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
                        **await _page_job_fields(queue, job.id),
                    },
                }
            )
    except Exception:
        _log.debug("build_snapshot: job query failed for %r", pid)

    return snapshot
