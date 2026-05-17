"""Phase 7b Cluster 1b — upsert_runtime_printer materialises one Printer row
from env config, idempotent across restarts, returns None when env is silent."""

from __future__ import annotations

import pytest
from app.config import Settings
from app.db.lifespan import upsert_runtime_printer
from app.models.printer import Printer
from app.services.printer_identity import derive_printer_id
from sqlmodel import select

pytestmark = pytest.mark.asyncio

_PT750W_HOST = "192.0.2.50"
_PT750W_PORT = 9100
_PT750W_MODEL = "PT-P750W"


def _settings_with_pt750w() -> Settings:
    """Settings with PT-P750W printer configured at a stable test address."""
    return Settings(
        _env_file=None,
        pt750w_host=_PT750W_HOST,
        pt750w_port=_PT750W_PORT,
        printer_model=_PT750W_MODEL,
        printer_backend="ptouch",
        printer_discover_via_snmp=False,
        printer_snmp_community="public",
    )


def _settings_with_mock_backend() -> Settings:
    """Settings without any printer host — mock/test backend, no row expected."""
    return Settings(
        _env_file=None,
        pt750w_host="",
        ql820_host="",
        printer_model="PT-P750W",
        printer_backend="mock",
        printer_discover_via_snmp=False,
    )


async def test_upsert_creates_row_when_db_empty(async_session_empty):
    settings = _settings_with_pt750w()
    expected_id = derive_printer_id(_PT750W_MODEL, _PT750W_HOST, _PT750W_PORT)

    returned_id = await upsert_runtime_printer(async_session_empty, settings)

    assert returned_id == expected_id
    result = await async_session_empty.execute(select(Printer))
    rows = list(result.scalars())
    assert len(rows) == 1
    assert rows[0].id == expected_id


async def test_upsert_is_idempotent(async_session_empty):
    settings = _settings_with_pt750w()
    first = await upsert_runtime_printer(async_session_empty, settings)
    second = await upsert_runtime_printer(async_session_empty, settings)
    assert first == second
    result = await async_session_empty.execute(select(Printer))
    assert len(list(result.scalars())) == 1


async def test_upsert_refreshes_fields_when_row_exists(async_session_empty):
    """Re-running upsert updates the row's name + connection + enabled fields."""
    settings = _settings_with_pt750w()
    pid = await upsert_runtime_printer(async_session_empty, settings)
    assert pid is not None

    # Mutate the existing row in-DB so we can verify upsert overwrites it.
    row = await async_session_empty.get(Printer, pid)
    assert row is not None
    row.enabled = False
    row.name = "stale name"
    await async_session_empty.flush()

    # Second upsert with same settings must restore the fields.
    await upsert_runtime_printer(async_session_empty, settings)
    refreshed = await async_session_empty.get(Printer, pid)
    assert refreshed is not None
    assert refreshed.enabled is True
    assert refreshed.name == f"{_PT750W_MODEL} ({_PT750W_HOST})"


async def test_upsert_returns_none_when_no_env_printer(async_session_empty):
    settings = _settings_with_mock_backend()
    result_id = await upsert_runtime_printer(async_session_empty, settings)
    assert result_id is None
    result = await async_session_empty.execute(select(Printer))
    assert len(list(result.scalars())) == 0


async def test_upsert_handles_existing_row_with_same_name_different_id(
    async_session_empty,
):
    """Phase 7b.1 regression test for issue #76:
    An old Printer row (with a random uuid4 id) from Phase 7a has the
    same NAME the new deterministic UUIDv5 wants. upsert_runtime_printer
    must replace the old row, not crash with UNIQUE constraint failed.
    """
    from uuid import uuid4

    # Settings configured for PT-P750W on 192.0.2.50:9100 — matches the
    # deterministic UUIDv5 the test below expects to land in the DB.
    settings = _settings_with_pt750w()
    expected_id = derive_printer_id(_PT750W_MODEL, _PT750W_HOST, _PT750W_PORT)

    # Seed the DB with the SAME name but a different (random) id, mimicking
    # the Phase 7a row that triggered the production crash.
    old_id = uuid4()
    assert old_id != expected_id
    async_session_empty.add(
        Printer(
            id=old_id,
            name=f"{_PT750W_MODEL} ({_PT750W_HOST})",  # same name upsert_runtime_printer computes
            model="pt-p750w",
            backend="ptouch",
            connection={"host": _PT750W_HOST, "port": _PT750W_PORT},
            enabled=True,
        )
    )
    await async_session_empty.flush()

    # Now call upsert — it must NOT raise IntegrityError
    returned_id = await upsert_runtime_printer(async_session_empty, settings)

    assert returned_id == expected_id

    # Exactly one row should remain — the new one with the deterministic id
    result = await async_session_empty.execute(select(Printer))
    rows = list(result.scalars())
    assert len(rows) == 1
    assert rows[0].id == expected_id
    assert rows[0].id != old_id


async def test_upsert_preserves_dependent_rows_during_id_migration(
    async_session_empty,
):
    """Phase 7b.1 round 2: when a name-collision triggers id-migration, ALL
    dependent rows (jobs, printer_state, printer_status_cache) must have
    their FK references rewritten to the new deterministic UUIDv5 — not
    cascade-deleted (which would lose historical print jobs)."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from app.models.job import Job, JobState
    from app.models.printer import Printer
    from app.models.printer_state import PrinterState
    from app.models.printer_status_cache import PrinterStatusCache

    settings = _settings_with_pt750w()
    expected_id = derive_printer_id(_PT750W_MODEL, _PT750W_HOST, _PT750W_PORT)

    # Seed: old Printer row with random uuid4 + dependent rows
    old_id = uuid4()
    assert old_id != expected_id
    async_session_empty.add(
        Printer(
            id=old_id,
            name=f"{_PT750W_MODEL} ({_PT750W_HOST})",
            model="pt-p750w",
            backend="ptouch",
            connection={"host": _PT750W_HOST, "port": _PT750W_PORT},
            enabled=True,
        )
    )
    await async_session_empty.flush()

    # Dependent rows that would trigger FOREIGN KEY constraint failure on DELETE
    async_session_empty.add(
        PrinterState(
            printer_id=old_id,
            paused=False,
            updated_at=datetime.now(UTC),
        )
    )
    async_session_empty.add(
        PrinterStatusCache(
            printer_id=old_id,
            captured_at=datetime.now(UTC),
            parsed={"online": False, "last_error": "stale data"},
        )
    )
    async_session_empty.add(
        Job(
            id=uuid4(),
            printer_id=old_id,
            template_key="label/address",
            state=JobState.DONE.value,
        )
    )
    await async_session_empty.flush()

    # NOW call upsert — must NOT raise IntegrityError, and must preserve dependent rows
    returned_id = await upsert_runtime_printer(async_session_empty, settings)
    assert returned_id == expected_id

    # The Printer row migrated id (old row gone, new row exists with new id)
    result = await async_session_empty.execute(select(Printer))
    rows = list(result.scalars())
    assert len(rows) == 1
    assert rows[0].id == expected_id

    # Dependent rows have FK rewritten to new id (not deleted)
    result = await async_session_empty.execute(select(PrinterState))
    states = list(result.scalars())
    assert len(states) == 1
    assert states[0].printer_id == expected_id

    result = await async_session_empty.execute(select(PrinterStatusCache))
    caches = list(result.scalars())
    assert len(caches) == 1
    assert caches[0].printer_id == expected_id

    result = await async_session_empty.execute(select(Job))
    jobs = list(result.scalars())
    assert len(jobs) == 1
    assert jobs[0].printer_id == expected_id
