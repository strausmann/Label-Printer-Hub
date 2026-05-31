from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from app.printer_backends.exceptions import (
    PrinterCoverOpenError,
    PrinterOfflineError,
    TapeEmptyError,
    TapeMismatchError,
)
from app.printer_backends.snmp_helper import PreflightStatus
from app.schemas.label_data import LabelData
from app.schemas.print_request import (
    PrintLookupRequest,
    PrintOptions,
    PrintRequest,
    RawLabelData,
)
from app.services.job_lifecycle import Job, JobState
from app.services.print_service import PrintService
from app.services.template_loader import TemplateNotFoundError
from PIL import Image


@pytest.fixture
def template():
    # Build a minimal TemplateSchema-compatible object — the actual schema
    # was created in Phase 4. Use the real schema if available, else a
    # MagicMock with .tape_mm attribute.
    tpl = MagicMock()
    tpl.tape_mm = 24
    tpl.id = "qr-only-24mm"
    return tpl


@pytest.fixture
def image():
    return Image.new("1", (200, 128))


@pytest.fixture
def loader(template):
    m = MagicMock()
    m.get.return_value = template
    return m


@pytest.fixture
def renderer(image):
    m = MagicMock()
    m.render.return_value = image
    return m


_FAKE_JOB_UUID = uuid4()


@pytest.fixture
def queue():
    m = AsyncMock()
    m.submit.return_value = "job-1"
    # Phase 2: submit_with_id und submit_paused_with_id werden jetzt genutzt
    m.submit_with_id.return_value = _FAKE_JOB_UUID
    m.submit_paused_with_id.return_value = _FAKE_JOB_UUID
    return m


@pytest.fixture
def lookup_service():
    m = AsyncMock()
    m.lookup.return_value = LabelData(
        title="X",
        primary_id="1",
        qr_payload="u",
        source_app="snipeit",
        secondary=(),
    )
    return m


@pytest.fixture
def backend():
    """Backend mock that reports 24mm tape loaded and printer idle (happy path)."""
    m = AsyncMock()
    m.preflight_check.return_value = PreflightStatus(
        hr_printer_status="idle",
        loaded_tape_mm=24,
        error_flags=[],
    )
    return m


_PRINTER_ID = UUID("bbbbbbbb-0000-0000-0000-000000000001")


def _service(loader, renderer, queue, lookup_service, backend):
    return PrintService(
        template_loader=loader,
        renderer=renderer,
        print_queue=queue,
        lookup_service=lookup_service,
        printer_id=_PRINTER_ID,
        backend=backend,
    )


# ---------------------------------------------------------------------------
# Existing happy-path tests — updated to pass backend fixture
# ---------------------------------------------------------------------------


async def test_lookup_path_calls_lookup_and_renders(
    loader,
    renderer,
    queue,
    lookup_service,
    backend,
) -> None:
    svc = _service(loader, renderer, queue, lookup_service, backend)
    req = PrintRequest(
        template_id="qr-only-24mm",
        lookup=PrintLookupRequest(app="snipeit", identifier="42"),
    )
    job_id = await svc.submit_print_job(req)
    lookup_service.lookup.assert_awaited_once_with("snipeit", "42")
    renderer.render.assert_called_once()
    # Phase 2: submit_print_job ruft submit_with_id statt submit
    queue.submit_with_id.assert_awaited_once()
    assert isinstance(job_id, UUID)


async def test_data_path_bypasses_lookup_and_marks_source_manual(
    loader,
    renderer,
    queue,
    lookup_service,
    backend,
) -> None:
    svc = _service(loader, renderer, queue, lookup_service, backend)
    req = PrintRequest(
        template_id="qr-only-24mm",
        data=RawLabelData(title="T", primary_id="P", qr_payload="Q", secondary=["a"]),
    )
    job_id = await svc.submit_print_job(req)
    lookup_service.lookup.assert_not_called()
    args, _ = renderer.render.call_args
    label_data = args[1]
    assert isinstance(label_data, LabelData)
    assert label_data.source_app == "manual"
    assert label_data.secondary == ("a",)
    # Phase 2: submit_print_job gibt UUID zurück
    assert isinstance(job_id, UUID)


