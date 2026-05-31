"""Phase 2: neue jobs_repo Helper fuer JobStore Adapter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.models.job import JobState
from app.repositories import jobs as jobs_repo


@pytest.mark.asyncio
async def test_mark_printing_as_failed_restart_only_printing(db_session):
    """mark_printing_as_failed_restart darf QUEUED-Jobs NICHT aendern."""
    printer_id = uuid4()
    other_printer_id = uuid4()

    queued = await jobs_repo.create_queued(
        db_session,
        printer_id=printer_id,
        template_key="t",
        payload={"k": "v"},
    )
    printing = await jobs_repo.create_queued(
        db_session,
        printer_id=printer_id,
        template_key="t",
        payload={"k": "v"},
    )
    await jobs_repo.mark_printing(db_session, printing.id)

    other_printing = await jobs_repo.create_queued(
        db_session,
        printer_id=other_printer_id,
        template_key="t",
        payload={"k": "v"},
    )
    await jobs_repo.mark_printing(db_session, other_printing.id)

    affected = await jobs_repo.mark_printing_as_failed_restart(
        db_session,
        printer_id,
    )
    assert affected == 1  # nur das eine PRINTING auf unserem printer

    await db_session.refresh(queued)
    await db_session.refresh(printing)
    await db_session.refresh(other_printing)

    assert queued.state == JobState.QUEUED.value
    assert printing.state == JobState.FAILED_RESTART.value
    assert printing.error == "printer_interrupted"
    assert printing.finished_at is not None
    assert other_printing.state == JobState.PRINTING.value  # anderer printer unangetastet


@pytest.mark.asyncio
async def test_list_active_filterable_by_printer(db_session):
    """list_active(printer_id=...) liefert nur Jobs des Druckers."""
    p1, p2 = uuid4(), uuid4()
    j1 = await jobs_repo.create_queued(db_session, printer_id=p1, template_key="t", payload={})
    j2 = await jobs_repo.create_queued(db_session, printer_id=p2, template_key="t", payload={})

    all_active = await jobs_repo.list_active(db_session)
    assert {j.id for j in all_active} == {j1.id, j2.id}

    p1_only = await jobs_repo.list_active(db_session, printer_id=p1)
    assert {j.id for j in p1_only} == {j1.id}


@pytest.mark.asyncio
async def test_evict_terminal_older_than(db_session):
    """evict loescht DONE/FAILED/CANCELLED/FAILED_RESTART aelter als age."""
    printer_id = uuid4()
    old_done = await jobs_repo.create_queued(
        db_session, printer_id=printer_id, template_key="t", payload={}
    )
    await jobs_repo.mark_printing(db_session, old_done.id)
    await jobs_repo.mark_done(db_session, old_done.id, result={})
    # backdate finished_at by hand for test
    old_done.finished_at = datetime.now(UTC) - timedelta(days=35)
    await db_session.commit()

    young_done = await jobs_repo.create_queued(
        db_session, printer_id=printer_id, template_key="t", payload={}
    )
    await jobs_repo.mark_printing(db_session, young_done.id)
    await jobs_repo.mark_done(db_session, young_done.id, result={})  # finished_at is now()

    # not terminal
    queued = await jobs_repo.create_queued(
        db_session, printer_id=printer_id, template_key="t", payload={}
    )

    deleted = await jobs_repo.evict_terminal_older_than(db_session, age=timedelta(days=30))
    assert deleted == 1

    assert await jobs_repo.get(db_session, old_done.id) is None
    assert await jobs_repo.get(db_session, young_done.id) is not None
    assert await jobs_repo.get(db_session, queued.id) is not None
