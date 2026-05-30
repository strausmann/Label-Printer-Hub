"""Verifiziert dass die 3 Hangar-Templates valide YAML sind und beim Seed landen."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.schemas.template import TemplateSchema

SEED_DIR = Path(__file__).parents[3] / "app" / "seed" / "templates"


@pytest.mark.parametrize("tape_mm,template_id", [
    (12, "hangar-furniture-12mm"),
    (18, "hangar-furniture-18mm"),
    (24, "hangar-furniture-24mm"),
])
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
