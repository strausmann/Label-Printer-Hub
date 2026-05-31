"""PrintQueue.start() muss beim Neustart Recovery durchführen.

Task 6 — Phase 2 Job Persistence.

Tests verifizieren:
1. PRINTING-Jobs werden als FAILED_RESTART markiert
2. QUEUED-Jobs werden in FIFO-Reihenfolge in die asyncio.Queue re-enqueued

async_session_factory kommt aus tests/conftest.py (sichtbar für alle Tests).
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy import update
from sqlmodel import col

from app.models.job import Job, JobState
from app.services.job_store_sqlite import SQLiteJobStore
from app.services.print_queue import PrintQueue

# Minimal-Payload der recovery-fähigen Jobs: label_data + tape_mm wie
# print_service.submit_print_job() es schreibt (Task 5).
_SAMPLE_PAYLOAD = {
    "label_data": {
        "title": "Test",
        "primary_id": "T-001",
        "qr_payload": "https://example.com",
        "source_app": "manual",
        "secondary": [],
    },
    "tape_mm": 24,
}


class _FakePrinter:
    """Fake Drucker-Objekt das nie wirklich druckt."""

    def __init__(self, printer_id):
        self.id = printer_id

    async def print_image(self, image, *, tape_mm, **options):
        pass


def _make_mock_renderer_and_loader() -> tuple[MagicMock, MagicMock]:
    """Renderer + Loader-Mocks für Recovery-Tests.

    renderer.render() gibt ein minimales 1-bit-Image zurück.
    loader.get() gibt ein Mock-Template mit tape_mm=24 zurück.
    """
    mock_template = MagicMock()
    mock_template.tape_mm = 24
    mock_template.elements = []

    loader = MagicMock()
    loader.get.return_value = mock_template

    renderer = MagicMock()
    renderer.render.return_value = Image.new("1", (200, 106))

    return renderer, loader


@pytest.mark.asyncio
async def test_start_marks_printing_as_failed_restart(
    async_session_factory,
):
    """Jobs in PRINTING before start() must be marked FAILED_RESTART."""
    store = SQLiteJobStore(async_session_factory)
    printer_id = uuid4()

    # Pre-seed: ein Job der in PRINTING-Zustand steckt (simuliert Absturz)
    interrupted_job = Job(
        printer_id=printer_id,
        template_key="t",
        payload={},
    )
    await store.save_queued(interrupted_job)
    # save_queued setzt immer QUEUED — manuell auf PRINTING setzen
    async with async_session_factory() as s:
        await s.execute(
            update(Job).where(col(Job.id) == interrupted_job.id).values(
                state=JobState.PRINTING.value,
            )
        )
        await s.commit()

    fake_printer = _FakePrinter(printer_id)
    queue = PrintQueue(
        printers=[fake_printer],
        store=store,
    )
    await queue.start()

    fetched = await store.get(interrupted_job.id)
    assert fetched is not None
    assert fetched.state == JobState.FAILED_RESTART.value
    assert fetched.error == "printer_interrupted"

    await queue.stop()


@pytest.mark.asyncio
async def test_start_reenqueues_queued_jobs_in_fifo_order(
    async_session_factory,
):
    """Jobs in QUEUED state must be re-enqueued in created_at order."""
    store = SQLiteJobStore(async_session_factory)
    printer_id = uuid4()

    j1 = Job(printer_id=printer_id, template_key="t", payload=_SAMPLE_PAYLOAD)
    j2 = Job(printer_id=printer_id, template_key="t", payload=_SAMPLE_PAYLOAD)
    await store.save_queued(j1)
    await store.save_queued(j2)

    renderer, loader = _make_mock_renderer_and_loader()
    fake_printer = _FakePrinter(printer_id)
    queue = PrintQueue(
        printers=[fake_printer],
        store=store,
        renderer=renderer,
        loader=loader,
    )
    await queue.start()

    # asyncio.Queue-Reihenfolge prüfen — Worker läuft, holt aber Items
    # aus der Queue. Wir stoppen zuerst und lesen dann die verbliebenen Items
    # (Worker könnte einen schon konsumiert haben — deshalb queue.stop() FIRST)
    # Alternative: Queue direkt nach start() lesen bevor Worker sie leert.
    # Da Worker asyncio-concurrent ist, nutzen wir get_nowait() in einer
    # kurzen Schleife BEVOR Worker aufwacht (beide Tasks laufen im gleichen
    # Event-Loop — der Worker startet erst beim nächsten await).
    recovered_ids = []
    while not queue._queues[printer_id].empty():
        item = queue._queues[printer_id].get_nowait()
        if item is not None:  # None ist Worker-Sentinel aus stop()
            recovered_ids.append(item.id)

    assert recovered_ids == [str(j1.id), str(j2.id)]

    await queue.stop()
