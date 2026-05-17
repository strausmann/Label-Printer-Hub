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
