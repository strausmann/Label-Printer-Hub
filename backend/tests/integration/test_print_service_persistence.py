"""PrintService muss Job-Row in DB anlegen BEVOR an PrintQueue übergeben wird.

Task 5 — Phase 2 Job Persistence.

Fixtures erstellen PrintService + SQLiteJobStore + PrintQueue mit echtem DB-Backend.
async_session_factory kommt aus tests/conftest.py (sichtbar für alle Tests).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from app.models.job import JobState
from app.printer_backends.snmp_helper import PreflightStatus
from app.schemas.label_data import LabelData
from app.schemas.print_request import PrintRequest, RawLabelData
from app.services.job_store_sqlite import SQLiteJobStore
from app.services.print_queue import PrintQueue
from app.services.print_service import PrintService
from PIL import Image


class _FakePrinter:
    """Fake Drucker-Objekt das nie wirklich druckt."""

    def __init__(self, printer_id):
        self.id = printer_id

    async def print_image(self, image, *, tape_mm, **options):
        pass  # kein wirklicher Druck im Test


@pytest_asyncio.fixture
async def sqlite_store(async_session_factory):
    """SQLiteJobStore gegen per-Test SQLite DB."""
    return SQLiteJobStore(async_session_factory)


@pytest_asyncio.fixture
async def print_queue(sqlite_store):
    """PrintQueue mit SQLiteJobStore aber OHNE Workers (nicht gestartet)."""
    printer_id = uuid4()
    fake_printer = _FakePrinter(printer_id)
    queue = PrintQueue(
        printers=[fake_printer],
        store=sqlite_store,
    )
    yield queue, printer_id
    # Workers nicht gestartet, kein stop() nötig


@pytest_asyncio.fixture
def backend_mock():
    """Backend-Mock der 24mm Tape meldet und IDLE ist."""
    m = AsyncMock()
    m.preflight_check.return_value = PreflightStatus(
        hr_printer_status="idle",
        loaded_tape_mm=24,
        error_flags=[],
    )
    return m


@pytest_asyncio.fixture
def sample_request():
    """Minimaler PrintRequest mit direktem LabelData."""
    return PrintRequest(
        template_id="test-label-24mm",
        data=RawLabelData(
            title="Regal A-01",
            primary_id="SHF-001",
            qr_payload="https://example.com/shelf/001",
        ),
    )


@pytest_asyncio.fixture
async def print_service(print_queue, sqlite_store, backend_mock):
    """PrintService mit SQLiteJobStore + submit_with_id-fähiger PrintQueue.

    template_loader und renderer sind Mocks; die eigentliche Render-Logik
    wird nicht getestet — nur dass save_queued() VOR queue-Submit aufgerufen wird.
    """
    queue_obj, printer_id = print_queue

    template = MagicMock()
    template.tape_mm = 24
    template.id = "test-label-24mm"

    loader = MagicMock()
    loader.get.return_value = template

    renderer = MagicMock()
    renderer.render.return_value = Image.new("1", (200, 128))

    lookup_service = AsyncMock()
    lookup_service.lookup.return_value = LabelData(
        title="X",
        primary_id="1",
        qr_payload="u",
        source_app="manual",
        secondary=(),
    )

    svc = PrintService(
        template_loader=loader,
        renderer=renderer,
        print_queue=queue_obj,
        lookup_service=lookup_service,
        printer_id=printer_id,
        backend=backend_mock,
        store=sqlite_store,
    )
    return svc, sqlite_store, printer_id


@pytest.mark.asyncio
async def test_submit_persists_queued_job_before_queue(
    print_service,
    sample_request,
):
    """Nach submit_print_job muss der Job in DB als QUEUED existieren."""
    svc, sqlite_store, _printer_id = print_service

    job_id = await svc.submit_print_job(sample_request)

    # Job muss in DB persistiert sein
    persisted = await sqlite_store.get(job_id)
    assert persisted is not None, "Job nicht in DB gefunden nach submit_print_job"
    assert persisted.state == JobState.QUEUED.value
    assert persisted.template_key == sample_request.template_id
    assert persisted.printer_id == _printer_id


@pytest.mark.asyncio
async def test_submit_returns_uuid_not_string(
    print_service,
    sample_request,
):
    """submit_print_job muss eine UUID zurückgeben (nicht str)."""
    from uuid import UUID

    svc, _store, _printer_id = print_service
    job_id = await svc.submit_print_job(sample_request)
    assert isinstance(job_id, UUID), f"Erwartet UUID, erhalten: {type(job_id)}"