async def test_template_not_found_raises_synchronously(
    loader,
    renderer,
    queue,
    lookup_service,
    backend,
) -> None:
    loader.get.side_effect = TemplateNotFoundError("qr-only-24mm")
    svc = _service(loader, renderer, queue, lookup_service, backend)
    req = PrintRequest(
        template_id="qr-only-24mm",
        lookup=PrintLookupRequest(app="snipeit", identifier="x"),
    )
    with pytest.raises(TemplateNotFoundError):
        await svc.submit_print_job(req)
    queue.submit.assert_not_called()
    # preflight must NOT be called when template is not found
    backend.preflight_check.assert_not_awaited()


async def test_options_passed_to_queue(loader, renderer, queue, lookup_service, backend) -> None:
    svc = _service(loader, renderer, queue, lookup_service, backend)
    req = PrintRequest(
        template_id="qr-only-24mm",
        data=RawLabelData(title="T", primary_id="P", qr_payload="Q"),
        options=PrintOptions(copies=2, auto_cut=False, high_resolution=True),
    )
    await svc.submit_print_job(req)
    # Phase 2: submit_with_id statt submit
    _, kwargs = queue.submit_with_id.call_args
    assert kwargs["tape_mm"] == 24
    assert kwargs["auto_cut"] is False
    assert kwargs["high_resolution"] is True
    # `copies` is deliberately NOT forwarded — see service comment
    assert "copies" not in kwargs


# ---------------------------------------------------------------------------
# Preflight: happy path (tape matches)
# ---------------------------------------------------------------------------


async def test_preflight_match_proceeds_normally(
    loader, renderer, queue, lookup_service, backend
) -> None:
    """When loaded tape matches template.tape_mm the job is submitted normally."""
    svc = _service(loader, renderer, queue, lookup_service, backend)
    req = PrintRequest(
        template_id="qr-only-24mm",
        data=RawLabelData(title="T", primary_id="P", qr_payload="Q"),
    )
    job_id = await svc.submit_print_job(req)
    assert isinstance(job_id, UUID)
    backend.preflight_check.assert_awaited_once()
    # Phase 2: submit_print_job ruft submit_with_id statt submit
    queue.submit_with_id.assert_awaited_once()


# ---------------------------------------------------------------------------
# Preflight: tape mismatch + fail (default)
# ---------------------------------------------------------------------------


async def test_preflight_mismatch_fail_raises_tape_mismatch(
    loader, renderer, queue, lookup_service, backend
) -> None:
    """on_tape_mismatch=fail (default) → TapeMismatchError raised, no job created."""
    backend.preflight_check.return_value = PreflightStatus(
        hr_printer_status="idle",
        loaded_tape_mm=12,
        error_flags=[],
    )
    svc = _service(loader, renderer, queue, lookup_service, backend)
    req = PrintRequest(
        template_id="qr-only-24mm",  # template wants 24mm, printer has 12mm
        data=RawLabelData(title="T", primary_id="P", qr_payload="Q"),
        on_tape_mismatch="fail",
    )
    with pytest.raises(TapeMismatchError) as exc_info:
        await svc.submit_print_job(req)
    assert exc_info.value.expected_mm == 24
    assert exc_info.value.loaded_mm == 12
    queue.submit.assert_not_called()


async def test_preflight_mismatch_default_is_fail(
    loader, renderer, queue, lookup_service, backend
) -> None:
    """on_tape_mismatch defaults to 'fail' when not specified."""
    backend.preflight_check.return_value = PreflightStatus(
        hr_printer_status="idle",
        loaded_tape_mm=12,
        error_flags=[],
    )
    svc = _service(loader, renderer, queue, lookup_service, backend)
    req = PrintRequest(
        template_id="qr-only-24mm",
        data=RawLabelData(title="T", primary_id="P", qr_payload="Q"),
        # no on_tape_mismatch — default is "fail"
    )
    with pytest.raises(TapeMismatchError):
        await svc.submit_print_job(req)
    queue.submit.assert_not_called()


# ---------------------------------------------------------------------------
# Preflight: tape mismatch + queue
# ---------------------------------------------------------------------------


