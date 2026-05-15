from __future__ import annotations

from importlib.metadata import entry_points


def test_mock_backend_is_declared_in_entry_points() -> None:
    names = {ep.name for ep in entry_points(group="label_hub.printer_backends")}
    assert "mock" in names


def test_ptouch_backend_is_declared_in_entry_points() -> None:
    names = {ep.name for ep in entry_points(group="label_hub.printer_backends")}
    assert "ptouch" in names
