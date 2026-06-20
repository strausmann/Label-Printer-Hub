"""Phase 7b Cluster 1b — derive_printer_id: stabiler UUIDv5 für (model, host, port, created_at_utc).

Issue #124: Erweiterung von 3-arg auf 4-arg mit timezone-aware created_at_utc.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from app.services.printer_identity import derive_printer_id

# Fester Testzeitpunkt (UTC, timezone-aware) — RFC 5737 IPs
_CREATED_AT = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)


# --- Bestehende Tests (3-arg-Semantik) — angepasst auf 4-arg ---


def test_same_inputs_produce_same_uuid():
    """Determinismus: gleicher Input → gleiche UUID."""
    a = derive_printer_id("PT-P750W", "192.0.2.50", 9100, _CREATED_AT)
    b = derive_printer_id("PT-P750W", "192.0.2.50", 9100, _CREATED_AT)
    assert a == b


def test_host_change_produces_different_uuid():
    a = derive_printer_id("PT-P750W", "192.0.2.50", 9100, _CREATED_AT)
    b = derive_printer_id("PT-P750W", "192.0.2.51", 9100, _CREATED_AT)
    assert a != b


def test_port_change_produces_different_uuid():
    a = derive_printer_id("PT-P750W", "192.0.2.50", 9100, _CREATED_AT)
    b = derive_printer_id("PT-P750W", "192.0.2.50", 9101, _CREATED_AT)
    assert a != b


def test_model_change_produces_different_uuid():
    a = derive_printer_id("PT-P750W", "192.0.2.50", 9100, _CREATED_AT)
    b = derive_printer_id("QL-820NWB", "192.0.2.50", 9100, _CREATED_AT)
    assert a != b


def test_returns_uuid_v5():
    out = derive_printer_id("PT-P750W", "192.0.2.50", 9100, _CREATED_AT)
    assert isinstance(out, UUID)
    assert out.version == 5


def test_model_case_insensitive():
    """Mixed-case Modell-Angaben ergeben dieselbe UUID.

    Die Umgebung kann ``'PT-P750W'`` oder ``'pt-p750w'`` liefern;
    beide müssen zur gleichen UUID führen.
    """
    a = derive_printer_id("PT-P750W", "192.0.2.50", 9100, _CREATED_AT)
    b = derive_printer_id("pt-p750w", "192.0.2.50", 9100, _CREATED_AT)
    assert a == b


# --- Neue Tests für 4-arg-Erweiterung (Issue #124) ---


def test_created_at_utc_change_produces_different_uuid():
    """Verschiedene created_at_utc → verschiedene UUID (auch bei sonst gleichem Input)."""
    t1 = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2024, 1, 15, 11, 0, 0, tzinfo=UTC)
    a = derive_printer_id("PT-P750W", "192.0.2.50", 9100, t1)
    b = derive_printer_id("PT-P750W", "192.0.2.50", 9100, t2)
    assert a != b


def test_naive_datetime_raises_value_error():
    """Naive datetime (kein tzinfo) → ValueError.

    Salt ist TZ-sensitiv — der ISO-String würde je nach lokaler TZ variieren.
    """
    naive_dt = datetime(2024, 1, 15, 10, 0, 0)  # kein tzinfo!
    assert naive_dt.tzinfo is None
    with pytest.raises(ValueError, match="timezone-aware"):
        derive_printer_id("PT-P750W", "192.0.2.50", 9100, naive_dt)


def test_determinism_across_calls_with_created_at():
    """Mehrfache Aufrufe mit identischen Parametern inkl. created_at_utc liefern
    exakt dieselbe UUID — kein Zufall, kein Zeitstempel-Drift."""
    t = datetime(2024, 6, 1, 8, 30, 0, tzinfo=UTC)
    results = [derive_printer_id("QL-820NWB", "192.0.2.10", 9100, t) for _ in range(5)]
    assert len(set(results)) == 1


def test_created_at_iso_format_in_salt():
    """created_at_utc wird als ISO-8601-String in den Salt aufgenommen.

    Implizite Verifikation: UTC-aware Zeitstempel mit gleicher
    Kalenderzeit aber verschiedenem UTC-Offset ergeben verschiedene UUIDs.
    """
    # +01:00 Offset — gleiche Wallclock-Zeit, aber anderer ISO-String
    berlin_tz = timezone(timedelta(hours=1))
    t_utc = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
    t_berlin = datetime(2024, 1, 15, 11, 0, 0, tzinfo=berlin_tz)  # gleiche Instant, anderer ISO

    a = derive_printer_id("PT-P750W", "192.0.2.50", 9100, t_utc)
    b = derive_printer_id("PT-P750W", "192.0.2.50", 9100, t_berlin)
    # Gleiche Instant, aber unterschiedliche ISO-Strings → verschiedene UUIDs
    # (TZ-Sensitivität ist explizit gewollt laut Spec)
    assert t_utc.isoformat() != t_berlin.isoformat()
    assert a != b
