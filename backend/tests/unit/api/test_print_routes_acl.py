"""Per-printer access on the legacy routes (POST /print, /printer/resume, /jobs/*)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID
from uuid import uuid4 as _uuid4

import pytest
from app.api.routes import print as print_routes
from app.api.routes.print import router
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_print, require_read
from app.db.session import get_session
from app.services.job_lifecycle import Job, JobState
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

_DEFAULT = UUID("dddddddd-0000-0000-0000-000000000001")
_OTHER = UUID("dddddddd-0000-0000-0000-000000000002")
_PRINT_BODY = {
    "content_type": "qr_two_lines",
    "data": {"title": "X", "primary_id": "1", "qr_payload": "u"},
}


def _ctx(allowed: list[UUID]) -> AuthContext:
    return AuthContext(
        source="api-key",
        scope="print",
        api_key_id=_uuid4(),
        ip="127.0.0.1",
        allowed_printer_ids=[str(p) for p in allowed],
    )


def _app(ctx: AuthContext, service: AsyncMock, queue: MagicMock) -> FastAPI:
    app = FastAPI()
    app.state.print_service = service
    app.state.print_queue = queue
    app.state.printer_id = _DEFAULT
    app.include_router(router)

    async def _fake_session():
        yield MagicMock()

    app.dependency_overrides[get_session] = _fake_session
    for dep in (require_read, require_print):
        app.dependency_overrides[dep] = lambda _c=ctx: _c
    return app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def _job(printer_id: UUID) -> Job:
    job = Job(id="job-1", printer_id=printer_id, image_payload=b"", tape_mm=24, options={})
    job.state = JobState.PAUSED
    job.submitted_at = datetime.now(UTC)
    return job


@pytest.fixture
def service() -> AsyncMock:
    m = AsyncMock()
    m.submit_print_job.return_value = "job-1"
    return m


@pytest.fixture
def queue() -> MagicMock:
    q = MagicMock()
    q.resume_printer = AsyncMock(return_value=None)
    q.resume_job = AsyncMock(return_value=None)
    return q


@pytest.fixture
def set_paused(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    m = AsyncMock()
    monkeypatch.setattr(print_routes.printer_state_repo, "set_paused", m)
    return m


# --- POST /print -----------------------------------------------------------------------


async def test_post_print_restricted_key_gets_403_and_nothing_is_submitted(service, queue) -> None:
    app = _app(_ctx([_OTHER]), service, queue)
    async with _client(app) as c:
        r = await c.post("/print", json=_PRINT_BODY)
    assert r.status_code == 403
    assert r.json()["detail"]["error_code"] == "printer_not_allowed"
    service.submit_print_job.assert_not_awaited()


async def test_post_print_key_allowed_for_default_printer_works(service, queue) -> None:
    async with _client(_app(_ctx([_DEFAULT]), service, queue)) as c:
        r = await c.post("/print", json=_PRINT_BODY)
    assert r.status_code == 202
    service.submit_print_job.assert_awaited_once()


async def test_post_print_unrestricted_key_keeps_working(service, queue) -> None:
    async with _client(_app(_ctx([]), service, queue)) as c:
        r = await c.post("/print", json=_PRINT_BODY)
    assert r.status_code == 202


# --- POST /printer/resume --------------------------------------------------------------


async def test_printer_resume_restricted_key_gets_403_and_pause_stays(
    service, queue, set_paused
) -> None:
    async with _client(_app(_ctx([_OTHER]), service, queue)) as c:
        r = await c.post("/printer/resume")
    assert r.status_code == 403
    assert r.json()["detail"]["error_code"] == "printer_not_allowed"
    set_paused.assert_not_awaited()
    queue.resume_printer.assert_not_awaited()


async def test_printer_resume_allowed_and_unrestricted_keys_work(
    service, queue, set_paused
) -> None:
    for allowed in ([_DEFAULT], []):
        async with _client(_app(_ctx(allowed), service, queue)) as c:
            r = await c.post("/printer/resume")
        assert r.status_code == 200
    assert set_paused.await_count == 2


# --- GET /jobs/{id} and POST /jobs/{id}/resume -----------------------------------------


async def test_get_job_foreign_printer_is_404_like_unknown(service, queue) -> None:
    queue.get = AsyncMock(return_value=_job(_DEFAULT))
    async with _client(_app(_ctx([_OTHER]), service, queue)) as c:
        foreign = await c.get("/jobs/job-1")
    queue.get = AsyncMock(side_effect=KeyError("job-1"))
    async with _client(_app(_ctx([_OTHER]), service, queue)) as c:
        unknown = await c.get("/jobs/job-1")
    assert foreign.status_code == 404
    assert foreign.json() == unknown.json()


async def test_get_job_own_and_unrestricted_work(service, queue) -> None:
    queue.get = AsyncMock(return_value=_job(_DEFAULT))
    for allowed in ([_DEFAULT], []):
        async with _client(_app(_ctx(allowed), service, queue)) as c:
            r = await c.get("/jobs/job-1")
        assert r.status_code == 200


async def test_resume_job_foreign_printer_is_404_and_job_untouched(service, queue) -> None:
    job = _job(_DEFAULT)
    queue.get = AsyncMock(return_value=job)
    async with _client(_app(_ctx([_OTHER]), service, queue)) as c:
        foreign = await c.post("/jobs/job-1/resume")
    queue.get = AsyncMock(side_effect=KeyError("job-1"))
    async with _client(_app(_ctx([_OTHER]), service, queue)) as c:
        unknown = await c.post("/jobs/job-1/resume")
    assert foreign.status_code == 404
    assert foreign.json() == unknown.json()
    queue.resume_job.assert_not_awaited()


async def test_resume_job_own_and_unrestricted_work(service, queue) -> None:
    queue.get = AsyncMock(return_value=_job(_DEFAULT))
    for allowed in ([_DEFAULT], []):
        async with _client(_app(_ctx(allowed), service, queue)) as c:
            r = await c.post("/jobs/job-1/resume")
        assert r.status_code == 200
