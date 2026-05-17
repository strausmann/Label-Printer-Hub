from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from app.api.routes.print import router
from app.printer_backends.exceptions import SnmpQueryError
from app.printer_backends.snmp_helper import LiveStatus
from app.services.job_lifecycle import Job, JobState
from app.services.lookup_service import LookupFailedError
from app.services.template_loader import TemplateNotFoundError
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_print, require_read
from fastapi import FastAPI
from uuid import uuid4 as _uuid4
from httpx import ASGITransport, AsyncClient

_PRINTER_ID = UUID("dddddddd-0000-0000-0000-000000000001")
_PRINTER_ID_STR = str(_PRINTER_ID)


@pytest.fixture
def fake_service():
    m = AsyncMock()
    m.submit_print_job.return_value = "job-1"
    return m


@pytest.fixture
def fake_queue():
    return MagicMock()


def _app(service, queue):
    app = FastAPI()
    app.state.print_service = service
    app.state.print_queue = queue
    app.include_router(router)
    _fake_ctx = AuthContext(source="api-key", scope="admin", api_key_id=_uuid4(), ip="127.0.0.1")
    for _dep in (require_read, require_print):
        app.dependency_overrides[_dep] = lambda _c=_fake_ctx: _c
    return app


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def test_post_print_data_path_returns_202(fake_service, fake_queue) -> None:
    async with _client(_app(fake_service, fake_queue)) as c:
        r = await c.post(
            "/print",
            json={
                "template_id": "t",
                "data": {"title": "X", "primary_id": "1", "qr_payload": "u"},
            },
        )
    assert r.status_code == 202
    body = r.json()
    assert body == {"job_id": "job-1", "status": "queued"}


async def test_post_print_lookup_path_returns_202(fake_service, fake_queue) -> None:
    async with _client(_app(fake_service, fake_queue)) as c:
        r = await c.post(
            "/print",
            json={
                "template_id": "t",
                "lookup": {"app": "snipeit", "identifier": "42"},
            },
        )
    assert r.status_code == 202


async def test_post_print_neither_source_is_422(fake_service, fake_queue) -> None:
    async with _client(_app(fake_service, fake_queue)) as c:
        r = await c.post("/print", json={"template_id": "t"})
    assert r.status_code == 422


async def test_post_print_template_not_found_is_404(fake_service, fake_queue) -> None:
    fake_service.submit_print_job.side_effect = TemplateNotFoundError("missing")
    async with _client(_app(fake_service, fake_queue)) as c:
        r = await c.post(
            "/print",
            json={
                "template_id": "missing",
                "data": {"title": "X", "primary_id": "1", "qr_payload": "u"},
            },
        )
    assert r.status_code == 404
    assert r.json()["error_code"] == "template_not_found"


async def test_post_print_lookup_failed_is_502(fake_service, fake_queue) -> None:
    fake_service.submit_print_job.side_effect = LookupFailedError("upstream down")
    async with _client(_app(fake_service, fake_queue)) as c:
        r = await c.post(
            "/print",
            json={
                "template_id": "t",
                "lookup": {"app": "snipeit", "identifier": "x"},
            },
        )
    assert r.status_code == 502
    assert r.json()["error_code"] == "integration_lookup_failed"


async def test_get_jobs_returns_status_with_live_block(
    fake_service, fake_queue, monkeypatch
) -> None:
    job = Job(id="job-1", printer_id=_PRINTER_ID, image_payload=b"", tape_mm=24, options={})
    job.state = JobState.PRINTING
    job.submitted_at = datetime.now(UTC)
    fake_queue.get = AsyncMock(return_value=job)

    async def fake_live(host: str, *, community: str = "public", timeout_s: float = 3.0):
        return LiveStatus(hr_printer_status="printing", error_flags=[])

    monkeypatch.setattr("app.api.routes.print.query_live_status", fake_live)

    app = _app(fake_service, fake_queue)
    app.state.printer_host = "192.0.2.10"
    app.state.printer_snmp_community = "public"
    async with _client(app) as c:
        r = await c.get("/jobs/job-1")
    assert r.status_code == 200
    body = r.json()
    assert body["job_id"] == "job-1"
    assert body["status"] == "printing"
    assert body["live"] == {"hr_printer_status": "printing", "error_flags": []}


async def test_get_jobs_no_live_block_when_not_printing(fake_service, fake_queue) -> None:
    job = Job(id="job-1", printer_id=_PRINTER_ID, image_payload=b"", tape_mm=24, options={})
    job.state = JobState.COMPLETED
    job.submitted_at = datetime.now(UTC)
    fake_queue.get = AsyncMock(return_value=job)
    async with _client(_app(fake_service, fake_queue)) as c:
        r = await c.get("/jobs/job-1")
    assert r.status_code == 200
    assert r.json()["live"] is None


