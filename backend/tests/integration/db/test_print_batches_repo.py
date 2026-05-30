"""print_batches-Tabelle: create + get + list_recent."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.models.print_batch import PrintBatch
from app.models.printer import Printer
from app.repositories import print_batches as batches_repo
from sqlalchemy.ext.asyncio import AsyncSession


async def _create_printer(session: AsyncSession) -> Printer:
    """Hilfsfunktion: legt einen minimalen Printer an (FK-Pflicht für printer_id)."""
    p = Printer(
        name=f"Test-Printer-{uuid4().hex[:8]}",
        slug=f"test-{uuid4().hex[:8]}",
        model="PT-P750W",
        backend="mock",
    )
    session.add(p)
    await session.commit()
    await session.refresh(p)
    return p


@pytest.mark.asyncio
async def test_create_and_get(db_session: AsyncSession):
    printer = await _create_printer(db_session)

    batch_id = uuid4()
    job_ids = [str(uuid4()) for _ in range(3)]
    b = PrintBatch(
        id=batch_id, printer_id=printer.id, job_ids=job_ids, created_by="björn@example.test"
    )
    await batches_repo.create(db_session, b)

    found = await batches_repo.get(db_session, batch_id)
    assert found is not None
    assert found.printer_id == printer.id
    assert len(found.job_ids) == 3


@pytest.mark.asyncio
async def test_list_recent_24h(db_session: AsyncSession):
    printer1 = await _create_printer(db_session)
    printer2 = await _create_printer(db_session)

    now = datetime.now(UTC)
    b1 = PrintBatch(
        id=uuid4(),
        printer_id=printer1.id,
        job_ids=["j1"],
        created_by="u",
        created_at=now - timedelta(hours=2),
    )
    b2 = PrintBatch(
        id=uuid4(),
        printer_id=printer2.id,
        job_ids=["j2"],
        created_by="u",
        created_at=now - timedelta(hours=48),
    )
    await batches_repo.create(db_session, b1)
    await batches_repo.create(db_session, b2)

    recent = await batches_repo.list_recent(db_session, hours=24)
    assert len(recent) == 1
    assert recent[0].id == b1.id
