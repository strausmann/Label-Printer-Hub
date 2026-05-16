from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

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


@pytest.fixture
def queue():
    m = AsyncMock()
    m.submit.return_value = "job-1"
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


def _service(loader, renderer, queue, lookup_service, backend):
    return PrintService(
        template_loader=loader,
        renderer=renderer,
        print_queue=queue,
        lookup_service=lookup_service,
        printer_id="pt@x",
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
    queue.submit.assert_awaited_once()
    assert job_id == "job-1"


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
    assert job_id == "job-1"


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
    _, kwargs = queue.submit.call_args
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
    assert job_id == "job-1"
    backend.preflight_check.assert_awaited_once()
    queue.submit.assert_awaited_once()


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
    """on_tape_mismatch=queue → job created, immediately transitioned to PAUSED."""
    backend.preflight_check.return_value = PreflightStatus(
        hr_printer_status="idle",
        loaded_tape_mm=12,
        error_flags=[],
    )
    # queue.get must return a Job we can mutate
    job = Job(id="job-1", printer_id="pt@x", image_payload=b"", tape_mm=24, options={})
    queue.get.return_value = job
    svc = _service(loader, renderer, queue, lookup_service, backend)
    req = PrintRequest(
        template_id="qr-only-24mm",
        data=RawLabelData(title="T", primary_id="P", qr_payload="Q"),
        on_tape_mismatch="queue",
    )
    job_id = await svc.submit_print_job(req)
    assert job_id == "job-1"
    # Job was submitted to the queue
    queue.submit.assert_awaited_once()
    # Job is now PAUSED with tape-mismatch metadata
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
    job = Job(id="job-1", printer_id="pt@x", image_payload=b"", tape_mm=24, options={})
    queue.get.return_value = job
    svc = _service(loader, renderer, queue, lookup_service, backend)
    req = PrintRequest(
        template_id="qr-only-24mm",
        data=RawLabelData(title="T", primary_id="P", qr_payload="Q"),
        on_tape_mismatch="queue",
    )
    job_id = await svc.submit_print_job(req)
    assert job_id == "job-1"
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
