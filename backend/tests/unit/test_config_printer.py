"""Phase 1i CA-1: Tests für entfernte drucker-spezifische Settings-Felder.

Die 9 Felder (ql820_host, ql820_port, pt750w_host, pt750w_port,
printer_backend, printer_model, printer_discover_via_snmp,
printer_snmp_community, printer_queue_timeout_s) wurden aus Settings entfernt.
Diese Datei dokumentiert dass sie NICHT mehr vorhanden sind.

Hinweis zu extra="forbid" in pydantic-settings:
  extra="forbid" verhindert das direkte Übergeben alter Felder als Kwargs
  (z.B. Settings(pt750w_host="x") → ValidationError). Unbekannte Env-Vars
  (LABELYARD_PT750W_HOST) werden von pydantic-settings hingegen SILENTLY
  ignoriert — das ist pydantic-settings v2 Standardverhalten. Die Felder
  existieren einfach nicht mehr auf dem Settings-Objekt.
"""

from __future__ import annotations

import pytest
from app.config import Settings
from pydantic import ValidationError


def test_removed_fields_raise_on_direct_kwarg_printer_backend() -> None:
    """CA-1: printer_backend als Kwarg → ValidationError wegen extra=forbid."""
    with pytest.raises(ValidationError, match="extra_forbidden"):
        Settings(printer_backend="mock", _env_file=None)  # type: ignore[call-arg]


def test_removed_pt750w_host_raises_as_kwarg() -> None:
    """CA-1: pt750w_host als Kwarg → ValidationError wegen extra=forbid."""
    with pytest.raises(ValidationError, match="extra_forbidden"):
        Settings(pt750w_host="192.0.2.1", _env_file=None)  # type: ignore[call-arg]


def test_removed_ql820_host_raises_as_kwarg() -> None:
    """CA-1: ql820_host als Kwarg → ValidationError wegen extra=forbid."""
    with pytest.raises(ValidationError, match="extra_forbidden"):
        Settings(ql820_host="192.0.2.2", _env_file=None)  # type: ignore[call-arg]


def test_removed_fields_not_on_settings_object(monkeypatch: pytest.MonkeyPatch) -> None:
    """CA-1: Env-Var gesetzt aber Feld existiert nicht mehr auf Settings.

    pydantic-settings ignoriert unbekannte Env-Vars silently (kein Raise).
    Das Feld ist schlicht nicht mehr vorhanden.
    """
    monkeypatch.setenv("LABELYARD_PT750W_HOST", "192.0.2.1")
    s = Settings(_env_file=None)
    assert not hasattr(s, "pt750w_host"), "pt750w_host darf nicht auf Settings existieren"
    assert not hasattr(s, "printer_backend"), "printer_backend darf nicht auf Settings existieren"
    assert not hasattr(s, "printer_model"), "printer_model darf nicht auf Settings existieren"
