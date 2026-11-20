# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""#215: retention keeps a job row while its cells are ``reserved``, or ``unconfirmed`` on an
active sheet. A discarded sheet is never resolved, so its unconfirmed cells pin nothing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import app.models  # noqa: F401
import pytest
from app.models.job import Job
from app.models.printer import Printer
from app.models.sheet import Sheet, SheetCell
from app.repositories import jobs as jobs_repo
from app.repositories import printers as printers_repo
from app.sheets import type_service as ts
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.sheets.test_reservation import G48, _fields, make_sheet


async def _finished_job_with_cell(
    session: AsyncSession, *, cell_state: str, sheet_state: str
) -> UUID:
    await ts.create_type(session, _fields(), G48, actor="tester")
    code = await make_sheet(session)
    printer = await printers_repo.create(
        session, Printer(name="P", slug=f"p-{uuid4().hex[:6]}", model="m", backend="mock")
    )
    job = await jobs_repo.create_queued(
        session, printer_id=printer.id, template_key="t", payload={}
    )
    await jobs_repo.mark_printing(session, job.id)
    await jobs_repo.mark_done(session, job.id, result={})
    job.finished_at = datetime.now(UTC) - timedelta(days=40)
    sheet = await _sheet(session, code)
    sheet.state = sheet_state
    session.add(
        SheetCell(sheet_id=sheet.id, cell_no=1, state=cell_state, source="hub", job_id=job.id)
    )
    await session.commit()
    return job.id


async def _sheet(session: AsyncSession, code: str) -> Sheet:
    return (await session.execute(select(Sheet).where(Sheet.code == code))).scalar_one()


async def _evict(session: AsyncSession) -> int:
    return await jobs_repo.evict_terminal_older_than(session, timedelta(days=30))


@pytest.mark.asyncio
async def test_discarded_sheet_does_not_pin_old_jobs(db_session: AsyncSession) -> None:
    job_id = await _finished_job_with_cell(
        db_session, cell_state="unconfirmed", sheet_state="discarded"
    )

    assert await _evict(db_session) == 1
    assert await db_session.get(Job, job_id) is None


@pytest.mark.asyncio
async def test_active_sheet_still_pins(db_session: AsyncSession) -> None:
    job_id = await _finished_job_with_cell(
        db_session, cell_state="unconfirmed", sheet_state="active"
    )

    assert await _evict(db_session) == 0
    assert await db_session.get(Job, job_id) is not None


@pytest.mark.asyncio
async def test_reserved_cell_pins_whatever_the_sheet_state(db_session: AsyncSession) -> None:
    job_id = await _finished_job_with_cell(
        db_session, cell_state="reserved", sheet_state="discarded"
    )

    assert await _evict(db_session) == 0
    assert await db_session.get(Job, job_id) is not None
