"""Unit tests for IntegrationRegistry."""

import pytest
from app.integrations.base import IntegrationPlugin
from app.integrations.registry import IntegrationNotFoundError, IntegrationRegistry
from app.schemas.label_data import LabelData


class _FakePlugin:
    """Minimal IntegrationPlugin-shaped object for tests."""

    def __init__(self, name: str = "fake", display_name: str = "Fake") -> None:
        self.name = name
        self.display_name = display_name

    async def lookup(self, identifier: str) -> LabelData:
        return LabelData(
            title="fake", primary_id=identifier, qr_payload="x", source_app=self.name
        )


@pytest.fixture(autouse=True)
def _clear_registry() -> None:
    """Each test starts with an empty registry."""
    IntegrationRegistry._plugins.clear()


def test_register_stores_plugin() -> None:
    p = _FakePlugin()
    IntegrationRegistry.register(p)
    assert IntegrationRegistry.get("fake") is p


def test_register_rejects_empty_name() -> None:
    p = _FakePlugin(name="")
    with pytest.raises(ValueError, match="non-empty name"):
        IntegrationRegistry.register(p)


def test_register_rejects_duplicate() -> None:
    IntegrationRegistry.register(_FakePlugin())
    with pytest.raises(ValueError, match="already registered"):
        IntegrationRegistry.register(_FakePlugin())


def test_get_unknown_raises_not_found() -> None:
    with pytest.raises(IntegrationNotFoundError, match="Unknown integration 'nope'"):
        IntegrationRegistry.get("nope")


def test_all_returns_copy() -> None:
    IntegrationRegistry.register(_FakePlugin(name="a"))
    IntegrationRegistry.register(_FakePlugin(name="b"))
    snapshot = IntegrationRegistry.all()
    snapshot.clear()
    assert IntegrationRegistry.names() == ["a", "b"]


def test_names_returns_sorted() -> None:
    IntegrationRegistry.register(_FakePlugin(name="zeta"))
    IntegrationRegistry.register(_FakePlugin(name="alpha"))
    assert IntegrationRegistry.names() == ["alpha", "zeta"]


def test_runtime_protocol_check_accepts_fake() -> None:
    """The Protocol is structural — _FakePlugin implements it."""
    assert isinstance(_FakePlugin(), IntegrationPlugin)
