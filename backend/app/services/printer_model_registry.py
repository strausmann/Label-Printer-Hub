"""Plugin-Registry fuer Drucker-Modelle (Issue #124).

Die Admin-UI braucht eine Liste verfuegbarer (backend, model)-Kombinationen
fuer das Model-Dropdown. Die Modelle leben in den Plugins
(ptouch.PRINTERS, brother_ql.MODELS) — Registry ist eine duenne Wrapper-Schicht.

Bekannte Kopplung (M5 akzeptiert):
- Falls ptouch.PRINTERS umbenannt wird, faellt der Import zurueck auf
  HARDCODED_FALLBACK_MODELS.
- brother_ql.MODELS hat aktuell eine stabile API.

Discovery-Strategie (ptouch):
  1. ptouch.PRINTERS (dict) — Spec-Pfad, noch nicht in ptouch 1.1.0
  2. ptouch.printers (Submodul) — PT*-Klassen via inspect

Discovery-Strategie (brother_ql):
  1. brother_ql.models.MODELS (dict) — Spec-Pfad, noch nicht in brother_ql 0.9.4
  2. brother_ql.models.ALL_MODELS (list[Model]) — stabiler API-Pfad in 0.9.4
"""
from __future__ import annotations

import inspect
import types
from dataclasses import dataclass


@dataclass(frozen=True)
class PrinterModel:
    backend: str
    model: str
    display_name: str


HARDCODED_FALLBACK_MODELS: tuple[PrinterModel, ...] = (
    PrinterModel("ptouch", "PT-P750W", "Brother PT-P750W (Compact-Tape 18mm)"),
    PrinterModel("brother_ql", "QL-820NWB", "Brother QL-820NWB (Endlosrolle 62mm)"),
)


def _load_ptouch_models() -> list[PrinterModel]:
    """Laedt ptouch-Modelle aus der ptouch-Bibliothek.

    Versucht zuerst ptouch.PRINTERS (Spec-Pfad), dann ptouch.printers
    via Klassen-Introspection (reale API in ptouch 1.1.0).
    Gibt leere Liste zurueck bei ImportError oder fehlendem Attribut.
    """
    try:
        import ptouch
    except ImportError:
        return []

    # Pfad 1: Spec-Pfad — ptouch.PRINTERS als dict {name: ...}
    raw = getattr(ptouch, "PRINTERS", None)
    if raw is not None and isinstance(raw, dict):
        return [
            PrinterModel(backend="ptouch", model=name, display_name=f"Brother {name}")
            for name in raw
        ]

    # Pfad 2: Reale API — ptouch.printers Submodul mit PT*-Klassen
    try:
        import ptouch.printers as pt_printers
    except ImportError:
        return []

    if not isinstance(pt_printers, types.ModuleType):
        return []

    pt_classes = [
        name
        for name, obj in inspect.getmembers(pt_printers, inspect.isclass)
        if (name.startswith("PT") or name.startswith("PTE")) and name != "PTouchError"
    ]
    return [
        PrinterModel(
            backend="ptouch",
            model=name,
            display_name=f"Brother {name}",
        )
        for name in pt_classes
    ]


def _load_brother_ql_models() -> list[PrinterModel]:
    """Laedt brother_ql-Modelle aus der brother_ql-Bibliothek.

    Versucht zuerst brother_ql.models.MODELS (Spec-Pfad), dann
    brother_ql.models.ALL_MODELS (reale API in brother_ql 0.9.4).
    Gibt leere Liste zurueck bei ImportError oder fehlendem Attribut.
    """
    try:
        from brother_ql import models as bq_models
    except ImportError:
        return []

    if not isinstance(bq_models, types.ModuleType):
        return []

    # Pfad 1: Spec-Pfad — brother_ql.models.MODELS als dict {name: ...}
    raw = getattr(bq_models, "MODELS", None)
    if raw is not None and isinstance(raw, dict):
        return [
            PrinterModel(
                backend="brother_ql",
                model=name,
                display_name=f"Brother {name}",
            )
            for name in raw
        ]

    # Pfad 2: Reale API — ALL_MODELS als list[Model] mit .identifier
    all_models = getattr(bq_models, "ALL_MODELS", None)
    if all_models is None:
        return []

    result: list[PrinterModel] = []
    for entry in all_models:
        identifier = getattr(entry, "identifier", None)
        if identifier is None or not isinstance(identifier, str):
            continue
        result.append(
            PrinterModel(
                backend="brother_ql",
                model=identifier,
                display_name=f"Brother {identifier}",
            )
        )
    return result


def list_available_models() -> list[PrinterModel]:
    """Sammelt verfuegbare Modelle aus den Plugins.

    Faellt auf HARDCODED_FALLBACK_MODELS zurueck wenn beide Plugins
    keine Modelle liefern.
    """
    models = _load_ptouch_models() + _load_brother_ql_models()
    if not models:
        return list(HARDCODED_FALLBACK_MODELS)
    return models
