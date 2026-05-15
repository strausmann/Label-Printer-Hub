"""Smoke tests for the IntegrationPlugin Protocol."""

from typing import get_type_hints

from app.integrations.base import IntegrationPlugin


def test_protocol_is_runtime_checkable() -> None:
    """isinstance() must work — the registry uses it defensively."""

    class _Fake:
        name = "x"
        display_name = "X"

        async def lookup(self, identifier: str) -> object:
            return object()

    assert isinstance(_Fake(), IntegrationPlugin)


def test_protocol_requires_name_display_name_lookup() -> None:
    """Type hints declare the contract."""
    hints = get_type_hints(IntegrationPlugin)
    assert "name" in hints and hints["name"] is str
    assert "display_name" in hints and hints["display_name"] is str
