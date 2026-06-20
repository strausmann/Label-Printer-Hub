"""Tests für PrinterYAMLConfig-Laufzeitkonfiguration.

Phase 5 (#124): Importpfad von app.schemas.printer_config →
app.services.backend_router (Klassen dorthin verschoben).
PrintersFile und test_duplicate_slugs_rejected entfernt — PrintersFile
existiert nicht mehr (YAML-Parser-Ebene zusammen mit PrinterConfigLoader entfernt).
"""

from __future__ import annotations

import pytest
from app.services.backend_router import (
    CutDefaults,
    PrinterYAMLConfig,
)
from pydantic import ValidationError


def test_minimal_printer_config_valid():
    cfg = PrinterYAMLConfig(
        slug="brother-p750w",
        name="Brother P-750W",
        backend="ptouch",
        model="PT-P750W",
        host="192.0.2.10",
    )
    assert cfg.port == 9100
    assert cfg.snmp.discover is True
    assert cfg.snmp.community == "public"
    assert cfg.queue.timeout_s == 30
    assert cfg.cut_defaults.half_cut is True
    assert cfg.cut_defaults.cut_at_end is True


def test_invalid_slug_pattern_rejected():
    with pytest.raises(ValidationError):
        PrinterYAMLConfig(
            slug="Brother_P750W",
            name="x",
            backend="ptouch",
            model="x",
            host="x",
        )


def test_invalid_backend_rejected():
    with pytest.raises(ValidationError):
        PrinterYAMLConfig(slug="x", name="x", backend="cups", model="x", host="x")


def test_extra_field_rejected_strict_mode():
    with pytest.raises(ValidationError):
        PrinterYAMLConfig(
            slug="x",
            name="x",
            backend="ptouch",
            model="x",
            host="x",
            unknown_field="boom",
        )


def test_half_cut_true_on_brother_ql_rejected():
    """MA-1: cut_defaults.half_cut=True + backend=brother_ql -> PrinterConfigValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        PrinterYAMLConfig(
            slug="ql820",
            name="QL820",
            backend="brother_ql",
            model="QL-820NWB",
            host="192.0.2.11",
            cut_defaults=CutDefaults(half_cut=True, cut_at_end=True),
        )
    assert "half_cut" in str(exc_info.value).lower()


# test_duplicate_slugs_rejected entfernt — PrintersFile (YAML-Datei-Schema)
# wurde in Phase 5 (#124) zusammen mit PrinterConfigLoader gelöscht.
# Duplikat-Slug-Prüfung erfolgt nun via DB UNIQUE-Constraint (Admin-API).
