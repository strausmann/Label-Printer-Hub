"""PrintQueue muss store.mark_* bei jeder State-Transition aufrufen.

Tests verwenden die echte PrintQueue-Signatur:
    PrintQueue(printers=[...], on_state_change=None, store=store)

Der Worker bridget dataclass-Job.id (str) via UUID(job.id) an den Store.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from PIL import Image

from app.services.job_store import MemoryJobStore
from app.services.print_queue import PrintQueue

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
