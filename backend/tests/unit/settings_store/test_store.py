"""Unit tests for the runtime settings store (D4 env locks, D5 encrypted secrets)."""

from __future__ import annotations

import base64
import json

import pytest
from app.config import get_settings
from app.models.app_setting import AppSetting
from app.security.secret_box import SecretBox
from app.settings_store import (
    SETTINGS,
    InvalidSettingValueError,
    SecretRequiredForNewUrlError,
    SettingLockedError,
    SettingsStore,
    UnknownSettingError,
    UrlRequiredForSecretError,
)
from sqlalchemy import select

KEY_A = b"test-secret-key-0123456789abcdef"
KEY_B = b"other-secret-key-0123456789abcde"
FAKE_TOKEN = "fake-token-value-for-tests"
GROCY_URL = "https://grocy.example.invalid"
WITH_URL = {"integrations.grocy.url": GROCY_URL}


@pytest.fixture(autouse=True)
def _fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def store() -> SettingsStore:
    return SettingsStore(SecretBox(KEY_A))


async def _raw_rows(factory):
    async with factory() as s:
        return {r.key: r for r in (await s.execute(select(AppSetting))).scalars()}


def test_registry_has_exactly_the_specified_keys() -> None:
    assert set(SETTINGS) == {
        "general.display_name",
        "general.language",
        "general.time_zone",
        "general.public_url",
        "integrations.snipeit.url",
        "integrations.snipeit.api_key",
        "integrations.snipeit.timeout",
        "integrations.grocy.url",
        "integrations.grocy.api_key",
        "integrations.grocy.timeout",
        "integrations.spoolman.url",
        "integrations.spoolman.timeout",
        "integrations.paperless.url",
        "integrations.paperless.token",
        "integrations.paperless.timeout",
        "access.webhook_api_key",
        "jobs.retention_days",
    }
    assert SETTINGS["general.language"].choices == ("en", "de")
    assert SETTINGS["jobs.retention_days"].default == 30


async def test_defaults_without_env(store, async_session_factory) -> None:
    async with async_session_factory() as s:
        await store.load(s)
    assert store.get("general.display_name") == "Label Printer Hub"
    assert store.get("general.language") == "en"
    assert store.get("jobs.retention_days") == 30
    assert store.is_locked("integrations.snipeit.url") is False


async def test_locked_when_env_set(monkeypatch, store, async_session_factory) -> None:
    monkeypatch.setenv("LABELYARD_SNIPEIT_URL", "https://snipeit.example.invalid")
    get_settings.cache_clear()
    async with async_session_factory() as s:
        await store.load(s)
        assert store.is_locked("integrations.snipeit.url")
        with pytest.raises(SettingLockedError):
            await store.set_many(s, {"integrations.snipeit.url": "https://other.example.invalid"})
    assert store.get("integrations.snipeit.url") == "https://snipeit.example.invalid"


async def test_empty_env_value_does_not_lock(monkeypatch, store, async_session_factory) -> None:
    monkeypatch.setenv("LABELYARD_SNIPEIT_URL", "")
    get_settings.cache_clear()
    assert "snipeit_url" in get_settings().model_fields_set
    assert store.is_locked("integrations.snipeit.url") is False
    async with async_session_factory() as s:
        await store.set_many(s, {"integrations.snipeit.url": "https://snipeit.example.invalid"})
    assert store.get("integrations.snipeit.url") == "https://snipeit.example.invalid"


def test_public_url_is_always_locked(store) -> None:
    assert store.is_locked("general.public_url")
    assert store.get("general.public_url").startswith("http://localhost:8000")


async def test_value_set_after_env_is_ignored_when_locked(
    monkeypatch, store, async_session_factory
) -> None:
    async with async_session_factory() as s:
        await store.set_many(s, {"jobs.retention_days": 10})
    assert store.get("jobs.retention_days") == 10
    monkeypatch.setenv("LABELYARD_JOB_RETENTION_DAYS", "45")
    get_settings.cache_clear()
    assert store.get("jobs.retention_days") == 45


async def test_values_survive_reload(store, async_session_factory) -> None:
    async with async_session_factory() as s:
        await store.set_many(s, {"general.display_name": "Hub 1", "general.language": "de"})
    fresh = SettingsStore(SecretBox(KEY_A))
    async with async_session_factory() as s:
        await fresh.load(s)
    assert fresh.get("general.display_name") == "Hub 1"
    assert fresh.get("general.language") == "de"


