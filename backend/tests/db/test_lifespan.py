"""Tests for app.db.lifespan — startup/shutdown DB helpers.

Each test exercises a single helper function in isolation using the
in-memory SQLite session fixture from conftest.py.

Note on run_migrations(): the function wraps the synchronous Alembic
command in asyncio.to_thread.  Testing it in isolation would actually
run migrations against a real SQLite file which is covered by the
existing Alembic CLI tests and by the full app startup in CI.  We
skip a dedicated unit test here and cover only the three helpers that
operate on the in-memory session fixture.
"""

from __future__ import annotations

import pytest
from app.db.lifespan import ensure_printer_state, recover_inflight_jobs, seed_templates
from app.models.job import Job, JobState
from app.models.printer import Printer
from app.models.printer_state import PrinterState
from app.models.template import Template
from app.repositories import jobs as jobs_repo
from app.repositories import printers as printers_repo
from app.repositories import templates as templates_repo

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_printer(session, *, name: str = "pt-office") -> Printer:
    p = Printer(
        name=name,
        model="pt-series",
        backend="ptouch",
        connection={"interface": "usb"},
    )
    return await printers_repo.create(session, p)


class _MockLoader:
    """Minimal stand-in for TemplateLoader.all() that returns a fixed dict.

    Avoids loading real YAML files (which would require IntegrationRegistry
    to have plugins registered) and keeps the test self-contained.
    """

    def __init__(self, count: int = 3) -> None:
        self._count = count
        self._templates = {
            f"tpl-{i}": _schema_stub(f"tpl-{i}", f"Template {i}") for i in range(count)
        }

    def all(self) -> dict:
        return dict(self._templates)

    def __len__(self) -> int:
        return self._count

    async def seed_db(self, session) -> int:
        """Implement seed_db so seed_templates can delegate (Task 8 interface)."""
        rows = [
            Template(
                key=schema.id,
                name=schema.name,
                app=schema.app,
                printer_model="pt-series",
                tape_width_mm=schema.tape_mm,
                schema_version=schema.schema_version,
                definition=schema.model_dump(),
                source="seed",
            )
            for schema in self._templates.values()
        ]
        return await templates_repo.upsert_seed(session, rows)


def _schema_stub(id_: str, name: str):
    """Build a minimal TemplateSchema-like object for testing."""
    from app.schemas.template import TemplateSchema

    return TemplateSchema(
        id=id_,
        name=name,
        app=None,
        tape_mm=12,
        schema_version=1,
        elements=(
            {
                "type": "qr",
                "x": 0,
                "y": 0,
                "size": 80,
                "data_field": "url",
            },
        ),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recover_marks_inflight_as_failed_restart(session):
    """recover_inflight_jobs sweeps QUEUED jobs to FAILED_RESTART."""
    printer = await _make_printer(session)
    job = await jobs_repo.create_queued(
        session,
        printer_id=printer.id,
        template_key="test-label",
        payload={"field": "value"},
    )
    assert job.state == JobState.QUEUED.value

    swept = await recover_inflight_jobs(session)

    assert swept == 1
    refreshed = await session.get(Job, job.id)
    assert refreshed is not None
    assert refreshed.state == JobState.FAILED_RESTART.value


@pytest.mark.asyncio
async def test_seed_templates_idempotent(session):
    """seed_templates called twice produces exactly N rows — no duplicates."""
    loader = _MockLoader(count=3)

    count_first = await seed_templates(session, loader)
    count_second = await seed_templates(session, loader)

    assert count_first == len(loader)
    assert count_second == len(loader)

    all_rows = await templates_repo.list_all(session)
    assert len(all_rows) == len(loader)


@pytest.mark.asyncio
async def test_ensure_printer_state_creates_missing(session):
    """ensure_printer_state creates one row per printer; second call creates none."""
    p1 = await _make_printer(session, name="printer-alpha")
    p2 = await _make_printer(session, name="printer-beta")

    created_first = await ensure_printer_state(session)
    assert created_first == 2

    # Verify rows exist
    state1 = await session.get(PrinterState, p1.id)
    state2 = await session.get(PrinterState, p2.id)
    assert state1 is not None
    assert state2 is not None
    assert state1.paused is False
    assert state2.paused is False

    # Second call must be a no-op
    created_second = await ensure_printer_state(session)
    assert created_second == 0