async def test_preflight_mismatch_queue_creates_paused_job(
    loader, renderer, queue, lookup_service, backend
) -> None:
    """on_tape_mismatch=queue → job created via submit_paused() with PAUSED metadata."""
    backend.preflight_check.return_value = PreflightStatus(
        hr_printer_status="idle",
        loaded_tape_mm=12,
        error_flags=[],
    )
    # Phase 2: submit_paused_with_id statt submit_paused.
    # queue.get gibt ein in-memory Job-Objekt zurück auf das Metadaten gesetzt werden.
    job = Job(id="job-1", printer_id=_PRINTER_ID, image_payload=b"", tape_mm=24, options={})
    from app.services.job_lifecycle import JobStateMachine

    JobStateMachine.transition(job, JobState.PAUSED)
    queue.submit_paused_with_id.return_value = _FAKE_JOB_UUID
    queue.get.return_value = job
    svc = _service(loader, renderer, queue, lookup_service, backend)
    req = PrintRequest(
        template_id="qr-only-24mm",
        data=RawLabelData(title="T", primary_id="P", qr_payload="Q"),
        on_tape_mismatch="queue",
    )
    job_id = await svc.submit_print_job(req)
    assert isinstance(job_id, UUID)
    # Phase 2: submit_paused_with_id() wurde aufgerufen (nicht submit/submit_with_id)
    queue.submit_paused_with_id.assert_awaited_once()
    queue.submit_with_id.assert_not_awaited()
    queue.submit.assert_not_awaited()
    # tape-mismatch metadata attached after submit_paused_with_id
    assert job.state == JobState.PAUSED
    assert job.error_code == "tape_mismatch"
    assert job.error_message is not None
    assert job.error_detail == {"expected_mm": 24, "loaded_mm": 12}


async def test_preflight_mismatch_queue_none_tape_loaded(
    loader, renderer, queue, lookup_service, backend
) -> None:
    """on_tape_mismatch=queue with no tape loaded (loaded_tape_mm=None)."""
    backend.preflight_check.return_value = PreflightStatus(
        hr_printer_status="idle",
        loaded_tape_mm=None,
        error_flags=[],
    )
    job = Job(id="job-1", printer_id=_PRINTER_ID, image_payload=b"", tape_mm=24, options={})
    from app.services.job_lifecycle import JobStateMachine

    JobStateMachine.transition(job, JobState.PAUSED)
    queue.submit_paused_with_id.return_value = _FAKE_JOB_UUID
    queue.get.return_value = job
    svc = _service(loader, renderer, queue, lookup_service, backend)
    req = PrintRequest(
        template_id="qr-only-24mm",
        data=RawLabelData(title="T", primary_id="P", qr_payload="Q"),
        on_tape_mismatch="queue",
    )
    job_id = await svc.submit_print_job(req)
    assert isinstance(job_id, UUID)
    # Phase 2: submit_paused_with_id() aufgerufen
    queue.submit_paused_with_id.assert_awaited_once()
    assert job.state == JobState.PAUSED
    assert job.error_code == "tape_mismatch"
    assert job.error_detail == {"expected_mm": 24, "loaded_mm": None}


# ---------------------------------------------------------------------------
# Preflight: other printer errors — always synchronous regardless of on_tape_mismatch
# ---------------------------------------------------------------------------


async def test_preflight_offline_raises_synchronously(
    loader, renderer, queue, lookup_service, backend
) -> None:
    """PrinterOfflineError from preflight propagates synchronously."""
    backend.preflight_check.side_effect = PrinterOfflineError("host unreachable")
    svc = _service(loader, renderer, queue, lookup_service, backend)
    req = PrintRequest(
        template_id="qr-only-24mm",
        data=RawLabelData(title="T", primary_id="P", qr_payload="Q"),
        on_tape_mismatch="queue",  # even with queue, offline is always synchronous
    )
    with pytest.raises(PrinterOfflineError):
        await svc.submit_print_job(req)
    queue.submit.assert_not_called()