async def test_none_resets_to_default(store, async_session_factory) -> None:
    async with async_session_factory() as s:
        await store.set_many(s, {"general.display_name": "Hub 1"})
        await store.set_many(s, {"general.display_name": None})
    assert store.get("general.display_name") == "Label Printer Hub"
    assert "general.display_name" not in await _raw_rows(async_session_factory)


async def test_secret_stored_encrypted_and_never_described(store, async_session_factory) -> None:
    async with async_session_factory() as s:
        await store.set_many(s, {**WITH_URL, "integrations.grocy.api_key": FAKE_TOKEN})
    row = (await _raw_rows(async_session_factory))["integrations.grocy.api_key"]
    assert row.secret_token is not None
    assert FAKE_TOKEN not in row.secret_token
    assert FAKE_TOKEN not in (row.value_json or "")
    assert row.secret_token.startswith("v1.")
    assert store.get("integrations.grocy.api_key") == FAKE_TOKEN
    view = next(v for v in store.describe() if v.key == "integrations.grocy.api_key")
    assert view.value is None and view.is_set is True
    assert FAKE_TOKEN not in json.dumps([v.model_dump() for v in store.describe()])


async def test_secret_empty_string_clears(store, async_session_factory) -> None:
    async with async_session_factory() as s:
        await store.set_many(s, {**WITH_URL, "integrations.grocy.api_key": FAKE_TOKEN})
        await store.set_many(s, {"integrations.grocy.api_key": ""})
    assert store.get("integrations.grocy.api_key") == ""
    assert "integrations.grocy.api_key" not in await _raw_rows(async_session_factory)
    view = next(v for v in store.describe() if v.key == "integrations.grocy.api_key")
    assert view.is_set is False


async def test_undecryptable_secret_reported(store, async_session_factory) -> None:
    async with async_session_factory() as s:
        await store.set_many(s, {**WITH_URL, "integrations.grocy.api_key": FAKE_TOKEN})
    other = SettingsStore(SecretBox(KEY_B))
    async with async_session_factory() as s:
        await other.load(s)
    view = next(v for v in other.describe() if v.key == "integrations.grocy.api_key")
    assert view.state == "undecryptable"
    assert view.is_set is True
    assert other.get("integrations.grocy.api_key") == ""


async def test_secret_cannot_be_moved_to_another_key(store, async_session_factory) -> None:
    async with async_session_factory() as s:
        await store.set_many(s, {**WITH_URL, "integrations.grocy.api_key": FAKE_TOKEN})
        row = await s.get(AppSetting, "integrations.grocy.api_key")
        s.add(
            AppSetting(
                key="integrations.snipeit.api_key",
                value_json=row.value_json,
                secret_token=row.secret_token,
            )
        )
        await s.commit()
    fresh = SettingsStore(SecretBox(KEY_A))
    async with async_session_factory() as s:
        await fresh.load(s)
    assert fresh.get("integrations.snipeit.api_key") == ""
    view = next(v for v in fresh.describe() if v.key == "integrations.snipeit.api_key")
    assert view.state == "undecryptable"


async def test_unknown_key(store, async_session_factory) -> None:
    async with async_session_factory() as s:
        with pytest.raises(UnknownSettingError):
            await store.set_many(s, {"nope.nothing": 1})


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("jobs.retention_days", "x"),
        ("jobs.retention_days", True),
        ("jobs.retention_days", 0),
        ("integrations.grocy.timeout", "5"),
        ("integrations.grocy.timeout", 0),
        ("general.language", "fr"),
        ("general.time_zone", "Mars/Olympus"),
        ("integrations.grocy.api_key", 5),
        ("integrations.grocy.api_key", "a\nb"),
        ("integrations.grocy.url", "ftp://grocy.example.invalid"),
        ("integrations.grocy.url", "https://u:p@grocy.example.invalid"),
        ("integrations.grocy.url", "https://user@grocy.example.invalid"),
        ("integrations.grocy.url", 5),
    ],
)
async def test_wrong_type_rejected(store, async_session_factory, key, value) -> None:
    async with async_session_factory() as s:
        with pytest.raises(InvalidSettingValueError):
            await store.set_many(s, {key: value})
    assert await _raw_rows(async_session_factory) == {}


async def test_invalid_value_message_never_contains_the_value(store, async_session_factory) -> None:
    async with async_session_factory() as s:
        with pytest.raises(InvalidSettingValueError) as ei:
            await store.set_many(s, {"integrations.grocy.api_key": 123456789})
    assert "123456789" not in str(ei.value)


