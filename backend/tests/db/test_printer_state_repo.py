"""Tests for the printer_state repository — get, get_or_create, set_paused."""
from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.printer import Printer
from app.repositories import printer_state as ps_repo
from app.repositories import printers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _make_printer(session) -> Printer:
    p = Printer(
        name="ql820-ps-test",
        model="ql-series",
        backend="ql",
        connection={"interface": "usb"},
    )
    return await printers.create(session, p)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_returns_none_when_missing(session):
    """get() for a UUID with no row must return None."""
    result = await ps_repo.get(session, uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_get_or_create_inserts_default(session):
    """get_or_create() inserts a paused=False row when none exists."""
    printer = await _make_printer(session)
    state = await ps_repo.get_or_create(session, printer.id)
    assert state.printer_id == printer.id
    assert state.paused is False

    # Second call must not insert a duplicate
    state2 = await ps_repo.get_or_create(session, printer.id)
    assert state2.printer_id == printer.id
    assert state2.paused is False


@pytest.mark.asyncio
async def test_set_paused_toggles(session):
    """set_paused flips the paused flag and persists it correctly."""
    printer = await _make_printer(session)

    # Flip True
    s1 = await ps_repo.set_paused(session, printer.id, paused=True)
    assert s1.paused is True

    # Read back independently
    s2 = await ps_repo.get(session, printer.id)
    assert s2 is not None
    assert s2.paused is True

    # Flip back to False
    s3 = await ps_repo.set_paused(session, printer.id, paused=False)
    assert s3.paused is False

    s4 = await ps_repo.get(session, printer.id)
    assert s4 is not None
    assert s4.paused is False
