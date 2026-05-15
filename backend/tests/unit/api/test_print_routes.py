from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.routes.print import router
from app.printer_backends.exceptions import SnmpQueryError
from app.printer_backends.snmp_helper import LiveStatus
from app.services.job_lifecycle import Job, JobState
from app.services.lookup_service import LookupFailedError
from app.services.template_loader import TemplateNotFoundError
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


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
    job = Job(id="job-1", printer_id="p", image_payload=b"", tape_mm=24, options={})
    job.state = JobState.PRINTING
    job.submitted_at = datetime.now(UTC)
    fake_queue.get = AsyncMock(return_value=job)

    async def fake_live(host: str, *, community: str = "public", timeout_s: float = 3.0):
        return LiveStatus(hr_printer_status="printing", error_flags=[])

    monkeypatch.setattr("app.api.routes.print.query_live_status", fake_live)

    app = _app(fake_service, fake_queue)
    app.state.printer_host = "10.0.0.5"
    app.state.printer_snmp_community = "public"
    async with _client(app) as c:
        r = await c.get("/jobs/job-1")
    assert r.status_code == 200
    body = r.json()
    assert body["job_id"] == "job-1"
    assert body["status"] == "printing"
    assert body["live"] == {"hr_printer_status": "printing", "error_flags": []}


async def test_get_jobs_no_live_block_when_not_printing(fake_service, fake_queue) -> None:
    job = Job(id="job-1", printer_id="p", image_payload=b"", tape_mm=24, options={})
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
    job = Job(id="job-1", printer_id="p", image_payload=b"", tape_mm=24, options={})
    job.state = JobState.PRINTING
    job.submitted_at = datetime.now(UTC)
    fake_queue.get = AsyncMock(return_value=job)

    async def fake_live(*_a, **_kw):
        raise SnmpQueryError("timed out")

    monkeypatch.setattr("app.api.routes.print.query_live_status", fake_live)

    app = _app(fake_service, fake_queue)
    app.state.printer_host = "10.0.0.5"
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
