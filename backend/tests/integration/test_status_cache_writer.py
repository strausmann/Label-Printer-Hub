"""Phase 7b Cluster 1f — StatusProbeProducer writes printer_status_cache."""

from __future__ import annotations

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def _printer_id():
    """Insert one Printer row into the autouse temp-DB and return its UUID."""
    import app.db.engine as _eng
    from app.models.printer import Printer

    async with _eng.async_session() as s:
        p = Printer(
            name="cache-writer-test",
            model="PT-P750W",
            backend="ptouch",
            connection={"host": "127.0.0.1", "port": 9100},
        )
        s.add(p)
        await s.commit()
        await s.refresh(p)
        return p.id


def _make_producer(printer_id):
    """Build a StatusProbeProducer with a stub EventBus."""
    from app.services.event_bus import EventBus
    from app.services.producers.status_probe_producer import StatusProbeProducer

    return StatusProbeProducer(
        bus=EventBus(),
        printer_id=str(printer_id),
        host="127.0.0.1",
    )


# ---------------------------------------------------------------------------
# Test 1 — successful probe writes online=True cache row
# ---------------------------------------------------------------------------


async def test_successful_probe_writes_cache(_printer_id, monkeypatch):
    """_probe_once writes online=True with loaded_tape_mm when probe succeeds."""
    from app.printer_backends.snmp_helper import PreflightStatus

    ok_status = PreflightStatus(
        hr_printer_status="idle",
        loaded_tape_mm=12,
        error_flags=[],
    )

    async def _fake_query(host, *, community="public", timeout_s=3.0):
        return ok_status

    monkeypatch.setattr(
        "app.services.producers.status_probe_producer.query_preflight",
        _fake_query,
    )

    producer = _make_producer(_printer_id)
    await producer._probe_once()

    import app.db.engine as _eng
    from app.models.printer_status_cache import PrinterStatusCache

    async with _eng.async_session() as s:
        row = await s.get(PrinterStatusCache, _printer_id)

    assert row is not None, "cache row must be written after successful probe"
    assert row.captured_at is not None
    assert row.parsed is not None
    assert row.parsed["online"] is True
    assert row.parsed["loaded_tape_mm"] == 12


# ---------------------------------------------------------------------------
# Test 2 — failed probe writes online=False cache row
# ---------------------------------------------------------------------------


async def test_probe_failure_marks_offline(_printer_id, monkeypatch):
    """_probe_once writes online=False + last_error when SNMP raises."""

    async def _failing_query(host, *, community="public", timeout_s=3.0):
        raise OSError("timed out")

    monkeypatch.setattr(
        "app.services.producers.status_probe_producer.query_preflight",
        _failing_query,
    )

    producer = _make_producer(_printer_id)
    await producer._probe_once()

    import app.db.engine as _eng
    from app.models.printer_status_cache import PrinterStatusCache

    async with _eng.async_session() as s:
        row = await s.get(PrinterStatusCache, _printer_id)

    assert row is not None, "cache row must be written even on probe failure"
    assert row.captured_at is not None
    assert row.parsed is not None
    assert row.parsed["online"] is False
    assert "last_error" in row.parsed


# ---------------------------------------------------------------------------
# Test 3 — failure after success preserves prior parsed data
# ---------------------------------------------------------------------------


async def test_probe_failure_preserves_prior_parsed_data(_printer_id, monkeypatch):
    """After a prior success, a failing probe keeps loaded_tape_mm but flips online=False."""
    from app.printer_backends.snmp_helper import PreflightStatus

    # First call: success
    async def _ok_query(host, *, community="public", timeout_s=3.0):
        return PreflightStatus(
            hr_printer_status="idle",
            loaded_tape_mm=24,
            error_flags=[],
        )

    monkeypatch.setattr(
        "app.services.producers.status_probe_producer.query_preflight",
        _ok_query,
    )

    producer = _make_producer(_printer_id)
    await producer._probe_once()  # success — should write loaded_tape_mm=24

    # Second call: failure
    async def _fail_query(host, *, community="public", timeout_s=3.0):
        raise OSError("gone offline")

    monkeypatch.setattr(
        "app.services.producers.status_probe_producer.query_preflight",
        _fail_query,
    )

    await producer._probe_once()  # failure — should flip online=False, keep tape data

    import app.db.engine as _eng
    from app.models.printer_status_cache import PrinterStatusCache

    async with _eng.async_session() as s:
        row = await s.get(PrinterStatusCache, _printer_id)

    assert row is not None
    assert row.parsed is not None
    assert row.parsed["online"] is False
    assert "last_error" in row.parsed
    # Prior tape data must be preserved
    assert row.parsed.get("loaded_tape_mm") == 24