async def test_preflight_tape_empty_raises_synchronously(
    loader, renderer, queue, lookup_service, backend
) -> None:
    """TapeEmptyError from preflight propagates synchronously."""
    backend.preflight_check.side_effect = TapeEmptyError()
    svc = _service(loader, renderer, queue, lookup_service, backend)
    req = PrintRequest(
        template_id="qr-only-24mm",
        data=RawLabelData(title="T", primary_id="P", qr_payload="Q"),
    )
    with pytest.raises(TapeEmptyError):
        await svc.submit_print_job(req)
    queue.submit.assert_not_called()


async def test_preflight_cover_open_raises_synchronously(
    loader, renderer, queue, lookup_service, backend
) -> None:
    """PrinterCoverOpenError from preflight propagates synchronously."""
    backend.preflight_check.side_effect = PrinterCoverOpenError()
    svc = _service(loader, renderer, queue, lookup_service, backend)
    req = PrintRequest(
        template_id="qr-only-24mm",
        data=RawLabelData(title="T", primary_id="P", qr_payload="Q"),
    )
    with pytest.raises(PrinterCoverOpenError):
        await svc.submit_print_job(req)
    queue.submit.assert_not_called()


# ---------------------------------------------------------------------------
# Race-condition fix: submit_paused() atomic path (Commit A — Issue #67)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tape_mismatch_queue_job_never_enters_asyncio_queue() -> None:
    """Prove the atomic path: submit_paused() MUST NOT place the job in the
    asyncio.Queue — the job must be stored only in the paused-jobs registry.

    We verify this by inspecting the real PrintQueue's asyncio.Queue size
    immediately after submit_print_job returns. If the fix uses submit_paused()
    correctly, the queue is empty (qsize() == 0). If the old race-prone code
    path is used (submit() then transition PAUSED), the queue has one item
    (qsize() == 1) which the worker could pick up before the PAUSED transition
    completes.
    """

    from uuid import UUID as _UUID

    from unittest.mock import AsyncMock, MagicMock

    from app.printer_backends.snmp_helper import PreflightStatus
    from app.services.print_queue import PrintQueue
    from app.services.print_service import PrintService
    from PIL import Image as _Image

    _RACE_PRINTER_ID = _UUID("aaaaaaaa-0000-0000-0000-000000000001")

    class _NeverPrint:
        """Printer that must never be called in this test."""

        id = _RACE_PRINTER_ID

        async def print_image(self, image, *, tape_mm, **kw):
            raise AssertionError("Worker dequeued the paused job — race is present!")

    real_queue = PrintQueue([_NeverPrint()])
    # Do NOT start the worker — we're testing the submit side only.
    # The asyncio.Queue size directly reveals whether the job was enqueued.

    tpl = MagicMock()
    tpl.tape_mm = 24
    tpl.id = "race-tpl"
    loader = MagicMock()
    loader.get.return_value = tpl

    renderer = MagicMock()
    renderer.render.return_value = _Image.new("1", (200, 128))

    backend = AsyncMock()
    backend.preflight_check.return_value = PreflightStatus(
        hr_printer_status="idle",
        loaded_tape_mm=12,  # mismatch: template wants 24mm
        error_flags=[],
    )

    svc = PrintService(
        template_loader=loader,
        renderer=renderer,
        print_queue=real_queue,
        lookup_service=AsyncMock(),
        printer_id=_RACE_PRINTER_ID,
        backend=backend,
    )

    req = PrintRequest(
        template_id="race-tpl",
        data=RawLabelData(title="T", primary_id="P", qr_payload="Q"),
        on_tape_mismatch="queue",
    )

    job_id = await svc.submit_print_job(req)

    # The asyncio.Queue MUST be empty — job was submitted in PAUSED state,
    # not enqueued. If this fails, the race-prone code path is still active.
    # Phase 2: Printer-Key ist jetzt UUID, nicht "pt@race".
    queue_size = real_queue._queues[_RACE_PRINTER_ID].qsize()
    assert queue_size == 0, (
        f"Job was placed in asyncio.Queue (qsize={queue_size}) — "
        "race-prone submit+pause path still active, fix not applied!"
    )

    job = await real_queue.get(job_id)
    from app.services.job_lifecycle import JobState

    assert job.state == JobState.PAUSED, f"Expected PAUSED, got {job.state}"
    assert job.error_code == "tape_mismatch"
    assert job.error_detail == {"expected_mm": 24, "loaded_mm": 12}
