"""Phase 7b Cluster 1b — derive_printer_id is a stable UUIDv5 for (model, host, port)."""

from __future__ import annotations

from uuid import UUID

from app.services.printer_identity import derive_printer_id


def test_same_inputs_produce_same_uuid():
    a = derive_printer_id("PT-P750W", "192.0.2.50", 9100)
    b = derive_printer_id("PT-P750W", "192.0.2.50", 9100)
    assert a == b


def test_host_change_produces_different_uuid():
    a = derive_printer_id("PT-P750W", "192.0.2.50", 9100)
    b = derive_printer_id("PT-P750W", "192.0.2.51", 9100)
    assert a != b


def test_port_change_produces_different_uuid():
    a = derive_printer_id("PT-P750W", "192.0.2.50", 9100)
    b = derive_printer_id("PT-P750W", "192.0.2.50", 9101)
    assert a != b


def test_model_change_produces_different_uuid():
    a = derive_printer_id("PT-P750W", "192.0.2.50", 9100)
    b = derive_printer_id("QL-820NWB", "192.0.2.50", 9100)
    assert a != b


def test_returns_uuid_v5():
    out = derive_printer_id("PT-P750W", "192.0.2.50", 9100)
    assert isinstance(out, UUID)
    assert out.version == 5


def test_model_case_insensitive():
    """Mixed-case model names hash to the same UUID.

    Environment may supply ``'PT-P750W'`` or ``'pt-p750w'``; both must resolve
    identically.
    """
    a = derive_printer_id("PT-P750W", "192.0.2.50", 9100)
    b = derive_printer_id("pt-p750w", "192.0.2.50", 9100)
    assert a == b
