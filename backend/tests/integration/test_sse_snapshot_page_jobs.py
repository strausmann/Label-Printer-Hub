"""The reconnect snapshot carries a page job's sub-state at the printer (spec 16, C2).

The sub-state lives only in the queue's in-memory job; a reloaded job page would otherwise show
nothing until the next live event.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest_asyncio
from app.models.printer import Printer
from app.repositories import jobs as jobs_repo
from app.repositories import printers as printers_repo
from app.services.sse_snapshot import build_snapshot


class _Queue:
    """The slice of ``PrintQueue`` the snapshot reads."""

    def __init__(self, jobs: dict[str, SimpleNamespace]) -> None:
        self._jobs = jobs

    def has_job(self, job_id: UUID | str) -> bool:
        return str(job_id) in self._jobs

    async def get(self, job_id: UUID | str) -> SimpleNamespace:
        return self._jobs[str(job_id)]


@pytest_asyncio.fixture
async def printer(db_session) -> Printer:
    p = Printer(name="Page", slug="page-printer", model="x", backend="mock")
    return await printers_repo.create(db_session, p)


def _page_job(**kw: object) -> SimpleNamespace:
    base = {
        "kind": "sheet_page",
        "summary": {"sheet_code": "L4736-0002", "cell_count": 9},
        "at_printer": "stopped",
        "at_printer_reasons": ["toner-empty"],
    }
    return SimpleNamespace(**{**base, **kw})


async def _job_frames(session, printer_id, queue):
    events = await build_snapshot(session, printer_id, queue=queue)
    return [e["data"] for e in events if e["type"] == "job.state_changed"]


async def test_page_job_frame_carries_the_sub_state(db_session, printer) -> None:
    job = await jobs_repo.create_queued(
        db_session, printer_id=printer.id, template_key=None, payload={}
    )
    await jobs_repo.mark_printing(db_session, job.id)
    queue = _Queue({str(job.id): _page_job()})
    (frame,) = await _job_frames(db_session, printer.id, queue)
    assert frame["job_id"] == str(job.id)
    assert frame["kind"] == "sheet_page"
    assert frame["at_printer"] == "stopped"
    assert frame["at_printer_reasons"] == ["toner-empty"]
    assert frame["summary"] == {"sheet_code": "L4736-0002", "cell_count": 9}


async def test_tape_job_frame_is_unchanged(db_session, printer) -> None:
    job = await jobs_repo.create_queued(
        db_session, printer_id=printer.id, template_key="t", payload={}
    )
    queue = _Queue({str(job.id): _page_job(kind=None)})
    (frame,) = await _job_frames(db_session, printer.id, queue)
    assert "kind" not in frame and "at_printer" not in frame


async def test_untracked_job_and_missing_queue_leave_the_frame_plain(db_session, printer) -> None:
    await jobs_repo.create_queued(db_session, printer_id=printer.id, template_key="t", payload={})
    (untracked,) = await _job_frames(db_session, printer.id, _Queue({}))
    (no_queue,) = await _job_frames(db_session, printer.id, None)
    assert "kind" not in untracked and "kind" not in no_queue


async def test_a_failing_queue_lookup_does_not_drop_the_job(db_session, printer) -> None:
    job = await jobs_repo.create_queued(
        db_session, printer_id=printer.id, template_key=None, payload={}
    )

    class _Broken(_Queue):
        async def get(self, job_id: UUID | str) -> SimpleNamespace:
            raise KeyError(job_id)  # evicted between has_job and get

    (frame,) = await _job_frames(db_session, printer.id, _Broken({str(job.id): _page_job()}))
    assert frame["job_id"] == str(job.id) and "kind" not in frame


async def test_jobs_past_the_snapshot_limit_get_no_frame(db_session, printer) -> None:
    """The 6th active job has no frame; the UI says "at the printer" for it (documented limit)."""
    from app.services.sse_snapshot import SNAPSHOT_JOB_LIMIT

    jobs = {}
    for _ in range(SNAPSHOT_JOB_LIMIT + 1):
        j = await jobs_repo.create_queued(
            db_session, printer_id=printer.id, template_key=None, payload={}
        )
        jobs[str(j.id)] = _page_job()
    frames = await _job_frames(db_session, printer.id, _Queue(jobs))
    assert len(frames) == SNAPSHOT_JOB_LIMIT
    assert all(f["kind"] == "sheet_page" for f in frames)


async def test_a_printing_job_is_not_pushed_out_by_queued_ones(db_session, printer) -> None:
    from app.services.sse_snapshot import SNAPSHOT_JOB_LIMIT

    jobs = {}
    for _ in range(SNAPSHOT_JOB_LIMIT + 1):
        await jobs_repo.create_queued(
            db_session, printer_id=printer.id, template_key=None, payload={}
        )
    printing = await jobs_repo.create_queued(
        db_session, printer_id=printer.id, template_key=None, payload={}
    )
    await jobs_repo.mark_printing(db_session, printing.id)
    jobs[str(printing.id)] = _page_job()
    frames = await _job_frames(db_session, printer.id, _Queue(jobs))
    assert len(frames) == SNAPSHOT_JOB_LIMIT
    by_id = {f["job_id"]: f for f in frames}
    assert by_id[str(printing.id)]["at_printer"] == "stopped"