async def test_batch_is_atomic_when_one_value_is_invalid(store, async_session_factory) -> None:
    async with async_session_factory() as s:
        with pytest.raises(InvalidSettingValueError):
            await store.set_many(s, {"general.display_name": "ok", "jobs.retention_days": "x"})
    assert await _raw_rows(async_session_factory) == {}
    assert store.get("general.display_name") == "Label Printer Hub"


async def test_subscribe_called_with_changed_keys(store, async_session_factory) -> None:
    seen: list[set[str]] = []
    store.subscribe(seen.append)
    async with async_session_factory() as s:
        await store.set_many(s, {"general.display_name": "X", "jobs.retention_days": 5})
    assert seen == [{"general.display_name", "jobs.retention_days"}]


async def test_failing_subscriber_does_not_break_set(store, async_session_factory) -> None:
    def boom(_keys: set[str]) -> None:
        raise RuntimeError("boom")

    store.subscribe(boom)
    async with async_session_factory() as s:
        await store.set_many(s, {"general.display_name": "X"})
    assert store.get("general.display_name") == "X"


async def test_changing_url_requires_secret(store, async_session_factory) -> None:
    async with async_session_factory() as s:
        await store.set_many(
            s,
            {
                "integrations.grocy.url": "https://grocy.example.invalid",
                "integrations.grocy.api_key": FAKE_TOKEN,
            },
        )
        with pytest.raises(SecretRequiredForNewUrlError):
            await store.set_many(s, {"integrations.grocy.url": "https://evil.example.invalid"})
        # same URL (trailing slash is not a change) without token is fine
        await store.set_many(s, {"integrations.grocy.url": "https://grocy.example.invalid/"})
        # new URL with the secret re-entered is fine and rebinds the secret
        await store.set_many(
            s,
            {
                "integrations.grocy.url": "https://grocy2.example.invalid",
                "integrations.grocy.api_key": FAKE_TOKEN,
            },
        )
    assert store.get("integrations.grocy.url") == "https://grocy2.example.invalid"
    assert store.get("integrations.grocy.api_key") == FAKE_TOKEN


async def test_clearing_url_or_secret_needs_no_secret(store, async_session_factory) -> None:
    async with async_session_factory() as s:
        await store.set_many(
            s,
            {
                "integrations.grocy.url": "https://grocy.example.invalid",
                "integrations.grocy.api_key": FAKE_TOKEN,
            },
        )
        await store.set_many(s, {"integrations.grocy.url": ""})
        await store.set_many(
            s,
            {
                "integrations.grocy.url": "https://other.example.invalid",
                "integrations.grocy.api_key": "",
            },
        )
    assert store.get("integrations.grocy.api_key") == ""


async def test_secret_alone_binds_to_current_url(store, async_session_factory) -> None:
    async with async_session_factory() as s:
        await store.set_many(s, {"integrations.paperless.url": "https://p.example.invalid"})
        await store.set_many(s, {"integrations.paperless.token": FAKE_TOKEN})
        with pytest.raises(SecretRequiredForNewUrlError):
            await store.set_many(s, {"integrations.paperless.url": "https://q.example.invalid"})


def test_resolve_probe_uses_form_over_effective(store) -> None:
    url, secret, timeout = store.resolve_probe(
        "grocy",
        {
            "integrations.grocy.url": "https://grocy.example.invalid/",
            "integrations.grocy.api_key": FAKE_TOKEN,
            "integrations.grocy.timeout": 2,
        },
    )
    assert (url, secret, timeout) == ("https://grocy.example.invalid", FAKE_TOKEN, 2.0)


def test_resolve_probe_rejects_foreign_keys(store) -> None:
    with pytest.raises(InvalidSettingValueError):
        store.resolve_probe("grocy", {"integrations.snipeit.url": "https://x.example.invalid"})


async def test_env_secret_with_ui_url_is_never_sent(
    monkeypatch, store, async_session_factory
) -> None:
    """S1: an env secret must not follow a URL that the UI can change."""
    monkeypatch.setenv("LABELYARD_GROCY_API_KEY", FAKE_TOKEN)
    get_settings.cache_clear()
    async with async_session_factory() as s:
        await store.set_many(s, WITH_URL)
    assert store.get("integrations.grocy.api_key") == ""
    view = next(v for v in store.describe() if v.key == "integrations.grocy.api_key")
    assert view.state == "env_secret_needs_env_url" and view.is_set is True
    for form in ({}, {"integrations.grocy.url": "https://evil.example.invalid"}):
        with pytest.raises(SecretRequiredForNewUrlError):
            store.resolve_probe("grocy", form)


