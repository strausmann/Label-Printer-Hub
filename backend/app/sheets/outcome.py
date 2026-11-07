"""How a sheet page job ends decides its cells (spec 8, D15) and the startup orphan sweep.

D15: cells are reserved at job creation (``reservation``), and this module owns the other
transitions:

* the job completed        -> ``used``       (``sheets.last_used_at`` is set);
* it ended cleanly, never printed -> the rows are deleted (the cells are free);
* it may have printed (started, interrupted, outcome unknown) -> ``unconfirmed``.

``SheetCellsOutcome`` is the outcome handler of the ``sheet_page`` kind. Every call is one write
transaction under the sheet write lock, touches only ``reserved`` rows of that job (so a second
call, or a late contradicting one, changes nothing and publishes nothing) and publishes
``sheet.updated`` after the commit. ``id_printed`` is set in the **same** transaction that turns
the cells into ``used``: a crash can never leave used cells with an ID label that is "not
printed" (or the reverse). A job that fails cleanly leaves it false (OC-40).

``sweep_orphan_reservations`` repairs reservations whose job ended, or vanished, while the hub
was down. It applies the same rule to what the database holds. A job counts as possibly printed
if ``result.started`` is true, ``jobs.error`` starts with ``interrupted:`` or the state is
``failed_restart``: the queue backstop persists an interrupted job *without* a result (the
stored one can still say ``started: false``), so ``started`` alone would free the cells of a
page that may have printed, and a second label would be printed on top of it (C4).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.job import Job, JobState
from app.models.sheet import Sheet, SheetCell, SheetTypeVersion
from app.repositories import sheets as repo
from app.services.event_bus import EventBus
from app.sheets.geometry import cell_count
from app.sheets.reservation import HUB_SOURCE, _publish_all, _Touched
from app.sheets.text import log_value
from app.sheets.type_service import version_geometry, write_transaction

logger = logging.getLogger(__name__)

SessionFactory = async_sessionmaker[AsyncSession]
Outcome = Literal["used", "unconfirmed", "free"]

ACTOR = "hub"
INTERRUPTED = "interrupted"

SWEEP_GRACE = timedelta(seconds=30)
"""A reservation commits before its page job is saved (C26). In that window the rows have no
``jobs`` row yet and are not orphans: the sweep spares rows younger than this."""

__all__ = ["SWEEP_GRACE", "SheetCellsOutcome", "SweepReport", "sweep_orphan_reservations"]


# ---------------------------------------------------------------------------- shared core


async def _summary(session: AsyncSession, sheet: Sheet, changed: list[int]) -> _Touched:
    version = await session.get(SheetTypeVersion, sheet.type_version_id)
    assert version is not None  # a foreign key
    total = cell_count(version_geometry(version))
    remaining = len(await repo.cells_of(session, sheet.id))
    return _Touched(
        code=sheet.code, total=total, free=total - remaining, changed=changed, state=sheet.state
    )


async def _settle_locked(
    session: AsyncSession,
    decisions: Sequence[tuple[SheetCell, Outcome]],
    jobs: dict[UUID, Job],
    *,
    margin_only: Sequence[UUID] = (),
) -> list[_Touched]:
    """Apply the decisions. The caller holds the write lock and commits.

    ``margin_only`` are sheets whose completed job carried the margin ID but reserved no row.
    Nothing is committed here, so cells and ``id_printed`` always land together.
    """
    now = datetime.now(UTC)
    changed: dict[UUID, list[int]] = {}
    used_on: set[UUID] = set()
    id_printed_on: set[UUID] = set(margin_only)
    for row, outcome in decisions:
        changed.setdefault(row.sheet_id, []).append(row.cell_no)
        if outcome == "free":
            await session.delete(row)  # D15: reserved -> free
            continue
        row.state = outcome  # D15: reserved -> used | unconfirmed
        row.updated_at = now
        row.updated_by = ACTOR
        if outcome != "used":
            continue
        used_on.add(row.sheet_id)
        carries_margin = row.job_id is not None and repo.margin_id_sheet(jobs.get(row.job_id))
        if row.source == HUB_SOURCE or carries_margin:
            id_printed_on.add(row.sheet_id)  # the ID label is on the sheet now
    await session.flush()
    touched: list[_Touched] = []
    for sheet_id in sorted(changed.keys() | id_printed_on, key=str):
        sheet = await session.get(Sheet, sheet_id, populate_existing=True)
        if sheet is None:  # foreign keys make this unreachable
            continue
        if sheet_id in used_on:
            sheet.last_used_at = now
        flipped = sheet_id in id_printed_on and not sheet.id_printed
        if sheet_id in id_printed_on:
            sheet.id_printed = True
        if sheet_id not in changed and not flipped:
            continue  # nothing changed for this sheet: no event
        await session.flush()
        touched.append(await _summary(session, sheet, sorted(changed.get(sheet_id, []))))
    return touched


# ---------------------------------------------------------------------------- handler


class SheetCellsOutcome:
    """``PageOutcomeHandler`` of the ``sheet_page`` kind."""

    def __init__(self, session_factory: SessionFactory, bus: EventBus | None) -> None:
        self._factory = session_factory
        self._bus = bus

    async def on_started(self, job_id: UUID) -> None:
        """A documented no-op: the cells stay ``reserved``.

        ``on_started`` is best-effort (a crash between the persisted ``started`` and the call
        leaves it undelivered), so nothing here may depend on it. ``started`` reaches this
        class through ``on_ended``; a restart through ``on_unknown``.
        """
        del job_id

    async def on_completed(self, job_id: UUID) -> None:
        await self._apply(job_id, "used")

    async def on_ended(
        self,
        job_id: UUID,
        *,
        state: Literal["cancelled", "failed"],
        started: bool,
        error_code: str,
    ) -> None:
        del state
        # ``interrupted`` means the page may have printed whatever ``started`` says (C4).
        possibly_printed = started or error_code == INTERRUPTED
        await self._apply(job_id, "unconfirmed" if possibly_printed else "free")

    async def on_unknown(self, job_id: UUID) -> None:
        await self._apply(job_id, "unconfirmed")

    async def _apply(self, job_id: UUID, outcome: Outcome) -> None:
        async with self._factory() as session, write_transaction(session):
            rows = await repo.reserved_cells_of_job(session, job_id)
            jobs = await repo.jobs_by_id(session, [job_id])
            margin_only: list[UUID] = []
            if outcome == "used" and not rows:
                # A completed margin-ID job without a reserved cell still prints the ID.
                sheet_id = repo.margin_id_sheet(jobs.get(job_id))
                if sheet_id is not None:
                    margin_only = [UUID(sheet_id)]
            touched = await _settle_locked(
                session, [(r, outcome) for r in rows], jobs, margin_only=margin_only
            )
            await session.commit()
        _publish_all(self._bus, touched)
        if touched:
            logger.info("job %s ended: cells %s", log_value(str(job_id)), outcome)


# ---------------------------------------------------------------------------- sweep


@dataclass
class SweepReport:
    """What a sweep changed, in cells."""

    used: int = 0
    unconfirmed: int = 0
    freed: int = 0
    untouched: int = 0
    """Cells of jobs that are still queued or printing."""
    spared: int = 0
    """Cells younger than the grace period whose job has no ``jobs`` row yet."""


def _possibly_printed(job: Job) -> bool:
    started = (job.result or {}).get("started") is True
    return started or (job.error or "").startswith(f"{INTERRUPTED}:")


def _decide(job: Job) -> Outcome | None:
    """The outcome a stored job state stands for; ``None``: it is not over."""
    if job.state == JobState.DONE.value:
        return "used"
    if job.state == JobState.FAILED_RESTART.value:
        return "unconfirmed"
    if job.state == JobState.CANCELLED.value:
        return "free"
    if job.state == JobState.FAILED.value:
        return "unconfirmed" if _possibly_printed(job) else "free"
    return None  # queued, printing: the job still decides


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


async def sweep_orphan_reservations(
    session_factory: SessionFactory,
    *,
    bus: EventBus | None = None,
    grace: timedelta = SWEEP_GRACE,
) -> SweepReport:
    """Settle ``reserved`` cells whose job ended, or vanished, while the hub was down.

    One write transaction: the lock comes first, every read happens after it. A cell with no
    ``jobs`` row is deleted only if it is older than ``grace``: a reservation that has just
    committed has no job row yet, and the job is saved after the commit, so re-reading under
    the lock cannot tell the two apart; only age can (C26).
    """
    report = SweepReport()
    async with session_factory() as session, write_transaction(session):
        reserved = await repo.all_reserved_cells(session)
        jobs = await repo.jobs_by_id(session, sorted({r.job_id for r in reserved if r.job_id}))
        cutoff = datetime.now(UTC) - grace
        decisions: list[tuple[SheetCell, Outcome]] = []
        for row in reserved:
            job = jobs.get(row.job_id) if row.job_id is not None else None
            if job is None:
                if _aware(row.updated_at) > cutoff:
                    report.spared += 1
                else:
                    decisions.append((row, "free"))
                continue
            outcome = _decide(job)
            if outcome is None:
                report.untouched += 1
            else:
                decisions.append((row, outcome))
        touched = await _settle_locked(session, decisions, jobs)
        await session.commit()
    for _, outcome in decisions:
        if outcome == "used":
            report.used += 1
        elif outcome == "unconfirmed":
            report.unconfirmed += 1
        else:
            report.freed += 1
    _publish_all(bus, touched)
    if decisions or report.spared:
        logger.info(
            "orphan sweep: %d used, %d unconfirmed, %d freed, %d untouched, %d spared",
            report.used,
            report.unconfirmed,
            report.freed,
            report.untouched,
            report.spared,
        )
    return report
