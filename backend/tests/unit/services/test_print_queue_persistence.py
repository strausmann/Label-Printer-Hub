"""PrintQueue muss store.mark_* bei jeder State-Transition aufrufen.

Tests verwenden die echte PrintQueue-Signatur:
    PrintQueue(printers=[...], on_state_change=None, store=store)

Der Worker bridget dataclass-Job.id (str) via UUID(job.id) an den Store.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from app.services.job_store import MemoryJobStore
from app.services.print_queue import PrintQueue
from PIL import Image

# Stabile Printer-UUID für alle Tests in diesem Modul
_PRINTER_ID = UUID("cccccccc-0000-0000-0000-000000000001")


def _make_printer(printer_id: UUID = _PRINTER_ID) -> MagicMock:
    """Erstellt einen schnellen Fake-Printer der print_image sofort beendet."""
    printer = MagicMock()
    printer.id = printer_id
    printer.print_image = AsyncMock(return_value=None)
    return printer


def _sample_image() -> Image.Image:
    return Image.new("1", (300, 76))


@pytest.mark.asyncio
async def test_printqueue_constructor_accepts_store() -> None:
    """PrintQueue.__init__ muss store=JobStore annehmen und in _store ablegen."""
    store = MemoryJobStore()
    queue = PrintQueue(
        printers=[_make_printer()],
        store=store,
    )
    assert queue._store is store


@pytest.mark.asyncio
async def test_printqueue_calls_mark_printing_then_mark_done() -> None:
    """Worker muss store.mark_printing dann store.mark_done bei Erfolg aufrufen."""
    store = AsyncMock(spec=MemoryJobStore)
    # Recovery in start() ruft mark_interrupted + list_pending auf — konfigurieren
    # damit start() sauber durchläuft ohne TypeError bei > 0-Vergleich.
    store.mark_interrupted.return_value = 0
    store.list_pending.return_value = []
    printer = _make_printer()
    queue = PrintQueue(
        printers=[printer],
        store=store,
    )
    await queue.start()
    try:
        job_id = await queue.submit(_PRINTER_ID, _sample_image(), tape_mm=12)
        await queue.wait_for_job(job_id, timeout_s=5)
    finally:
        await queue.stop()

    # job.id ist str — Store-Calls bekommen UUID(job_id)
    expected_uuid = UUID(job_id)
    store.mark_printing.assert_awaited_once_with(expected_uuid)
    store.mark_done.assert_awaited_once_with(expected_uuid)
    store.mark_failed.assert_not_awaited()


@pytest.mark.asyncio
async def test_printqueue_calls_mark_failed_on_printer_error() -> None:
    """Worker muss store.mark_failed aufrufen wenn printer.print_image wirft."""
    from app.printer_backends.exceptions import PrinterError

    store = AsyncMock(spec=MemoryJobStore)
    # Recovery in start() konfigurieren — kein Absturz bei > 0-Vergleich
    store.mark_interrupted.return_value = 0
    store.list_pending.return_value = []
    printer = _make_printer()
    printer.print_image = AsyncMock(side_effect=PrinterError("tape_empty"))
    queue = PrintQueue(
        printers=[printer],
        store=store,
    )
    await queue.start()
    try:
        job_id = await queue.submit(_PRINTER_ID, _sample_image(), tape_mm=12)
        await queue.wait_for_job(job_id, timeout_s=5)
    finally:
        await queue.stop()

    expected_uuid = UUID(job_id)
    store.mark_printing.assert_awaited_once_with(expected_uuid)
    store.mark_failed.assert_awaited_once()
    # erstes Argument des einzigen Calls muss die richtige UUID sein
    actual_uuid = store.mark_failed.call_args.args[0]
    assert actual_uuid == expected_uuid
    store.mark_done.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_marks_inflight_jobs_as_failed_in_db() -> None:
    """stop() muss PRINTING-Jobs per store.mark_failed(id, 'shutdown') in DB persistieren.

    Spec-Errata C2: Der In-Memory-Zustand wurde bereits vor diesem Fix korrekt
    auf FAILED gesetzt — aber der DB-Store-Aufruf fehlte (C-1 Fix).
    Dieser Test verifiziert dass stop() await self._store.mark_failed(UUID(job.id), 'shutdown')
    aufruft wenn ein Job beim Shutdown noch in PRINTING war.
    """
    import asyncio

    store = AsyncMock(spec=MemoryJobStore)
    # Recovery in start() konfigurieren — kein Absturz bei > 0-Vergleich
    store.mark_interrupted.return_value = 0
    store.list_pending.return_value = []

    # Printer der nie fertig wird — blockiert den Worker im print_image-Aufruf
    # bis der Test stop() aufruft und der Task gecancelled wird.
    printer = _make_printer()

    async def _blocking_print(*_args: object, **_kwargs: object) -> None:
        await asyncio.sleep(60)  # blockiert bis CancelledError via stop()

    printer.print_image = _blocking_print  # type: ignore[assignment]

    queue = PrintQueue(printers=[printer], store=store)
    await queue.start()

    job_id = await queue.submit(_PRINTER_ID, _sample_image(), tape_mm=12)

    # Kurz warten bis der Worker den Job in PRINTING übernommen hat.
    from app.services.job_lifecycle import JobState as InMemState

    for _ in range(50):
        job = await queue.get(job_id)
        if job.state == InMemState.PRINTING:
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("Job erreichte PRINTING-State nicht innerhalb der Wartezeit")

    # stop() soll den Worker cancellen und dann PRINTING→FAILED + mark_failed aufrufen.
    await queue.stop(timeout_s=0.1)

    # Verifizierung: mark_failed muss mit der richtigen UUID und
    # error='shutdown' aufgerufen worden sein.
    expected_uuid = UUID(job_id)
    # mark_failed kann mehrfach aufgerufen werden (einmal durch Worker-CancelledError-Pfad
    # und einmal durch stop()-Cleanup) — mindestens ein Call muss (uuid, 'shutdown') sein.
    shutdown_calls = [
        call
        for call in store.mark_failed.call_args_list
        if call.args == (expected_uuid, "shutdown")
    ]
    assert shutdown_calls, (
        f"store.mark_failed(UUID(job_id), 'shutdown') wurde nicht aufgerufen. "
        f"Tatsächliche Calls: {store.mark_failed.call_args_list}"
    )
