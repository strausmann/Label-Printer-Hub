from __future__ import annotations

import pytest
from app.printer_backends import BackendRegistry, UnknownBackendError
from app.printer_backends.mock_backend import MockPrinterBackend


@pytest.fixture(autouse=True)
def reset_registry():
    BackendRegistry._factories.clear()
    BackendRegistry._discovered = False
    yield
    BackendRegistry._factories.clear()
    BackendRegistry._discovered = False


def test_register_and_find_by_backend_id() -> None:
    BackendRegistry.register("mock", MockPrinterBackend)
    assert BackendRegistry.find_by_backend_id("mock") is MockPrinterBackend


def test_unknown_backend_raises_with_registered_list() -> None:
    BackendRegistry.register("mock", MockPrinterBackend)
    with pytest.raises(UnknownBackendError) as exc:
        BackendRegistry.find_by_backend_id("zebra-zpl")
    msg = str(exc.value)
    assert "zebra-zpl" in msg
    assert "mock" in msg


def test_duplicate_registration_rejected() -> None:
    BackendRegistry.register("mock", MockPrinterBackend)
    with pytest.raises(ValueError):
        BackendRegistry.register("mock", MockPrinterBackend)


def test_ensure_discovered_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fake_iter(group: str):
        calls["n"] += 1
        return []

    monkeypatch.setattr("app.printer_backends.entry_points", fake_iter)
    BackendRegistry.ensure_discovered()
    BackendRegistry.ensure_discovered()
    assert calls["n"] == 1


def test_entry_point_discovery_registers_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeEntryPoint:
        name = "mock"

        def load(self):
            return MockPrinterBackend

    def fake_iter(group: str):
        assert group == "label_hub.printer_backends"
        return [FakeEntryPoint()]

    monkeypatch.setattr("app.printer_backends.entry_points", fake_iter)
    BackendRegistry.ensure_discovered()
    assert BackendRegistry.find_by_backend_id("mock") is MockPrinterBackend
