"""Unit tests for app.api.routes.jobs — 6 endpoints (Phase 6a Task 3).

Test mapping:
    1.  GET  /api/jobs              → test_list_jobs_unfiltered_returns_all
    2.  GET  /api/jobs?state=queued → test_list_jobs_filter_by_state
    3.  GET  /api/jobs?printer_id=X → test_list_jobs_filter_by_printer_id
    4a. GET  /api/jobs/{id}         → test_get_job_by_id_happy_path
    4b. GET  /api/jobs/{id}         → test_get_job_by_id_not_found_returns_404
    5.  POST /api/jobs/{id}/cancel  → test_cancel_queued_job_succeeds
    6.  POST /api/jobs/{id}/cancel  → test_cancel_printing_job_returns_409
    7.  POST /api/jobs/{id}/pause   → test_pause_returns_501
    8.  POST /api/jobs/{id}/resume  → test_resume_returns_501
    9.  POST /api/jobs/{id}/retry   → test_retry_clones_failed_job
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import app.models  # noqa: F401 — registers all SQLModel tables with metadata
import pytest
import pytest_asyncio
from app.api.routes.jobs import router
from app.db.engine import _apply_pragmas
from app.db.session import get_session
from app.models.job import Job, JobState
from app.models.printer import Printer
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel


# ---------------------------------------------------------------------------
# In-memory DB fixtures (same pattern as test_printers_routes.py)
# ---------------------------------------------------------------------------


def _make_engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(eng.sync_engine, "connect", _apply_pragmas)
    return eng


@pytest_asyncio.fixture
async def engine():
    eng = _make_engine()
    async with eng.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s


# ---------------------------------------------------------------------------
# App factory with DB override
# ---------------------------------------------------------------------------


def _build_app(session_override: AsyncSession) -> FastAPI:
    """Return a FastAPI app with the jobs router and the DB overridden."""
    app = FastAPI()
    app.include_router(router)

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session_override

    app.dependency_overrides[get_session] = _override_session
    return app


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


_printer_counter = 0


async def _make_printer(session: AsyncSession, name: str | None = None) -> Printer:
    global _printer_counter
    _printer_counter += 1
    p = Printer(
        name=name or f"test-printer-{_printer_counter}",
        model="pt-series",
        backend="ptouch",
        connection={"host": "192.168.1.10", "port": 9100},
    )
    session.add(p)
    await session.commit()
    await session.refresh(p)
    return p


async def _make_job(
    session: AsyncSession,
    printer_id: UUID,
    state: str = JobState.QUEUED.value,
    template_key: str = "label/default",
) -> Job:
    job = Job(
        printer_id=printer_id,
        template_key=template_key,
        state=state,
        payload={"title": "test"},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


# ---------------------------------------------------------------------------
# Test 1: GET /api/jobs — unfiltered, returns all jobs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_jobs_unfiltered_returns_all(session) -> None:
    """list_jobs without filters returns all jobs in the DB."""
    printer = await _make_printer(session)
    j1 = await _make_job(session, printer.id, state=JobState.QUEUED.value)
    j2 = await _make_job(session, printer.id, state=JobState.DONE.value)
    j3 = await _make_job(session, printer.id, state=JobState.FAILED.value)

    app = _build_app(session)
    client = TestClient(app, raise_server_exceptions=True)
    r = client.get("/api/jobs")

    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 3
    ids = {item["id"] for item in body}
    assert str(j1.id) in ids
    assert str(j2.id) in ids
    assert str(j3.id) in ids
    # Spot-check required fields on one item
    first = next(item for item in body if item["id"] == str(j1.id))
    assert first["state"] == JobState.QUEUED.value
    assert first["template_key"] == "label/default"
    assert "printer_id" in first
    assert "created_at" in first


# ---------------------------------------------------------------------------
# Test 2: GET /api/jobs?state=queued — filter by state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_jobs_filter_by_state_returns_only_matching(session) -> None:
    """list_jobs with ?state=queued returns only QUEUED jobs."""
    printer = await _make_printer(session)
    queued = await _make_job(session, printer.id, state=JobState.QUEUED.value)
    await _make_job(session, printer.id, state=JobState.DONE.value)
    await _make_job(session, printer.id, state=JobState.FAILED.value)

    app = _build_app(session)
    client = TestClient(app, raise_server_exceptions=True)
    r = client.get("/api/jobs?state=queued")

    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["id"] == str(queued.id)
    assert body[0]["state"] == JobState.QUEUED.value


# ---------------------------------------------------------------------------
# Test 3: GET /api/jobs?printer_id=X — filter by printer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_jobs_filter_by_printer_id(session) -> None:
    """list_jobs with ?printer_id= returns only jobs for that printer."""
    printer_a = await _make_printer(session)
    printer_b = await _make_printer(session)

    j_a = await _make_job(session, printer_a.id)
    await _make_job(session, printer_b.id)

    app = _build_app(session)
    client = TestClient(app, raise_server_exceptions=True)
    r = client.get(f"/api/jobs?printer_id={printer_a.id}")

    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["id"] == str(j_a.id)
    assert body[0]["printer_id"] == str(printer_a.id)


# ---------------------------------------------------------------------------
# Test 4a: GET /api/jobs/{id} — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_job_by_id_happy_path(session) -> None:
    """get_job returns the full job record for an existing ID."""
    printer = await _make_printer(session)
    job = await _make_job(session, printer.id, state=JobState.QUEUED.value)

    app = _build_app(session)
    client = TestClient(app, raise_server_exceptions=True)
    r = client.get(f"/api/jobs/{job.id}")

    assert r.status_code == 200
    body = r.json()
    assert body["id"] == str(job.id)
    assert body["state"] == JobState.QUEUED.value
    assert body["printer_id"] == str(printer.id)
    assert body["template_key"] == "label/default"
    assert body["result"] is None
    assert body["error"] is None


# ---------------------------------------------------------------------------
# Test 4b: GET /api/jobs/{id} — not found returns 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_job_by_id_not_found_returns_404(session) -> None:
    """get_job returns 404 for an unknown UUID."""
    app = _build_app(session)
    client = TestClient(app, raise_server_exceptions=True)
    r = client.get(f"/api/jobs/{uuid4()}")

    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Test 5: POST /api/jobs/{id}/cancel — QUEUED succeeds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_queued_job_succeeds(session) -> None:
    """cancel_job transitions QUEUED → CANCELLED and returns JobRead."""
    printer = await _make_printer(session)
    job = await _make_job(session, printer.id, state=JobState.QUEUED.value)

    app = _build_app(session)
    client = TestClient(app, raise_server_exceptions=True)
    r = client.post(f"/api/jobs/{job.id}/cancel")

    assert r.status_code == 200
    body = r.json()
    assert body["id"] == str(job.id)
    assert body["state"] == JobState.CANCELLED.value
    assert body["finished_at"] is not None


# ---------------------------------------------------------------------------
# Test 6: POST /api/jobs/{id}/cancel — PRINTING returns 409 ProblemDetail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_printing_job_returns_409(session) -> None:
    """cancel_job returns 409 ProblemDetail when job is PRINTING."""
    printer = await _make_printer(session)
    job = await _make_job(session, printer.id, state=JobState.PRINTING.value)

    app = _build_app(session)
    client = TestClient(app, raise_server_exceptions=True)
    r = client.post(f"/api/jobs/{job.id}/cancel")

    assert r.status_code == 409
    body = r.json()
    # FastAPI wraps the detail dict in a 'detail' key
    detail = body.get("detail", body)
    assert detail["type"] == "invalid-job-state"
    assert detail["status"] == 409
    assert "printing" in detail["detail"].lower()
    assert "queued" in detail["detail"].lower()


# ---------------------------------------------------------------------------
# Test 7: POST /api/jobs/{id}/pause — returns 501 ProblemDetail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pause_returns_501(session) -> None:
    """pause_job returns 501 ProblemDetail — placeholder not yet implemented."""
    printer = await _make_printer(session)
    job = await _make_job(session, printer.id, state=JobState.QUEUED.value)

    app = _build_app(session)
    client = TestClient(app, raise_server_exceptions=True)
    r = client.post(f"/api/jobs/{job.id}/pause")

    assert r.status_code == 501
    body = r.json()
    assert body["type"] == "not-implemented"
    assert body["status"] == 501


# ---------------------------------------------------------------------------
# Test 8: POST /api/jobs/{id}/resume — returns 501 ProblemDetail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_returns_501(session) -> None:
    """resume_job returns 501 ProblemDetail — placeholder not yet implemented."""
    printer = await _make_printer(session)
    job = await _make_job(session, printer.id, state=JobState.QUEUED.value)

    app = _build_app(session)
    client = TestClient(app, raise_server_exceptions=True)
    r = client.post(f"/api/jobs/{job.id}/resume")

    assert r.status_code == 501
    body = r.json()
    assert body["type"] == "not-implemented"
    assert body["status"] == 501


# ---------------------------------------------------------------------------
# Test 9: POST /api/jobs/{id}/retry — clones FAILED into fresh QUEUED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_clones_failed_job(session) -> None:
    """retry_job creates a new QUEUED job; original stays FAILED."""
    printer = await _make_printer(session)
    original = await _make_job(session, printer.id, state=JobState.FAILED.value)

    app = _build_app(session)
    client = TestClient(app, raise_server_exceptions=True)
    r = client.post(f"/api/jobs/{original.id}/retry")

    assert r.status_code == 201
    body = r.json()
    # New job has a different ID
    assert body["id"] != str(original.id)
    # New job is QUEUED
    assert body["state"] == JobState.QUEUED.value
    # Cloned fields match original
    assert body["printer_id"] == str(original.printer_id)
    assert body["template_key"] == original.template_key
    assert body["payload"] == original.payload
    # timestamps: no started_at or finished_at on fresh job
    assert body["started_at"] is None
    assert body["finished_at"] is None

    # Original job must still be in the DB in FAILED state (use direct DB check)
    from app.repositories import jobs as jobs_repo

    original_refreshed = await jobs_repo.get(session, original.id)
    assert original_refreshed is not None
    assert original_refreshed.state == JobState.FAILED.value
