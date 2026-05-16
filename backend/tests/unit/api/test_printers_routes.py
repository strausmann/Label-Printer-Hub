"""Unit tests for app.api.routes.printers — 7 endpoints (Phase 6a Task 1).

Each test builds a minimal FastAPI app with the printers router mounted, an
in-memory SQLite DB injected via ``get_session`` override, and (for the status
probe) a monkeypatched ``_probe_status_sync`` so no real TCP connection is
attempted.

Test mapping (one test per endpoint):
    1. GET  /api/printers            → list_printers
    2. GET  /api/printers/{id}/status → get_printer_status
    3. GET  /api/printers/{id}/tape   → get_printer_tape
    4. GET  /api/printers/{id}/queue  → get_printer_queue
    5. POST /api/printers/{id}/pause  → pause_printer
    6. POST /api/printers/{id}/resume → resume_printer
    7. POST /api/printers/{id}/queue/clear → clear_printer_queue
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import app.models  # noqa: F401 — registers all SQLModel tables with metadata
import pytest
import pytest_asyncio
from app.api.routes.printers import router
from app.db.engine import _apply_pragmas
from app.db.session import get_session
from app.models.job import Job, JobState
from app.models.printer import Printer
from app.models.printer_state import PrinterState
from app.models.printer_status_cache import PrinterStatusCache
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

# ---------------------------------------------------------------------------
# In-memory DB fixtures
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
    """Return a FastAPI app with the printers router and the DB overridden."""
    app = FastAPI()
    app.include_router(router)

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session_override

    app.dependency_overrides[get_session] = _override_session
    return app


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _make_printer(session: AsyncSession, **kwargs: Any) -> Printer:
    defaults: dict[str, Any] = {
        "name": "test-printer",
        "model": "pt-series",
        "backend": "ptouch",
        "connection": {"host": "192.168.1.10", "port": 9100},
    }
    defaults.update(kwargs)
    p = Printer(**defaults)
    session.add(p)
    await session.commit()
    await session.refresh(p)
    return p


async def _make_printer_state(
    session: AsyncSession, printer_id: UUID, paused: bool = False
) -> PrinterState:
    state = PrinterState(printer_id=printer_id, paused=paused)
    session.add(state)
    await session.commit()
    await session.refresh(state)
    return state


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
# Test 1: GET /api/printers — list_printers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_printers_returns_printers_with_paused_flag(session) -> None:
    """list_printers joins printer_state.paused and returns PrinterRead list."""
    printer = await _make_printer(session)
    await _make_printer_state(session, printer.id, paused=True)

    app = _build_app(session)
    client = TestClient(app, raise_server_exceptions=True)
    r = client.get("/api/printers")

    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 1
    p = body[0]
    assert p["name"] == "test-printer"
    assert p["paused"] is True
    assert "id" in p
    assert "model" in p
    assert "backend" in p


# ---------------------------------------------------------------------------
# Test 2: GET /api/printers/{id}/status — get_printer_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_printer_status_calls_probe_and_upserts_cache(session, monkeypatch) -> None:
    """get_printer_status wraps the probe in asyncio.to_thread and upserts cache."""
    from app.services.status_block import (
        MediaType,
        NotificationCode,
        PhaseType,
        PrinterError,
        StatusBlock,
        StatusType,
        TapeColor,
        TextColor,
    )

    printer = await _make_printer(session)

    # Build a fake parsed StatusBlock (12mm laminated tape, no errors)
    fake_block = StatusBlock(
        raw=b"\x80" + b"\x00" * 31,
        print_head_mark=0x80,
        size=32,
        brother_code=ord("B"),
        series_code=0x30,
        model_code=0x00,
        country_code=0xFF,
        media_width_mm=12,
        media_type=MediaType.LAMINATED,
        media_length_mm=0,
        mode=0,
        status_type=StatusType.REPLY,
        phase_type=PhaseType.EDITING,
        phase_number=0,
        notification=NotificationCode.NOT_AVAILABLE,
        tape_color=TapeColor.BLACK,
        text_color=TextColor.WHITE,
        errors=PrinterError.NONE,
    )

    def fake_probe(host: str, port: int = 9100) -> dict[str, Any]:
        return {"raw": b"\x80" + b"\x00" * 31, "block": fake_block}

    monkeypatch.setattr("app.api.routes.printers._probe_status_sync", fake_probe)

    app = _build_app(session)
    client = TestClient(app, raise_server_exceptions=True)
    r = client.get(f"/api/printers/{printer.id}/status")

    assert r.status_code == 200
    body = r.json()
    assert body["printer_id"] == str(printer.id)
    assert body["online"] is True
    assert "12mm" in (body["tape_loaded"] or "")
    assert body["error_state"] is None
    assert "captured_at" in body


# ---------------------------------------------------------------------------
# Test 3: GET /api/printers/{id}/tape — get_printer_tape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_printer_tape_returns_tape_spec_from_cache(session) -> None:
    """get_printer_tape reads the cached status block and returns the TapeSpec."""
    printer = await _make_printer(session)

    # Insert a cached status block for a 12mm laminated tape
    cache = PrinterStatusCache(
        printer_id=printer.id,
        raw_block=b"\x80" + b"\x00" * 31,
        parsed={
            "media_width_mm": 12,
            "media_type": "LAMINATED",
            "status_type": "REPLY",
            "phase_type": "EDITING",
            "errors": 0,
            "tape_color": "BLACK",
            "text_color": "WHITE",
        },
        captured_at=datetime.now(UTC),
    )
    session.add(cache)
    await session.commit()

    app = _build_app(session)
    client = TestClient(app, raise_server_exceptions=True)
    r = client.get(f"/api/printers/{printer.id}/tape")

    assert r.status_code == 200
    body = r.json()
    assert body["width_mm"] == 12


# ---------------------------------------------------------------------------
# Test 4: GET /api/printers/{id}/queue — get_printer_queue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_printer_queue_returns_queued_and_printing_jobs(session) -> None:
    """get_printer_queue returns QUEUED and PRINTING jobs for the printer."""
    printer = await _make_printer(session)
    job_q = await _make_job(session, printer.id, state=JobState.QUEUED.value)
    job_p = await _make_job(session, printer.id, state=JobState.PRINTING.value)
    # DONE job — must NOT appear
    await _make_job(session, printer.id, state=JobState.DONE.value)

    app = _build_app(session)
    client = TestClient(app, raise_server_exceptions=True)
    r = client.get(f"/api/printers/{printer.id}/queue")

    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    ids = {item["id"] for item in body}
    assert str(job_q.id) in ids
    assert str(job_p.id) in ids
    assert len(body) == 2


# ---------------------------------------------------------------------------
# Test 5: POST /api/printers/{id}/pause — pause_printer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pause_printer_returns_204_and_sets_paused_true(session) -> None:
    """pause_printer sets printer_state.paused=True and returns 204."""
    from app.repositories import printer_state as ps_repo

    printer = await _make_printer(session)
    await _make_printer_state(session, printer.id, paused=False)

    app = _build_app(session)
    client = TestClient(app, raise_server_exceptions=True)
    r = client.post(f"/api/printers/{printer.id}/pause")

    assert r.status_code == 204

    state = await ps_repo.get(session, printer.id)
    assert state is not None
    assert state.paused is True


# ---------------------------------------------------------------------------
# Test 6: POST /api/printers/{id}/resume — resume_printer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_printer_returns_204_and_sets_paused_false(session) -> None:
    """resume_printer sets printer_state.paused=False and returns 204."""
    from app.repositories import printer_state as ps_repo

    printer = await _make_printer(session)
    await _make_printer_state(session, printer.id, paused=True)

    app = _build_app(session)
    client = TestClient(app, raise_server_exceptions=True)
    r = client.post(f"/api/printers/{printer.id}/resume")

    assert r.status_code == 204

    state = await ps_repo.get(session, printer.id)
    assert state is not None
    assert state.paused is False


# ---------------------------------------------------------------------------
# Test 7: POST /api/printers/{id}/queue/clear — clear_printer_queue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clear_printer_queue_cancels_only_queued_jobs(session) -> None:
    """queue/clear cancels QUEUED jobs but leaves PRINTING jobs untouched."""
    printer = await _make_printer(session)
    job_q = await _make_job(session, printer.id, state=JobState.QUEUED.value)
    job_p = await _make_job(session, printer.id, state=JobState.PRINTING.value)

    app = _build_app(session)
    client = TestClient(app, raise_server_exceptions=True)
    r = client.post(f"/api/printers/{printer.id}/queue/clear")

    assert r.status_code == 204

    # QUEUED job must be cancelled
    cancelled = await session.get(Job, job_q.id)
    assert cancelled is not None
    assert cancelled.state == JobState.CANCELLED.value

    # PRINTING job must remain printing
    still_printing = await session.get(Job, job_p.id)
    assert still_printing is not None
    assert still_printing.state == JobState.PRINTING.value
