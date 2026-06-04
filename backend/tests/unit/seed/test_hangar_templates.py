"""Verifiziert dass die Hangar-Templates und Samla-Templates valide YAML sind."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from app.schemas.template import TemplateSchema

SEED_DIR = Path(__file__).parents[3] / "app" / "seed" / "templates"


@pytest.mark.parametrize(
    "tape_mm,template_id",
    [
        (12, "hangar-furniture-12mm"),
        (18, "hangar-furniture-18mm"),
        (24, "hangar-furniture-24mm"),
    ],
)
def test_hangar_template_parses(tape_mm: int, template_id: str):
    path = SEED_DIR / f"{template_id}.yaml"
    assert path.exists(), f"missing {path}"

    raw = yaml.safe_load(path.read_text())
    assert raw["schema_version"] == 1
    assert raw["id"] == template_id
    assert raw["app"] is None, "app must be null (IntegrationRegistry kennt hangar nicht)"
    assert raw["tape_mm"] == tape_mm

    tmpl = TemplateSchema(**raw)
    assert tmpl is not None
    types = [e["type"] for e in raw["elements"]]
    assert types.count("qr") == 1
    assert types.count("text") >= 2
    for elem in raw["elements"]:
        assert "bold" not in elem, f"'bold' is not a valid hub element field: {elem}"


@pytest.mark.parametrize(
    "tape_mm,printer_model,template_id",
    [
        (12, "ptouch", "samla-stirntag-12mm"),
        (24, "ptouch", "samla-stirntag-24mm"),
        (62, "brother_ql", "samla-stirntag-62mm"),
        (12, "ptouch", "samla-deckel-12mm"),
        (24, "ptouch", "samla-deckel-24mm"),
        (62, "brother_ql", "samla-deckel-62mm"),
    ],
)
def test_samla_template_parses(tape_mm: int, printer_model: str, template_id: str):
    """Phase 1i Task 10: Alle 6 Samla-Templates parsen korrekt.

    Prüft: tape_mm korrekt, printer_model gesetzt, QR + Text vorhanden,
    kein 'bold'-Feld (nicht im Schema), preview_sample vorhanden.
    """
    path = SEED_DIR / f"{template_id}.yaml"
    assert path.exists(), f"missing {path}"

    raw = yaml.safe_load(path.read_text())
    assert raw["schema_version"] == 1
    assert raw["id"] == template_id
    assert raw["app"] is None, "app must be null (Samla-Templates sind generisch)"
    assert raw["tape_mm"] == tape_mm
    assert raw.get("printer_model") == printer_model, (
        f"Expected printer_model={printer_model!r}, got {raw.get('printer_model')!r}"
    )

    tmpl = TemplateSchema(**raw)
    assert tmpl is not None
    assert tmpl.printer_model == printer_model

    types = [e["type"] for e in raw["elements"]]
    assert "qr" in types, "Samla-Template muss QR-Element haben"
    assert "text" in types, "Samla-Template muss Text-Element(e) haben"

    for elem in raw["elements"]:
        assert "bold" not in elem, f"'bold' ist kein gültiges Hub-Element-Feld: {elem}"

    assert raw.get("preview_sample") is not None, "preview_sample muss vorhanden sein"
    assert "qr_payload" in raw["preview_sample"], "preview_sample muss qr_payload enthalten"
