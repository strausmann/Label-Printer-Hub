"""Test helper: construct a plugin bound to an env-backed settings store."""

from __future__ import annotations

from app.security.secret_box import SecretBox
from app.settings_store import SettingsStore

_TEST_KEY = b"test-secret-key-0123456789abcdef"


def bound[P](plugin_cls: type[P]) -> P:
    """Instantiate ``plugin_cls`` and bind it to a store that reads the (patched) environment."""
    plugin = plugin_cls()
    plugin.bind(SettingsStore(SecretBox(_TEST_KEY)))  # type: ignore[attr-defined]
    return plugin


class NoopLive:
    """Mixin for fake plugins: satisfies the live-settings part of the protocol."""

    def bind(self, store: object) -> None:
        return None

    async def reconfigure(self) -> None:
        return None

    def is_configured(self) -> bool:
        return True
