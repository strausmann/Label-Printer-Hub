from __future__ import annotations

import pytest
from app.config import Settings


def test_defaults() -> None:
    s = Settings()
    assert s.printer_backend == "ptouch"
    assert s.printer_model == "PT-P750W"
    assert s.printer_queue_timeout_s == 30.0
    assert s.printer_discover_via_snmp is True
    assert s.printer_snmp_community == "public"


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRINTER_HUB_PRINTER_BACKEND", "mock")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_MODEL", "PT-P900")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_QUEUE_TIMEOUT_S", "60")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_DISCOVER_VIA_SNMP", "false")
    monkeypatch.setenv("PRINTER_HUB_PRINTER_SNMP_COMMUNITY", "private")
    s = Settings()
    assert s.printer_backend == "mock"
    assert s.printer_model == "PT-P900"
    assert s.printer_queue_timeout_s == 60.0
    assert s.printer_discover_via_snmp is False
    assert s.printer_snmp_community == "private"


def test_existing_pt750w_fields_intact() -> None:
    s = Settings()
    assert s.pt750w_host == ""
    assert s.pt750w_port == 9100
