"""PrintQueue.start() muss beim Neustart Recovery durchführen.

Task 6 — Phase 2 Job Persistence.

Tests verifizieren:
1. PRINTING-Jobs werden als FAILED_RESTART markiert
2. QUEUED-Jobs werden in FIFO-Reihenfolge in die asyncio.Queue re-enqueued

Phase 1k.1a (Task 25): Adapted from template_id/renderer/loader API to
content_type/LayoutEngine API. _SAMPLE_PAYLOAD updated to match new format.
test_recovery_skips_jobs_with_deleted_template removed (TemplateNotFoundError gone).

async_session_factory kommt aus tests/conftest.py (sichtbar für alle Tests).
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from app.models.job import Job, JobState
from app.services.job_store_sqlite import SQLiteJobStore
from app.services.layout_engine import LayoutEngine
from app.services.print_queue import PrintQueue
from PIL import Image
from sqlalchemy import update
from sqlmodel import col

# Minimal-Payload der recovery-fähigen Jobs: label_data + content_type +
# rendered_tape_mm wie print_service.submit_print_job() es schreibt (Phase 1k.1a).
_SAMPLE_PAYLOAD = {
    "label_data": {
        "title": "Test",
        "primary_id": "T-001",
        "qr_payload": "https://example.com",
        "source_app": "manual",
        "secondary": [],
        "items": [],
    },
    "content_type": "qr_two_lines",
    "rendered_tape_mm": 24,
    "tape_mm": 24,
    "options": {
        "copies": 1,
        "auto_cut": True,
        "high_resolution": False,
        "half_cut": False,
        "last_page": True,
    },
}


class _FakePrinter:
    """Fake Drucker-Objekt das nie wirklich druckt."""

    def __init__(self, printer_id):
        self.id = printer_id

    async def print_image(self, image, *, tape_mm, **options):
        pass


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
        template_key=None,
        payload={},
    )
    await store.save_queued(interrupted_job)
    # save_queued setzt immer QUEUED — manuell auf PRINTING setzen
    async with async_session_factory() as s:
        await s.execute(
            update(Job)
            .where(col(Job.id) == interrupted_job.id)
            .values(
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

    j1 = Job(printer_id=printer_id, template_key=None, payload=_SAMPLE_PAYLOAD)
    j2 = Job(printer_id=printer_id, template_key=None, payload=_SAMPLE_PAYLOAD)
    await store.save_queued(j1)
    await store.save_queued(j2)

    # Phase 1k.1a: use engine mock instead of renderer + loader
    engine_mock = MagicMock(spec=LayoutEngine)
    engine_mock.render.return_value = Image.new("1", (200, 106))

    fake_printer = _FakePrinter(printer_id)
    queue = PrintQueue(
        printers=[fake_printer],
        store=store,
        engine=engine_mock,
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


@pytest.mark.asyncio
async def test_recovery_skips_jobs_with_missing_label_data(
    async_session_factory,
):
    """C-1: Job mit payload={} (kein label_data) darf Recovery nicht abbrechen.

    Erwartet:
    - Der fehlerhafte Job wird als FAILED markiert (error enthält
      'recovery_rerender_failed').
    - Ein weiterer QUEUED-Job mit gültigem Payload wird trotzdem re-enqueued.
    """
    store = SQLiteJobStore(async_session_factory)
    printer_id = uuid4()

    # Job ohne label_data — simuliert alte Pre-Phase-2-Row oder korrupte Daten
    bad_job = Job(printer_id=printer_id, template_key=None, payload={})
    await store.save_queued(bad_job)

    # Gültiger Job der trotzdem verarbeitet werden soll
    good_job = Job(printer_id=printer_id, template_key=None, payload=_SAMPLE_PAYLOAD)
    await store.save_queued(good_job)

    # Phase 1k.1a: use engine mock instead of renderer + loader
    engine_mock = MagicMock(spec=LayoutEngine)
    engine_mock.render.return_value = Image.new("1", (200, 106))

    fake_printer = _FakePrinter(printer_id)
    queue = PrintQueue(
        printers=[fake_printer],
        store=store,
        engine=engine_mock,
    )
    await queue.start()

    # bad_job muss als FAILED in der DB stehen.
    # Phase 1k.1a Round-1 fix (MED-1): Jobs ohne content_type/label_data werden
    # jetzt als Webhook-Payload-Skip behandelt (recovery_skip_webhook_payload)
    # statt als allgemeiner Rerender-Fehler (recovery_rerender_failed).
    # Beide Pfade enden in JobState.FAILED — der Prefix unterscheidet die Ursache.
    fetched_bad = await store.get(bad_job.id)
    assert fetched_bad is not None
    assert fetched_bad.state == JobState.FAILED.value
    assert fetched_bad.error is not None
    assert (
        "recovery_skip_webhook_payload" in fetched_bad.error
        or "recovery_rerender_failed" in fetched_bad.error
    )

    # good_job muss in _jobs registriert worden sein (Recovery hat ihn enqueued).
    # Wir prüfen _jobs statt die asyncio.Queue, weil der Worker den Job bereits
    # konsumiert haben könnte (gleicher Event-Loop, aber Worker-Task darf aufwachen).
    assert str(good_job.id) in queue._jobs

    await queue.stop()
