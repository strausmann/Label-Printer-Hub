"""GET /api/batches/{id} liefert Snapshot mit Jobs + Summary."""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from app.models.print_batch import PrintBatch
from app.models.printer import Printer
from app.repositories import jobs as jobs_repo
from app.repositories import print_batches as batches_repo
from app.repositories import printers as printers_repo

# --- Fixtures (R2-C6: explizit definiert, nicht aus nicht-existenter conftest) ---


@pytest_asyncio.fixture
async def test_printer(db_session) -> Printer:
    """Drucker-Zeile in der Test-DB (jobs.printer_id + print_batches.printer_id FK)."""
    p = Printer(name="Test Printer", slug="test-printer", model="PT-P750W", backend="mock")
    return await printers_repo.create(db_session, p)


@pytest_asyncio.fixture
async def sample_batch_done(db_session, test_printer):
    """2 DONE-Jobs + PrintBatch in der Test-DB."""
    printer_id = test_printer.id
    j1 = await jobs_repo.create_queued(
        db_session, printer_id=printer_id, template_key="t", payload={}
    )
    j2 = await jobs_repo.create_queued(
        db_session, printer_id=printer_id, template_key="t", payload={}
    )
    await jobs_repo.mark_printing(db_session, j1.id)
    await jobs_repo.mark_done(db_session, j1.id, result={})
    await jobs_repo.mark_printing(db_session, j2.id)
    await jobs_repo.mark_done(db_session, j2.id, result={})

    batch = PrintBatch(
        printer_id=printer_id,
        job_ids=[str(j1.id), str(j2.id)],
        created_by="test@example.com",
    )
    db_session.add(batch)
    await db_session.commit()
    await db_session.refresh(batch)
    return batch


@pytest_asyncio.fixture
async def batch_with_ghost_ids(db_session, test_printer):
    """PrintBatch mit 3 job_ids, davon 2 nach Anlage gelöscht (Geister-IDs)."""
    printer_id = test_printer.id
    j1 = await jobs_repo.create_queued(
        db_session, printer_id=printer_id, template_key="t", payload={}
    )
    await jobs_repo.mark_printing(db_session, j1.id)
    await jobs_repo.mark_done(db_session, j1.id, result={})

    ghost_id_1 = str(uuid4())  # nie in DB eingetragen
    ghost_id_2 = str(uuid4())  # nie in DB eingetragen

    batch = PrintBatch(
        printer_id=printer_id,
        job_ids=[str(j1.id), ghost_id_1, ghost_id_2],
        created_by="test@example.com",
    )
    db_session.add(batch)
    await db_session.commit()
    await db_session.refresh(batch)
    return batch


# --- Tests ---


@pytest.mark.asyncio
async def test_get_batch_returns_404_for_unknown(client):
    # client kommt aus tests/integration/conftest.py:222 (fake-auth, kein eigenes auth_client)
    resp = await client.get(f"/api/batches/{uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_batch_returns_summary_with_all_terminal(
    client,
    sample_batch_done,
):
    resp = await client.get(f"/api/batches/{sample_batch_done.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(sample_batch_done.id)
    assert body["summary"]["total"] == 2
    assert body["summary"]["done"] == 2
    assert body["summary"]["queued"] == 0
    assert body["summary"]["all_terminal"] is True
    assert len(body["jobs"]) == 2


@pytest.mark.asyncio
async def test_get_batch_jobs_in_batch_order(
    client,
    sample_batch_done,
):
    """Job-Reihenfolge im Response entspricht batch.job_ids Array, nicht DB-default."""
    resp = await client.get(f"/api/batches/{sample_batch_done.id}")
    body = resp.json()
    received_ids = [j["id"] for j in body["jobs"]]
    expected_ids = [str(jid) for jid in sample_batch_done.job_ids]
    assert received_ids == expected_ids


@pytest.mark.asyncio
async def test_get_batch_handles_missing_jobs(client, batch_with_ghost_ids):
    """Wenn Jobs vom Cleanup gelöscht sind (Geister-IDs), werden sie übersprungen."""
    resp = await client.get(f"/api/batches/{batch_with_ghost_ids.id}")
    body = resp.json()
    # batch_with_ghost_ids hat 3 job_ids, aber nur 1 existiert in der DB
    assert body["summary"]["total"] == 1


@pytest.mark.asyncio
async def test_failed_counter_includes_failed_restart(
    client,
    db_session,
):
    """summary.failed zählt FAILED + FAILED_RESTART zusammen."""
    printer = Printer(
        name="Counter Test Printer",
        slug="counter-test-printer",
        model="PT-P750W",
        backend="mock",
    )
    printer = await printers_repo.create(db_session, printer)
    printer_id = printer.id

    # Job 1: FAILED via mark_failed
    j_failed = await jobs_repo.create_queued(
        db_session, printer_id=printer_id, template_key="t", payload={}
    )
    await jobs_repo.mark_printing(db_session, j_failed.id)
    await jobs_repo.mark_failed(db_session, j_failed.id, "tape_empty")

    # Job 2: FAILED_RESTART via mark_printing_as_failed_restart
    j_restart = await jobs_repo.create_queued(
        db_session, printer_id=printer_id, template_key="t", payload={}
    )
    await jobs_repo.mark_printing(db_session, j_restart.id)
    await jobs_repo.mark_printing_as_failed_restart(db_session, printer_id)

    batch = await batches_repo.create(
        db_session,
        PrintBatch(
            printer_id=printer_id,
            job_ids=[str(j_failed.id), str(j_restart.id)],
            created_by="test@example.com",
        ),
    )

    resp = await client.get(f"/api/batches/{batch.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["failed"] == 2  # FAILED + FAILED_RESTART zusammen
    assert body["summary"]["cancelled"] == 0
    assert body["summary"]["all_terminal"] is True
