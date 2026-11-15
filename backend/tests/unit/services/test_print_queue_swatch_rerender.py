# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""A stored swatch job re-renders across and is turned for an ``along`` batch (#346, R-346-9)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from app.models.job import Job as DbJob
from app.printer_backends.mock_backend import MockPrinterBackend
from app.schemas.label_data import LabelData
from app.schemas.label_layout import LabelOrientation
from app.services.job_store import MemoryJobStore
from app.services.layout_engine import LayoutEngine
from app.services.print_queue import PrintQueue
from app.services.spool_swatch import render_tape_swatch
from PIL import Image

from tests.helpers.spool_swatch import SAMPLE_URL, every_row

_PRINTER = UUID("cccccccc-0000-0000-0000-000000000346")


class _QueuePrinter:
    def __init__(self, backend: MockPrinterBackend) -> None:
        self.id = _PRINTER
        self.backend = backend

    async def print_image(self, image: Image.Image, *, tape_mm: int, **options: Any) -> None:
        raw = options.get("orientation")
        await self.backend.print_image(
            image,
            SimpleNamespace(width_mm=tape_mm),  # type: ignore[arg-type]
            orientation=LabelOrientation(str(raw)) if raw else None,
        )

    async def print_images(
        self, images: list[Image.Image], *, tape_mm: int, **options: Any
    ) -> None:
        for image in images:
            await self.print_image(image, tape_mm=tape_mm, **options)


def _payload(orientation: str, tape_mm: int = 62) -> dict[str, Any]:
    label = LabelData(source_app="spoolman", qr_payload=SAMPLE_URL, swatch=every_row())
    return {
        "label_data": label.model_dump(),
        "content_type": "spool_swatch",
        "rendered_tape_mm": tape_mm,
        "tape_mm": tape_mm,
        "options": {"copies": 1, "auto_cut": True, "orientation": orientation},
    }


def _across() -> Image.Image:
    return render_tape_swatch(every_row(), SAMPLE_URL)


async def _printed(backend: MockPrinterBackend) -> None:
    for _ in range(500):
        if backend.printed_images:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("nothing printed")


async def _queue_with_row(orientation: str) -> tuple[PrintQueue, MockPrinterBackend, DbJob]:
    backend = MockPrinterBackend(loaded_tape_mm=62)
    store = MemoryJobStore()
    row = DbJob(id=uuid4(), printer_id=_PRINTER, payload=_payload(orientation))
    await store.save_queued(row)
    queue = PrintQueue([_QueuePrinter(backend)], store=store, engine=LayoutEngine())  # type: ignore[list-item]
    return queue, backend, row


async def test_recovered_along_batch_swatch_is_turned() -> None:
    queue, backend, _ = await _queue_with_row("along")
    await queue.start()  # recovery re-renders the stored row
    try:
        await _printed(backend)
        printed = backend.printed_images[-1]
        assert backend.printed_orientations[-1] is LabelOrientation.ALONG
        assert printed.tobytes() == _across().transpose(Image.Transpose.ROTATE_90).tobytes()
        assert printed.transpose(Image.Transpose.ROTATE_270).tobytes() == _across().tobytes()
    finally:
        await queue.stop()


async def test_retry_of_an_along_batch_swatch() -> None:
    backend = MockPrinterBackend(loaded_tape_mm=62)
    store = MemoryJobStore()
    queue = PrintQueue([_QueuePrinter(backend)], store=store, engine=LayoutEngine())  # type: ignore[list-item]
    await queue.start()
    try:
        row = DbJob(id=uuid4(), printer_id=_PRINTER, payload=_payload("along"))
        await store.save_queued(row)
        await queue.enqueue_persisted(row)
        await _printed(backend)
        assert backend.printed_orientations[-1] is LabelOrientation.ALONG
        printed = backend.printed_images[-1]
        assert printed.transpose(Image.Transpose.ROTATE_270).tobytes() == _across().tobytes()
    finally:
        await queue.stop()


async def test_recovered_single_swatch_is_across() -> None:
    queue, backend, _ = await _queue_with_row("across")
    await queue.start()
    try:
        await _printed(backend)
        assert backend.printed_orientations[-1] is LabelOrientation.ACROSS
        assert backend.printed_images[-1].tobytes() == _across().tobytes()
    finally:
        await queue.stop()


async def test_recovered_along_swatch_on_38mm_is_handed_as_rendered() -> None:
    backend = MockPrinterBackend(loaded_tape_mm=38)
    store = MemoryJobStore()
    row = DbJob(id=uuid4(), printer_id=_PRINTER, payload=_payload("along", 38))
    await store.save_queued(row)
    queue = PrintQueue([_QueuePrinter(backend)], store=store, engine=LayoutEngine())  # type: ignore[list-item]
    await queue.start()
    try:
        await _printed(backend)
        assert backend.printed_orientations[-1] is LabelOrientation.ALONG
        native = render_tape_swatch(every_row(), SAMPLE_URL, 38)
        assert backend.printed_images[-1].tobytes() == native.tobytes()
    finally:
        await queue.stop()
