"""backend/.env.example must only name real Settings fields and show the required ones."""

from __future__ import annotations

import re
from pathlib import Path

from app.config import Settings

ENV_EXAMPLE = Path(__file__).parent.parent.parent / ".env.example"
_LINE = re.compile(r"^\s*#?\s*PRINTER_HUB_([A-Z0-9_]+)=", re.MULTILINE)


def _names() -> set[str]:
    return set(_LINE.findall(ENV_EXAMPLE.read_text()))


def test_every_documented_variable_is_a_settings_field() -> None:
    unknown = {n for n in _names() if n.lower() not in Settings.model_fields}
    assert not unknown, f"Not Settings fields: {sorted(unknown)}"


def test_required_variables_are_present() -> None:
    assert {"SECRET_KEY", "PUBLIC_URL"} <= _names()


def test_removed_variables_are_gone() -> None:
    removed = {"PRINTERS_CONFIG", "PRINTER_BACKEND", "PRINTER_MODEL", "PRINTER_DISCOVER_VIA_SNMP"}
    assert not (removed & _names())
