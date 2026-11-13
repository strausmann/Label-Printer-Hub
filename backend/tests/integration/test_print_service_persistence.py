"""PrintService muss Job-Row in DB anlegen BEVOR an PrintQueue übergeben wird.

Phase 1k.1a (Task 25): Adapted from template_id/renderer/template_loader API
to content_type/LayoutEngine API.

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
from app.schemas.content_type import ContentType
from app.schemas.print_request import PrintRequest, RawLabelData
from app.services.job_store_sqlite import SQLiteJobStore
from app.services.layout_engine import LayoutEngine
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
    """Minimaler PrintRequest mit ContentType und direktem LabelData."""
    return PrintRequest(
        content_type=ContentType.QR_TWO_LINES,
        data=RawLabelData(
            title="Regal A-01",
            primary_id="SHF-001",
            qr_payload="https://example.com/shelf/001",
        ),
    )


@pytest_asyncio.fixture
async def print_service(print_queue, sqlite_store, backend_mock):
    """PrintService mit SQLiteJobStore + submit_with_id-fähiger PrintQueue.

    LayoutEngine ist ein Mock; die eigentliche Render-Logik
    wird nicht getestet — nur dass save_queued() VOR queue-Submit aufgerufen wird.
    """
    queue_obj, printer_id = print_queue

    engine_mock = MagicMock(spec=LayoutEngine)
    engine_mock.render.return_value = Image.new("1", (200, 128))

    svc = PrintService(
        printer_id=printer_id,
        backend=backend_mock,
        queue=queue_obj,
        store=sqlite_store,
        engine=engine_mock,
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
    assert persisted.template_key is None  # Phase 1k.1a: template_key immer None
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


@pytest.mark.asyncio
async def test_submit_records_the_submitting_key_and_address(print_service, sample_request):
    """#294: a tape job belongs to the key that submitted it; the row says which one."""
    svc, sqlite_store, _printer_id = print_service
    key_id = uuid4()

    job_id = await svc.submit_print_job(sample_request, api_key_id=key_id, source_ip="192.0.2.7")

    persisted = await sqlite_store.get(job_id)
    assert persisted is not None
    assert persisted.api_key_id == key_id
    assert persisted.source_ip == "192.0.2.7"


@pytest.mark.asyncio
async def test_submit_without_a_key_stores_no_owner(print_service, sample_request):
    svc, sqlite_store, _printer_id = print_service
    job_id = await svc.submit_print_job(sample_request)
    persisted = await sqlite_store.get(job_id)
    assert persisted is not None and persisted.api_key_id is None


@pytest.mark.asyncio
async def test_test_label_records_the_submitting_key(print_service):
    svc, sqlite_store, _printer_id = print_service
    key_id = uuid4()

    job_id = await svc.submit_test_label(
        lambda _mm: RawLabelData(title="T", primary_id="1", qr_payload="https://e.invalid/t"),
        api_key_id=key_id,
        source_ip="192.0.2.8",
    )

    persisted = await sqlite_store.get(job_id)
    assert persisted is not None
    assert (persisted.api_key_id, persisted.source_ip) == (key_id, "192.0.2.8")


@pytest.mark.asyncio
async def test_batch_records_the_submitting_key_on_every_row(print_service, sample_request):
    svc, sqlite_store, _printer_id = print_service
    key_id = uuid4()

    job_ids = await svc.submit_batch_job(
        [sample_request, sample_request],
        half_cut=False,
        api_key_id=key_id,
        source_ip="192.0.2.9",
    )

    assert len(job_ids) == 2
    for job_id in job_ids:
        persisted = await sqlite_store.get(job_id)
        assert persisted is not None
        assert (persisted.api_key_id, persisted.source_ip) == (key_id, "192.0.2.9")
