"""Unit tests for app.api.routes.print.

Phase 1k.1a (Task 25): TemplateNotFoundError and template_loader removed.
Tests using old template_id-based API (POST /api/v1/print with template_id) adapted to
content_type-based API. test_post_print_template_not_found_is_404 removed.
The tests for the legacy job routes (GET /jobs/{id}, POST /jobs/{id}/resume) went with them.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID
from uuid import uuid4 as _uuid4

import pytest
from app.api.routes.print import router
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_print, require_read
from app.db.session import get_session
from app.printer_backends.exceptions import PrinterOfflineError
from app.services.lookup_service import LookupFailedError, UnknownAppError
from fastapi import FastAPI
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

    async def _fake_session():  # legacy resume also clears the DB pause flag
        s = MagicMock()
        s.get = AsyncMock()
        s.commit = AsyncMock()
        yield s

    app.dependency_overrides[get_session] = _fake_session
    _fake_ctx = AuthContext(source="api-key", scope="admin", api_key_id=_uuid4(), ip="127.0.0.1")
    for _dep in (require_read, require_print):
        app.dependency_overrides[_dep] = lambda _c=_fake_ctx: _c
    return app


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


# ---------------------------------------------------------------------------
# POST /api/v1/print — content_type-based API (Phase 1k.1a)
# ---------------------------------------------------------------------------


async def test_post_print_data_path_returns_202(fake_service, fake_queue) -> None:
    async with _client(_app(fake_service, fake_queue)) as c:
        r = await c.post(
            "/api/v1/print",
            json={
                "content_type": "qr_two_lines",
                "data": {"title": "X", "primary_id": "1", "qr_payload": "u"},
            },
        )
    assert r.status_code == 202
    body = r.json()
    assert body == {"job_id": "job-1", "status": "queued"}


async def test_post_print_lookup_path_returns_202(fake_service, fake_queue) -> None:
    async with _client(_app(fake_service, fake_queue)) as c:
        r = await c.post(
            "/api/v1/print",
            json={
                "content_type": "qr_two_lines",
                "lookup": {"app": "snipeit", "identifier": "42"},
            },
        )
    assert r.status_code == 202


async def test_post_print_neither_source_is_422(fake_service, fake_queue) -> None:
    async with _client(_app(fake_service, fake_queue)) as c:
        r = await c.post("/api/v1/print", json={"content_type": "qr_two_lines"})
    assert r.status_code == 422


async def test_post_print_lookup_failed_is_502(fake_service, fake_queue) -> None:
    fake_service.submit_print_job.side_effect = LookupFailedError("upstream down")
    async with _client(_app(fake_service, fake_queue)) as c:
        r = await c.post(
            "/api/v1/print",
            json={
                "content_type": "qr_two_lines",
                "lookup": {"app": "snipeit", "identifier": "x"},
            },
        )
    assert r.status_code == 502
    assert r.json()["error_code"] == "integration_lookup_failed"


_LOOKUP_BODY = {"content_type": "qr_two_lines", "lookup": {"app": "snipeit", "identifier": "x"}}


async def test_post_print_unknown_app_is_422_not_a_crash(fake_service, fake_queue) -> None:
    fake_service.submit_print_job.side_effect = UnknownAppError(
        "Unknown integration. Registered: [a, b]"
    )
    async with _client(_app(fake_service, fake_queue)) as c:
        r = await c.post("/api/v1/print", json=_LOOKUP_BODY)
    assert r.status_code == 422
    assert r.json()["error_code"] == "integration_unknown_app"
    assert "Registered" not in r.text


async def test_post_print_lookup_failure_text_stays_server_side(fake_service, fake_queue) -> None:
    fake_service.submit_print_job.side_effect = LookupFailedError(
        "GET https://up.example.invalid/?token=s3cret"
    )
    async with _client(_app(fake_service, fake_queue)) as c:
        r = await c.post("/api/v1/print", json=_LOOKUP_BODY)
    assert r.status_code == 502
    assert "s3cret" not in r.text and "example.invalid" not in r.text


async def test_post_print_subclass_of_a_mapped_error_uses_its_parents_mapping(
    fake_service, fake_queue
) -> None:
    class _DownError(PrinterOfflineError):
        pass

    fake_service.submit_print_job.side_effect = _DownError("offline")
    async with _client(_app(fake_service, fake_queue)) as c:
        r = await c.post("/api/v1/print", json=_LOOKUP_BODY)
    assert r.status_code == 503
    assert r.json()["error_code"] == "printer_offline"


# ---------------------------------------------------------------------------
# POST /api/v1/print — new synchronous error types
# ---------------------------------------------------------------------------


async def test_post_print_tape_mismatch_fail_is_409_with_detail(fake_service, fake_queue) -> None:
    from app.printer_backends.exceptions import TapeMismatchError

    fake_service.submit_print_job.side_effect = TapeMismatchError(expected_mm=24, loaded_mm=12)
    async with _client(_app(fake_service, fake_queue)) as c:
        r = await c.post(
            "/api/v1/print",
            json={
                "content_type": "qr_two_lines",
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
            "/api/v1/print",
            json={
                "content_type": "qr_two_lines",
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
            "/api/v1/print",
            json={
                "content_type": "qr_two_lines",
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
            "/api/v1/print",
            json={
                "content_type": "qr_two_lines",
                "data": {"title": "X", "primary_id": "1", "qr_payload": "u"},
            },
        )
    assert r.status_code == 409
    assert r.json()["error_code"] == "tape_empty"


# ---------------------------------------------------------------------------
# Phase 4 — PrinterDisabledError → 409
# ---------------------------------------------------------------------------


async def test_post_print_printer_disabled_is_409(fake_service, fake_queue) -> None:
    """POST /api/v1/print mit deaktiviertem Drucker → 409 mit printer_disabled Body."""
    from app.printer_backends.exceptions import PrinterDisabledError

    fake_service.submit_print_job.side_effect = PrinterDisabledError(
        printer_id=_PRINTER_ID, slug="brother-p750w"
    )
    async with _client(_app(fake_service, fake_queue)) as c:
        r = await c.post(
            "/api/v1/print",
            json={
                "content_type": "qr_two_lines",
                "data": {"title": "X", "primary_id": "1", "qr_payload": "u"},
            },
        )
    assert r.status_code == 409
    body = r.json()
    assert body["error"] == "printer_disabled"
    assert body["slug"] == "brother-p750w"


async def test_post_print_cover_open_is_409(fake_service, fake_queue) -> None:
    from app.printer_backends.exceptions import PrinterCoverOpenError

    fake_service.submit_print_job.side_effect = PrinterCoverOpenError()
    async with _client(_app(fake_service, fake_queue)) as c:
        r = await c.post(
            "/api/v1/print",
            json={
                "content_type": "qr_two_lines",
                "data": {"title": "X", "primary_id": "1", "qr_payload": "u"},
            },
        )
    assert r.status_code == 409
    assert r.json()["error_code"] == "printer_cover_open"


# ---------------------------------------------------------------------------
# POST /api/v1/printer/resume
# ---------------------------------------------------------------------------


async def test_resume_printer_endpoint(fake_service, fake_queue) -> None:
    fake_queue.resume_printer = AsyncMock(return_value=None)
    app = _app(fake_service, fake_queue)
    app.state.printer_id = _PRINTER_ID
    async with _client(app) as c:
        r = await c.post("/api/v1/printer/resume")
    assert r.status_code == 200
    body = r.json()
    assert body == {"printer_id": _PRINTER_ID_STR, "state": "active"}
    fake_queue.resume_printer.assert_awaited_once_with(_PRINTER_ID)


async def test_resume_printer_404_when_no_printer_configured(fake_service, fake_queue) -> None:
    app = _app(fake_service, fake_queue)
    # NOT setting app.state.printer_id
    async with _client(app) as c:
        r = await c.post("/api/v1/printer/resume")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/printer/resume — 409 contract (Commit B — Issue #67)
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
        r = await c.post("/api/v1/printer/resume")
    assert r.status_code == 409
    body = r.json()
    assert body.get("error_code") == "already_active"


async def test_resume_printer_paused_returns_200(fake_service, fake_queue) -> None:
    """Calling resume_printer on a PAUSED printer must still return 200 (control)."""
    fake_queue.resume_printer = AsyncMock(return_value=None)
    app = _app(fake_service, fake_queue)
    app.state.printer_id = _PRINTER_ID
    async with _client(app) as c:
        r = await c.post("/api/v1/printer/resume")
    assert r.status_code == 200
    assert r.json() == {"printer_id": _PRINTER_ID_STR, "state": "active"}
