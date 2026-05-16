"""Tests for the jobs repository — state machine + sweep."""

from __future__ import annotations

from uuid import UUID

import pytest
from app.models.job import Job, JobState
from app.models.printer import Printer
from app.repositories import jobs, printers

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_printer(session) -> Printer:
    p = Printer(
        name="ql820-office",
        model="ql-series",
        backend="ql",
        connection={"interface": "usb"},
    )
    return await printers.create(session, p)


async def _queued(session, printer: Printer, *, key: str = "label-v1") -> Job:
    return await jobs.create_queued(
        session,
        printer_id=printer.id,
        template_key=key,
        payload={"line1": "Hello"},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_queued_starts_in_queued_state(session):
    printer = await _make_printer(session)
    job = await _queued(session, printer)

    assert job.id is not None
    assert isinstance(job.id, UUID)
    assert job.state == JobState.QUEUED.value
    assert job.printer_id == printer.id
    assert job.template_key == "label-v1"
    assert job.payload == {"line1": "Hello"}
    assert job.result is None
    assert job.error is None
    assert job.started_at is None
    assert job.finished_at is None
    assert job.created_at is not None


@pytest.mark.asyncio
async def test_state_machine_happy_path(session):
    """queued → printing → done; timestamps populated correctly."""
    printer = await _make_printer(session)
    job = await _queued(session, printer)

    # queued → printing
    printing = await jobs.mark_printing(session, job.id)
    assert printing.state == JobState.PRINTING.value
    assert printing.started_at is not None
    assert printing.finished_at is None

    # printing → done
    done = await jobs.mark_done(session, job.id, result={"pages": 1})
    assert done.state == JobState.DONE.value
    assert done.result == {"pages": 1}
    assert done.finished_at is not None
    assert done.started_at is not None  # preserved


@pytest.mark.asyncio
async def test_failed_transition_from_queued(session):
    """queued → failed; finished_at set, error stored."""
    printer = await _make_printer(session)
    job = await _queued(session, printer)

    failed = await jobs.mark_failed(session, job.id, error="usb_timeout")
    assert failed.state == JobState.FAILED.value
    assert failed.error == "usb_timeout"
    assert failed.finished_at is not None
    assert failed.started_at is None  # never started


@pytest.mark.asyncio
async def test_cancelled_from_queued(session):
    """queued → cancelled; finished_at set."""
    printer = await _make_printer(session)
    job = await _queued(session, printer)

    cancelled = await jobs.mark_cancelled(session, job.id)
    assert cancelled.state == JobState.CANCELLED.value
    assert cancelled.finished_at is not None
    assert cancelled.started_at is None


@pytest.mark.asyncio
async def test_cancelled_from_printing(session):
    """queued → printing → cancelled."""
    printer = await _make_printer(session)
    job = await _queued(session, printer)
    await jobs.mark_printing(session, job.id)

    cancelled = await jobs.mark_cancelled(session, job.id)
    assert cancelled.state == JobState.CANCELLED.value
    assert cancelled.finished_at is not None
    assert cancelled.started_at is not None  # set during mark_printing


@pytest.mark.asyncio
async def test_invalid_transition_raises(session):
    """mark_done from queued (skipping printing) must raise ValueError."""
    printer = await _make_printer(session)
    job = await _queued(session, printer)

    with pytest.raises(ValueError, match="expected 'printing'"):
        await jobs.mark_done(session, job.id)


@pytest.mark.asyncio
async def test_restart_sweep(session):
    """mark_inflight_as_failed_restart: 2 queued + 1 printing swept; 1 done untouched."""
    printer = await _make_printer(session)

    q1 = await _queued(session, printer, key="label-v1")
    q2 = await _queued(session, printer, key="label-v2")
    p1 = await _queued(session, printer, key="label-v3")
    await jobs.mark_printing(session, p1.id)
    d1 = await _queued(session, printer, key="label-v4")
    await jobs.mark_printing(session, d1.id)
    await jobs.mark_done(session, d1.id)

    swept = await jobs.mark_inflight_as_failed_restart(session)
    assert swept == 3  # q1, q2, p1

    # Refresh from DB and verify states
    updated_q1 = await session.get(Job, q1.id)
    updated_q2 = await session.get(Job, q2.id)
    updated_p1 = await session.get(Job, p1.id)
    updated_d1 = await session.get(Job, d1.id)

    assert updated_q1.state == JobState.FAILED_RESTART.value
    assert updated_q1.error == "restart_during_inflight"
    assert updated_q1.finished_at is not None

    assert updated_q2.state == JobState.FAILED_RESTART.value
    assert updated_p1.state == JobState.FAILED_RESTART.value

    # The done job must be untouched
    assert updated_d1.state == JobState.DONE.value
    assert updated_d1.error is None


@pytest.mark.asyncio
async def test_list_active_returns_only_inflight(session):
    """list_active returns queued + printing only; done/failed excluded."""
    printer = await _make_printer(session)

    q = await _queued(session, printer, key="q")
    p = await _queued(session, printer, key="p")
    await jobs.mark_printing(session, p.id)
    d = await _queued(session, printer, key="d")
    await jobs.mark_printing(session, d.id)
    await jobs.mark_done(session, d.id)

    active = await jobs.list_active(session)
    active_ids = {j.id for j in active}

    assert q.id in active_ids
    assert p.id in active_ids
    assert d.id not in active_ids
    assert len(active) == 2
