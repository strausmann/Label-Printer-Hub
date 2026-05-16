"""Tests for the printer_status_cache repository — upsert + get."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.models.printer import Printer
from app.repositories import printer_status_cache as psc_repo
from app.repositories import printers

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_BLOCK_A = bytes(range(32))  # 32-byte ascending sequence
_SAMPLE_BLOCK_B = bytes(range(32, 64))  # different 32-byte block
_CAPTURED_AT = datetime(2026, 5, 16, 10, 0, 0, tzinfo=UTC)


async def _make_printer(session, name: str = "ql820-cache-test") -> Printer:
    p = Printer(
        name=name,
        model="ql-series",
        backend="ql",
        connection={"interface": "usb"},
    )
    return await printers.create(session, p)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_inserts_new(session):
    """upsert() on a new printer_id inserts a row with correct data."""
    printer = await _make_printer(session)
    parsed = {"status": "ready", "tape_width": 12}

    row = await psc_repo.upsert(
        session,
        printer.id,
        raw_block=_SAMPLE_BLOCK_A,
        parsed=parsed,
        captured_at=_CAPTURED_AT,
    )

    assert row.printer_id == printer.id
    assert row.raw_block == _SAMPLE_BLOCK_A  # bytes round-trip
    assert row.parsed == parsed  # JSON round-trip
    assert row.captured_at == _CAPTURED_AT  # datetime preserved


@pytest.mark.asyncio
async def test_upsert_replaces_existing(session):
    """upsert() called twice results in exactly one row with the latest values."""
    printer = await _make_printer(session, name="ql820-cache-replace")

    await psc_repo.upsert(
        session,
        printer.id,
        raw_block=_SAMPLE_BLOCK_A,
        parsed={"status": "ready"},
        captured_at=_CAPTURED_AT,
    )

    captured_at_2 = datetime(2026, 5, 16, 11, 0, 0, tzinfo=UTC)
    row = await psc_repo.upsert(
        session,
        printer.id,
        raw_block=_SAMPLE_BLOCK_B,
        parsed={"status": "cooling"},
        captured_at=captured_at_2,
    )

    assert row.raw_block == _SAMPLE_BLOCK_B
    assert row.parsed == {"status": "cooling"}
    assert row.captured_at == captured_at_2

    # Only one row exists
    re_read = await psc_repo.get(session, printer.id)
    assert re_read is not None
    assert re_read.raw_block == _SAMPLE_BLOCK_B


@pytest.mark.asyncio
async def test_get_returns_none_when_missing(session):
    """get() for a UUID with no cached row must return None."""
    result = await psc_repo.get(session, uuid4())
    assert result is None