async def test_get_jobs_live_snmp_failure_is_non_fatal(
    fake_service, fake_queue, monkeypatch
) -> None:
    job = Job(id="job-1", printer_id=_PRINTER_ID, image_payload=b"", tape_mm=24, options={})
    job.state = JobState.PRINTING
    job.submitted_at = datetime.now(UTC)
    fake_queue.get = AsyncMock(return_value=job)

    async def fake_live(*_a, **_kw):
        raise SnmpQueryError("timed out")

    monkeypatch.setattr("app.api.routes.print.query_live_status", fake_live)

    app = _app(fake_service, fake_queue)
    app.state.printer_host = "192.0.2.10"
    app.state.printer_snmp_community = "public"
    async with _client(app) as c:
        r = await c.get("/jobs/job-1")
    assert r.status_code == 200
    assert r.json()["live"] is None


async def test_get_jobs_unknown_is_404(fake_service, fake_queue) -> None:
    fake_queue.get = AsyncMock(side_effect=KeyError("nope"))
    async with _client(_app(fake_service, fake_queue)) as c:
        r = await c.get("/jobs/does-not-exist")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /print — new synchronous error types
# ---------------------------------------------------------------------------


async def test_post_print_tape_mismatch_fail_is_409_with_detail(fake_service, fake_queue) -> None:
    from app.printer_backends.exceptions import TapeMismatchError

    fake_service.submit_print_job.side_effect = TapeMismatchError(expected_mm=24, loaded_mm=12)
    async with _client(_app(fake_service, fake_queue)) as c:
        r = await c.post(
            "/print",
            json={
                "template_id": "t",
                "data": {"title": "X", "primary_id": "1", "qr_payload": "u"},
            },
        )
    assert r.status_code == 409
    body = r.json()
    assert body["error_code"] == "tape_mismatch"
    assert body["error_detail"] == {"expected_mm": 24, "loaded_mm": 12}


async def test_post_print_tape_mismatch_no_tape_loaded(fake_service, fake_queue) -> None:
    from app.printer_backends.exceptions import TapeMismatchError

    fake_service.submit_print_job.side_effect = TapeMismatchError(expected_mm=24, loaded_mm=None)
    async with _client(_app(fake_service, fake_queue)) as c:
        r = await c.post(
            "/print",
            json={
                "template_id": "t",
                "data": {"title": "X", "primary_id": "1", "qr_payload": "u"},
            },
        )
    assert r.status_code == 409
    body = r.json()
    assert body["error_code"] == "tape_mismatch"
    assert body["error_detail"] == {"expected_mm": 24, "loaded_mm": None}


async def test_post_print_printer_offline_is_503(fake_service, fake_queue) -> None:
    from app.printer_backends.exceptions import PrinterOfflineError

    fake_service.submit_print_job.side_effect = PrinterOfflineError("host unreachable")
    async with _client(_app(fake_service, fake_queue)) as c:
        r = await c.post(
            "/print",
            json={
                "template_id": "t",
                "data": {"title": "X", "primary_id": "1", "qr_payload": "u"},
            },
        )
    assert r.status_code == 503
    assert r.json()["error_code"] == "printer_offline"


async def test_post_print_tape_empty_is_409(fake_service, fake_queue) -> None:
    from app.printer_backends.exceptions import TapeEmptyError

    fake_service.submit_print_job.side_effect = TapeEmptyError()
    async with _client(_app(fake_service, fake_queue)) as c:
        r = await c.post(
            "/print",
            json={
                "template_id": "t",
                "data": {"title": "X", "primary_id": "1", "qr_payload": "u"},
            },
        )
    assert r.status_code == 409
    assert r.json()["error_code"] == "tape_empty"


async def test_post_print_cover_open_is_409(fake_service, fake_queue) -> None:
    from app.printer_backends.exceptions import PrinterCoverOpenError

    fake_service.submit_print_job.side_effect = PrinterCoverOpenError()
    async with _client(_app(fake_service, fake_queue)) as c:
        r = await c.post(
            "/print",
            json={
                "template_id": "t",
                "data": {"title": "X", "primary_id": "1", "qr_payload": "u"},
            },
        )
    assert r.status_code == 409
    assert r.json()["error_code"] == "printer_cover_open"


# ---------------------------------------------------------------------------
# POST /printer/resume
# ---------------------------------------------------------------------------


async def test_resume_printer_endpoint(fake_service, fake_queue) -> None:
    fake_queue.resume_printer = AsyncMock(return_value=None)
    app = _app(fake_service, fake_queue)
    app.state.printer_id = _PRINTER_ID
    async with _client(app) as c:
        r = await c.post("/printer/resume")
    assert r.status_code == 200
    body = r.json()
    assert body == {"printer_id": _PRINTER_ID_STR, "state": "active"}
    fake_queue.resume_printer.assert_awaited_once_with(_PRINTER_ID)


async def test_resume_printer_404_when_no_printer_configured(fake_service, fake_queue) -> None:
    app = _app(fake_service, fake_queue)
    # NOT setting app.state.printer_id
    async with _client(app) as c:
        r = await c.post("/printer/resume")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /jobs/{job_id}/resume
