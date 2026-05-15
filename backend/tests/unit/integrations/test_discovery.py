"""Tests for entry_points-based plugin discovery."""

from collections.abc import Generator, Iterable

import pytest
from app.integrations import _discover_plugins
from app.integrations.registry import IntegrationRegistry


class _FakeEntryPoint:
    def __init__(self, name: str, plugin_cls: type) -> None:
        self.name = name
        self.value = f"{plugin_cls.__module__}:{plugin_cls.__name__}"
        self._cls = plugin_cls

    def load(self) -> type:
        return self._cls


class _AlphaPlugin:
    name = "alpha"
    display_name = "Alpha"

    async def lookup(self, identifier: str) -> object:
        raise NotImplementedError


class _BetaPlugin:
    name = "beta"
    display_name = "Beta"

    async def lookup(self, identifier: str) -> object:
        raise NotImplementedError


class _NotAPlugin:
    """Class that doesn't satisfy IntegrationPlugin (missing display_name, lookup)."""

    name = "fake"


class _ExplodingEntryPoint:
    def __init__(self, name: str) -> None:
        self.name = name
        self.value = "exploding"

    def load(self) -> type:
        raise RuntimeError("simulated package import failure")


@pytest.fixture(autouse=True)
def _clear_registry() -> Generator[None, None, None]:
    IntegrationRegistry._plugins.clear()
    yield
    IntegrationRegistry._plugins.clear()


def test_discover_loads_all_entry_points(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_entry_points(group: str) -> Iterable[_FakeEntryPoint]:
        assert group == "label_hub.integrations"
        return [
            _FakeEntryPoint("alpha", _AlphaPlugin),
            _FakeEntryPoint("beta", _BetaPlugin),
        ]

    monkeypatch.setattr("importlib.metadata.entry_points", fake_entry_points)
    _discover_plugins()
    assert IntegrationRegistry.names() == ["alpha", "beta"]


def test_discover_with_no_entry_points_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("importlib.metadata.entry_points", lambda group: [])
    _discover_plugins()
    assert IntegrationRegistry.names() == []


def test_discover_rejects_non_plugin_class(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An entry point that loads something not satisfying IntegrationPlugin is logged + skipped."""
    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda group: [_FakeEntryPoint("bad", _NotAPlugin)],
    )
    with caplog.at_level("ERROR"):
        _discover_plugins()
    assert IntegrationRegistry.names() == []
    assert any("does not satisfy IntegrationPlugin" in r.message for r in caplog.records)
    # Error message must name the entry-point so users can find the broken package
    assert any("bad" in r.message for r in caplog.records)


def test_discover_handles_load_exception(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If ep.load() raises, the discovery logs the error and continues with the next plugin."""
    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda group: [
            _ExplodingEntryPoint("broken"),
            _FakeEntryPoint("alpha", _AlphaPlugin),
        ],
    )
    with caplog.at_level("ERROR"):
        _discover_plugins()
    # The good plugin still registered — bad one didn't kill the process
    assert IntegrationRegistry.names() == ["alpha"]
    assert any("broken" in r.message for r in caplog.records)


def test_discover_handles_duplicate_registration(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Two entry-points exporting plugins with the same name: log + skip the second."""

    class _AlphaDup:
        name = "alpha"
        display_name = "Alpha Duplicate"

        async def lookup(self, identifier: str) -> object:
            raise NotImplementedError

    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda group: [
            _FakeEntryPoint("alpha", _AlphaPlugin),
            _FakeEntryPoint("alpha-dup", _AlphaDup),
        ],
    )
    with caplog.at_level("ERROR"):
        _discover_plugins()
    # Registry has the first one; the second was skipped with an error
    assert IntegrationRegistry.names() == ["alpha"]
    assert any(
        "alpha-dup" in r.message or "already registered" in r.message
        for r in caplog.records
    )


def test_protocol_rejects_incomplete_class() -> None:
    """A class missing required attributes does not satisfy the Protocol.

    Carried forward from Phase 1 review feedback — verifies the negative
    half of the @runtime_checkable contract.
    """
    from app.integrations.base import IntegrationPlugin

    assert not isinstance(_NotAPlugin(), IntegrationPlugin)
