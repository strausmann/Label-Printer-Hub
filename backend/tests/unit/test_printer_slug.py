"""Verifiziert dass das Printer-Modell ein `slug`-Feld hat und Default leer ist."""

from __future__ import annotations

from app.models.printer import Printer


def test_printer_model_has_slug_field():
    p = Printer(name="Brother PT-P750W", model="PT-P750W", backend="ptouch", slug="brother-p750w")
    assert p.slug == "brother-p750w"


def test_printer_slug_defaults_to_empty():
    p = Printer(name="X", model="X", backend="mock")
    assert p.slug == ""
