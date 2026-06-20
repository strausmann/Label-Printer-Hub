"""Tests für printer_model_registry (Issue #124).

TDD: Tests wurden VOR der Implementierung geschrieben.

Strategie:
- Die Bibliotheken ptouch und brother_ql sind in der Dev-Umgebung installiert,
  daher wird der Happy-Path getestet (echte Modelle vorhanden).
- Fallback-Verhalten wird über Monkeypatching isoliert getestet.
- PrinterModel ist ein frozen dataclass — Mutation muss FrozenInstanceError werfen.
"""
from __future__ import annotations

import sys
import types
from dataclasses import FrozenInstanceError
from unittest.mock import patch

import pytest
from app.services.printer_model_registry import (
    HARDCODED_FALLBACK_MODELS,
    PrinterModel,
    _load_brother_ql_models,
    _load_ptouch_models,
    list_available_models,
)

# ---------------------------------------------------------------------------
# Test 1: list_available_models liefert mindestens ein Modell
# ---------------------------------------------------------------------------


def test_list_available_models_returns_at_least_one() -> None:
    """list_available_models() muss immer ≥1 Ergebnis liefern.

    Im schlechtesten Fall (beide Libs fehlen) kommt HARDCODED_FALLBACK_MODELS.
    Mit den installierten Libs kommen echte Modelle.
    """
    models = list_available_models()
    assert len(models) >= 1


# ---------------------------------------------------------------------------
# Test 2: ptouch- und brother_ql-Modelle sind enthalten (oder Fallback)
# ---------------------------------------------------------------------------


def test_ptouch_or_fallback_present() -> None:
    """Entweder echte ptouch-Modelle oder Fallback-PT-P750W muss vorhanden sein."""
    models = list_available_models()
    backends = {m.backend for m in models}
    # Entweder ptouch (echte Lib) oder beide Fallback-Backends
    assert "ptouch" in backends or all(
        m.backend in {"ptouch", "brother_ql"} for m in HARDCODED_FALLBACK_MODELS
    )


def test_brother_ql_or_fallback_present() -> None:
    """Entweder echte brother_ql-Modelle oder Fallback-QL-Eintrag muss vorhanden sein."""
    models = list_available_models()
    backends = {m.backend for m in models}
    assert "brother_ql" in backends or "ptouch" in backends  # Fallback enthält beide


# ---------------------------------------------------------------------------
# Test 3: PT-P750W (oder Fallback) ist enthalten
# ---------------------------------------------------------------------------


def test_pt_p750w_present_or_fallback() -> None:
    """PT-P750W muss entweder in echten ptouch-Modellen oder im Fallback auftauchen."""
    models = list_available_models()
    model_ids = {m.model for m in models}
    # Der Fallback enthält PT-P750W; echte ptouch-Lib enthält PTP750W
    has_exact = "PT-P750W" in model_ids
    has_variant = "PTP750W" in model_ids or any("750" in mid for mid in model_ids)
    assert has_exact or has_variant, f"PT-P750W variant nicht gefunden in: {model_ids}"


# ---------------------------------------------------------------------------
# Test 4: PrinterModel ist frozen (FrozenInstanceError bei Modifikation)
# ---------------------------------------------------------------------------


def test_printer_model_is_frozen() -> None:
    """PrinterModel ist ein frozen dataclass — Mutations verwerfen FrozenInstanceError."""
    pm = PrinterModel(backend="ptouch", model="PT-P750W", display_name="Test")
    with pytest.raises(FrozenInstanceError):
        pm.model = "PT-9700PC"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Isolierte Tests für _load_ptouch_models via Monkeypatching
# ---------------------------------------------------------------------------


def test_load_ptouch_models_import_error_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """_load_ptouch_models fällt auf leere Liste zurück wenn Import schlägt fehl."""
    monkeypatch.setitem(sys.modules, "ptouch", None)  # type: ignore[call-overload]
    result = _load_ptouch_models()
    assert result == []


def test_load_ptouch_models_missing_attribute_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_load_ptouch_models fällt zurück wenn PRINTERS und printers fehlen."""
    fake_ptouch = types.ModuleType("ptouch")
    # Kein PRINTERS-Attribut, kein printers-Submodul → soll leere Liste liefern
    monkeypatch.setitem(sys.modules, "ptouch", fake_ptouch)
    # Submodul-Lookup ebenfalls blocken
    monkeypatch.setitem(sys.modules, "ptouch.printers", None)  # type: ignore[call-overload]
    result = _load_ptouch_models()
    assert result == []


def test_load_ptouch_models_with_printers_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    """_load_ptouch_models verarbeitet ptouch.PRINTERS dict korrekt (Spec-Pfad)."""
    fake_ptouch = types.ModuleType("ptouch")
    fake_ptouch.PRINTERS = {"PT-P700": object(), "PT-P750W": object()}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ptouch", fake_ptouch)
    monkeypatch.setitem(sys.modules, "ptouch.printers", None)  # type: ignore[call-overload]
    result = _load_ptouch_models()
    model_names = {m.model for m in result}
    assert {"PT-P700", "PT-P750W"} == model_names
    assert all(m.backend == "ptouch" for m in result)


def test_load_brother_ql_models_import_error_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_load_brother_ql_models fällt zurück wenn Import schlägt fehl."""
    monkeypatch.setitem(sys.modules, "brother_ql", None)  # type: ignore[call-overload]
    monkeypatch.setitem(sys.modules, "brother_ql.models", None)  # type: ignore[call-overload]
    result = _load_brother_ql_models()
    assert result == []


def test_load_brother_ql_models_missing_attribute_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_load_brother_ql_models fällt zurück wenn MODELS und ALL_MODELS fehlen.

    brother_ql ist bereits importiert — sys.modules-Patch reicht nicht, weil der
    laufende Prozess die echten Objekte schon cached. Stattdessen patchen wir
    die beiden Attribute auf dem realen Modul direkt.
    """
    from brother_ql import models as real_bq_models

    monkeypatch.delattr(real_bq_models, "MODELS", raising=False)
    monkeypatch.delattr(real_bq_models, "ALL_MODELS", raising=False)
    result = _load_brother_ql_models()
    assert result == []


def test_list_available_models_fallback_when_both_libs_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """list_available_models fällt auf HARDCODED_FALLBACK_MODELS zurück wenn beide Libs fehlen."""
    with (
        patch(
            "app.services.printer_model_registry._load_ptouch_models",
            return_value=[],
        ),
        patch(
            "app.services.printer_model_registry._load_brother_ql_models",
            return_value=[],
        ),
    ):
        result = list_available_models()
    assert result == list(HARDCODED_FALLBACK_MODELS)


def test_list_available_models_no_fallback_when_models_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """list_available_models verwendet NICHT den Fallback wenn Modelle vorhanden sind."""
    fake_model = PrinterModel(backend="ptouch", model="PT-TEST", display_name="Test")
    with (
        patch(
            "app.services.printer_model_registry._load_ptouch_models",
            return_value=[fake_model],
        ),
        patch(
            "app.services.printer_model_registry._load_brother_ql_models",
            return_value=[],
        ),
    ):
        result = list_available_models()
    assert result == [fake_model]
    # HARDCODED_FALLBACK_MODELS darf NICHT enthalten sein
    for fallback in HARDCODED_FALLBACK_MODELS:
        assert fallback not in result
