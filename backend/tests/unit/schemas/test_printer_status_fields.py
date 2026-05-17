"""Phase 7b Cluster 1f G2 — PrinterStatus carries cache freshness fields."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.schemas.printer import PrinterStatus


def test_printer_status_pending_when_no_probe():
    """online=None and captured_at=None signals no probe has run yet."""
    s = PrinterStatus(
        printer_id=uuid4(),
        online=None,
        captured_at=None,
        note="No probe yet — wait up to 30s for first probe cycle",
    )
    assert s.online is None
    assert s.note is not None
    assert s.note.startswith("No probe yet")


def test_printer_status_full_fields():
    """All four new fields round-trip through the model."""
    pid = uuid4()
    now = datetime.now(UTC)
    s = PrinterStatus(
        printer_id=pid,
        online=True,
        tape_loaded="12mm laminated black/white",
        captured_at=now,
        last_probe_age_s=15,
        last_error=None,
        note=None,
    )
    assert s.online is True
    assert s.last_probe_age_s == 15
    assert s.last_error is None
    assert s.note is None


def test_printer_status_serialises_captured_at_with_z_suffix():
    """captured_at is emitted as RFC3339 with Z suffix (not +00:00)."""
    s = PrinterStatus(
        printer_id=uuid4(),
        online=True,
        captured_at=datetime(2026, 5, 17, 12, 0, 0, tzinfo=UTC),
    )
    dumped = s.model_dump_json()
    assert '"captured_at":"2026-05-17T12:00:00Z"' in dumped


def test_printer_status_serialises_none_captured_at_as_null():
    """When captured_at is None the field serialises to JSON null."""
    s = PrinterStatus(printer_id=uuid4(), online=None, captured_at=None)
    dumped = s.model_dump_json()
    assert '"captured_at":null' in dumped


def test_printer_status_last_error_round_trips():
    """last_error string is preserved in model_dump."""
    s = PrinterStatus(
        printer_id=uuid4(),
        online=False,
        captured_at=datetime.now(UTC),
        last_error="timed out after 5s",
    )
    data = s.model_dump()
    assert data["last_error"] == "timed out after 5s"
    assert data["online"] is False