# ---------------------------------------------------------------------------


async def test_resume_job_transitions_paused_to_queued(fake_service, fake_queue) -> None:
    """Resume a PAUSED job → 200 with state=queued and cleared error metadata."""
    job = Job(id="job-1", printer_id=_PRINTER_ID, image_payload=b"", tape_mm=24, options={})
    # Manually set PAUSED state (as PrintService would after tape mismatch+queue)
    from app.services.job_lifecycle import JobStateMachine

    JobStateMachine.transition(job, JobState.PAUSED)
    job.error_code = "tape_mismatch"
    job.error_message = "Expected 24mm tape, loaded 12mm"
    job.error_detail = {"expected_mm": 24, "loaded_mm": 12}
    job.submitted_at = datetime.now(UTC)

    fake_queue.get = AsyncMock(return_value=job)
    fake_queue.resume_job = AsyncMock(side_effect=lambda job_id: _resume_side_effect(job))

    async with _client(_app(fake_service, fake_queue)) as c:
        r = await c.post("/jobs/job-1/resume")

    assert r.status_code == 200
    body = r.json()
    assert body["job_id"] == "job-1"
    assert body["status"] == "queued"
    assert body["error_code"] is None
    assert body["error_message"] is None
    assert body["error_detail"] is None


def _resume_side_effect(job: Job) -> None:
    """Simulate PrintQueue.resume_job transitioning PAUSED → QUEUED."""
    from app.services.job_lifecycle import JobStateMachine

    JobStateMachine.transition(job, JobState.QUEUED)


async def test_resume_job_unknown_is_404(fake_service, fake_queue) -> None:
    """Resuming an unknown job returns 404."""
    fake_queue.get = AsyncMock(side_effect=KeyError("nope"))

    async with _client(_app(fake_service, fake_queue)) as c:
        r = await c.post("/jobs/does-not-exist/resume")

    assert r.status_code == 404


async def test_resume_job_completed_is_409(fake_service, fake_queue) -> None:
    """Resuming a COMPLETED job returns 409."""
    from app.services.job_lifecycle import JobStateMachine

    job = Job(id="job-1", printer_id=_PRINTER_ID, image_payload=b"", tape_mm=24, options={})
    # Transition to COMPLETED via PRINTING
    JobStateMachine.transition(job, JobState.PRINTING)
    JobStateMachine.transition(job, JobState.COMPLETED)
    job.submitted_at = datetime.now(UTC)
    fake_queue.get = AsyncMock(return_value=job)

    async with _client(_app(fake_service, fake_queue)) as c:
        r = await c.post("/jobs/job-1/resume")

    assert r.status_code == 409


# ---------------------------------------------------------------------------
# POST /printer/resume — 409 contract (Commit B — Issue #67)
# ---------------------------------------------------------------------------


async def test_resume_printer_already_active_returns_409(fake_service, fake_queue) -> None:
    """Calling resume_printer when the printer is already ACTIVE must return 409
    with error_code='already_active' — the documented contract that was missing.
    """
    from app.services.print_queue import PrinterAlreadyActiveError

    fake_queue.resume_printer = AsyncMock(side_effect=PrinterAlreadyActiveError(_PRINTER_ID))
    app = _app(fake_service, fake_queue)
    app.state.printer_id = _PRINTER_ID
    async with _client(app) as c:
        r = await c.post("/printer/resume")
    assert r.status_code == 409
    body = r.json()
    assert body.get("error_code") == "already_active"


async def test_resume_printer_paused_returns_200(fake_service, fake_queue) -> None:
    """Calling resume_printer on a PAUSED printer must still return 200 (control)."""
    fake_queue.resume_printer = AsyncMock(return_value=None)
    app = _app(fake_service, fake_queue)
    app.state.printer_id = _PRINTER_ID
    async with _client(app) as c:
        r = await c.post("/printer/resume")
    assert r.status_code == 200
    assert r.json() == {"printer_id": _PRINTER_ID_STR, "state": "active"}


# ---------------------------------------------------------------------------
# POST /jobs/{job_id}/resume — structured error_code (Commit B — Issue #67)
# ---------------------------------------------------------------------------


async def test_resume_job_not_paused_returns_409_with_error_code(fake_service, fake_queue) -> None:
    """When resuming a non-PAUSED job the response must include
    error_code='invalid_state' (structured ProblemDetail, not a plain detail string).
    """
    job = Job(id="job-1", printer_id=_PRINTER_ID, image_payload=b"", tape_mm=24, options={})
    # job.state is QUEUED by default — not PAUSED
    job.submitted_at = datetime.now(UTC)
    fake_queue.get = AsyncMock(return_value=job)

    async with _client(_app(fake_service, fake_queue)) as c:
        r = await c.post("/jobs/job-1/resume")

    assert r.status_code == 409
    body = r.json()
    assert body.get("error_code") == "invalid_state", (
        f"Expected error_code='invalid_state', got: {body}"
    )