async def test_env_secret_with_env_url_is_usable(monkeypatch, store) -> None:
    monkeypatch.setenv("LABELYARD_GROCY_API_KEY", FAKE_TOKEN)
    monkeypatch.setenv("LABELYARD_GROCY_URL", GROCY_URL)
    get_settings.cache_clear()
    assert store.get("integrations.grocy.api_key") == FAKE_TOKEN
    # the locked URL wins over a form URL, so the secret still only goes to the env URL
    url, secret, _ = store.resolve_probe(
        "grocy", {"integrations.grocy.url": "https://evil.example.invalid"}
    )
    assert (url, secret) == (GROCY_URL, FAKE_TOKEN)
    view = next(v for v in store.describe() if v.key == "integrations.grocy.api_key")
    assert view.state == "ok"


async def test_secret_without_url_rejected(store, async_session_factory) -> None:
    """S2: no secret can be saved while no URL is effective."""
    async with async_session_factory() as s:
        with pytest.raises(UrlRequiredForSecretError):
            await store.set_many(s, {"integrations.grocy.api_key": FAKE_TOKEN})
        with pytest.raises(UrlRequiredForSecretError):
            await store.set_many(
                s, {"integrations.grocy.url": "", "integrations.grocy.api_key": FAKE_TOKEN}
            )
    assert await _raw_rows(async_session_factory) == {}


async def test_stored_secret_without_binding_is_denied(store, async_session_factory) -> None:
    """A legacy row without a binding is never returned or probed."""
    async with async_session_factory() as s:
        await store.set_many(s, WITH_URL)
        s.add(
            AppSetting(
                key="integrations.grocy.api_key",
                secret_token=SecretBox(KEY_A).seal(FAKE_TOKEN, aad="integrations.grocy.api_key"),
                value_json='{"bound_url": ""}',
            )
        )
        await s.commit()
    fresh = SettingsStore(SecretBox(KEY_A))
    async with async_session_factory() as s:
        await fresh.load(s)
    assert fresh.get("integrations.grocy.api_key") == ""
    with pytest.raises(SecretRequiredForNewUrlError):
        fresh.resolve_probe("grocy", {})


async def test_secret_only_returned_for_its_bound_url(store, async_session_factory) -> None:
    async with async_session_factory() as s:
        await store.set_many(s, {**WITH_URL, "integrations.grocy.api_key": FAKE_TOKEN})
        await store.set_many(s, {"integrations.grocy.url": ""})
        assert store.get("integrations.grocy.api_key") == ""  # no URL: nothing is sent
        with pytest.raises(SecretRequiredForNewUrlError):
            await store.set_many(s, {"integrations.grocy.url": "https://other.example.invalid"})
    async with async_session_factory() as s:
        await store.set_many(s, WITH_URL)  # back to the bound URL: usable again
    assert store.get("integrations.grocy.api_key") == FAKE_TOKEN


@pytest.mark.parametrize("secret", ["tëst-token", "tok\u00e9n", "bad\ttab", "emoji-\U0001f600"])
async def test_non_ascii_secret_rejected(store, async_session_factory, secret) -> None:
    async with async_session_factory() as s:
        with pytest.raises(InvalidSettingValueError) as ei:
            await store.set_many(s, {**WITH_URL, "integrations.grocy.api_key": secret})
    assert secret not in str(ei.value)


async def test_describe_strips_userinfo_from_env_url(monkeypatch, store) -> None:
    monkeypatch.setenv(
        "LABELYARD_SNIPEIT_URL", "https://user:pw-secret@snipeit.example.invalid:8443/x"
    )
    get_settings.cache_clear()
    view = next(v for v in store.describe() if v.key == "integrations.snipeit.url")
    assert view.value == "https://snipeit.example.invalid:8443/x"
    assert "pw-secret" not in json.dumps([v.model_dump() for v in store.describe()])


def test_key_constants_decode_to_32_bytes() -> None:
    assert len(KEY_A) == len(KEY_B) == 32
    assert base64.urlsafe_b64encode(KEY_A).decode().startswith("dGVzdC1z")
