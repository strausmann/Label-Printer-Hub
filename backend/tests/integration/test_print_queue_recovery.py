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

import asyncio
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
    # als Payload-Skip behandelt statt als allgemeiner Rerender-Fehler.
    # R2-1: Prefix jetzt recovery_skip_legacy_payload (deckt alle 3 fehlenden Keys).
    # Beide Pfade enden in JobState.FAILED — der Prefix unterscheidet die Ursache.
    fetched_bad = await store.get(bad_job.id)
    assert fetched_bad is not None
    assert fetched_bad.state == JobState.FAILED.value
    assert fetched_bad.error is not None
    assert (
        "recovery_skip_legacy_payload" in fetched_bad.error
        or "recovery_rerender_failed" in fetched_bad.error
    )

    # good_job muss in _jobs registriert worden sein (Recovery hat ihn enqueued).
    # Wir prüfen _jobs statt die asyncio.Queue, weil der Worker den Job bereits
    # konsumiert haben könnte (gleicher Event-Loop, aber Worker-Task darf aufwachen).
    assert str(good_job.id) in queue._jobs

    await queue.stop()


# --- 263-15 / 263-65: restart recovery re-batches the rows of one run -------------------------


class _RecordingPrinter(_FakePrinter):
    """Records single prints and batches; ``print_images`` is the tape batch call."""

    def __init__(self, printer_id):
        super().__init__(printer_id)
        self.singles = 0
        self.batches: list[int] = []

    async def print_image(self, image, *, tape_mm, **options):
        self.singles += 1

    async def print_images(self, images, *, tape_mm, **options):
        self.batches.append(len(images))


def _run_payload(run_id, *, awaits_confirmation=False):
    return {
        **_SAMPLE_PAYLOAD,
        "tape_run": {
            "run_id": None if run_id is None else str(run_id),
            "awaits_confirmation": awaits_confirmation,
        },
    }


async def _save_rows(store, printer_id, run_ids):
    """One QUEUED row per entry of *run_ids* (``None``: no run), created in list order. The ids
    are random, so only ``created_at`` carries the original order."""
    from datetime import UTC, datetime, timedelta

    base = datetime(2026, 11, 1, tzinfo=UTC)
    rows = []
    for i, run_id in enumerate(run_ids):
        row = Job(
            printer_id=printer_id,
            template_key=None,
            payload=_run_payload(run_id),
            created_at=base + timedelta(seconds=i),
        )
        await store.save_queued(row)
        rows.append(row)
    return rows


def _engine():
    engine_mock = MagicMock(spec=LayoutEngine)
    engine_mock.render.return_value = Image.new("1", (200, 106))
    return engine_mock


def _drain(queue, printer_id):
    items = []
    while not queue._queues[printer_id].empty():
        item = queue._queues[printer_id].get_nowait()
        if item is not None:
            items.append(item)
    return items


@pytest.mark.asyncio
async def test_recovery_rebatches_a_run(async_session_factory):
    """The rows of one run come back as ONE batch (one pre-roll), not label by label; rows
    without a run stay single and keep their place in the queue."""
    from app.services.print_queue import BatchJob

    store = SQLiteJobStore(async_session_factory)
    printer_id = uuid4()
    run_id = uuid4()
    rows = await _save_rows(store, printer_id, [None, run_id, run_id, run_id, None])

    queue = PrintQueue(printers=[_RecordingPrinter(printer_id)], store=store, engine=_engine())
    await queue.start()
    items = _drain(queue, printer_id)  # the worker has not run yet

    assert [type(i).__name__ for i in items] == ["Job", "BatchJob", "Job"]
    batch = items[1]
    assert isinstance(batch, BatchJob)
    assert batch.job_ids == [rows[1].id, rows[2].id, rows[3].id]
    assert len(batch.image_payloads) == 3
    assert [i.id for i in (items[0], items[2])] == [str(rows[0].id), str(rows[4].id)]
    for row in rows:  # all registered in memory, one Job per row
        assert str(row.id) in queue._jobs
    await queue.stop()


@pytest.mark.asyncio
async def test_recovery_keeps_order_of_run(async_session_factory):
    """The batch lists the labels in the order the rows were created (the ids are random)."""
    store = SQLiteJobStore(async_session_factory)
    printer_id = uuid4()
    run_id = uuid4()
    rows = await _save_rows(store, printer_id, [run_id] * 4)

    queue = PrintQueue(printers=[_RecordingPrinter(printer_id)], store=store, engine=_engine())
    await queue.start()
    batch = _drain(queue, printer_id)[0]
    assert [str(j) for j in batch.job_ids] == [str(r.id) for r in rows]
    await queue.stop()


@pytest.mark.asyncio
async def test_recovered_run_prints_in_one_call(async_session_factory):
    """End to end: the printer receives the run in one batch call, not label by label, and
    every row ends done."""
    store = SQLiteJobStore(async_session_factory)
    printer_id = uuid4()
    rows = await _save_rows(store, printer_id, [None])  # a single beside the run
    run_id = uuid4()
    rows += await _save_rows(store, printer_id, [run_id] * 3)
    printer = _RecordingPrinter(printer_id)

    queue = PrintQueue(printers=[printer], store=store, engine=_engine())
    await queue.start()
    try:
        async with asyncio.timeout(10):
            while True:
                states = [(await store.get(r.id)).state for r in rows]  # type: ignore[union-attr]
                if all(state == JobState.DONE.value for state in states):
                    break
                await asyncio.sleep(0.01)
        assert printer.batches == [3]  # one call for the run ...
        assert printer.singles == 1  # ... and the lone label on its own
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_recovery_rows_without_run_id_stay_single(async_session_factory):
    store = SQLiteJobStore(async_session_factory)
    printer_id = uuid4()
    await _save_rows(store, printer_id, [None, None])
    queue = PrintQueue(printers=[_RecordingPrinter(printer_id)], store=store, engine=_engine())
    await queue.start()
    items = _drain(queue, printer_id)
    assert [type(i).__name__ for i in items] == ["Job", "Job"]
    await queue.stop()


@pytest.mark.asyncio
async def test_recovered_run_keeps_the_half_cut_of_the_batch(async_session_factory):
    """The rows carry the batch-level cut mode (PrintService stores it); the recovered batch
    prints with it, not with a default."""
    from datetime import UTC, datetime

    store = SQLiteJobStore(async_session_factory)
    printer_id = uuid4()
    run_id = uuid4()
    for i in range(2):
        payload = _run_payload(run_id)
        payload["options"] = {**payload["options"], "half_cut": True}
        await store.save_queued(
            Job(
                printer_id=printer_id,
                template_key=None,
                payload=payload,
                created_at=datetime(2026, 11, 1, 0, 0, i, tzinfo=UTC),
            )
        )
    queue = PrintQueue(printers=[_RecordingPrinter(printer_id)], store=store, engine=_engine())
    await queue.start()
    batch = _drain(queue, printer_id)[0]
    assert batch.options["half_cut"] is True
    await queue.stop()
