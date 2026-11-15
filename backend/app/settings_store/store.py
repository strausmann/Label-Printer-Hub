# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Runtime settings store.

D4: an environment variable wins over a stored value; such a setting is *locked*.
D5: secrets are sealed with ``LABELYARD_SECRET_KEY`` and are write-only: the store
returns plaintext only inside the process, never through :meth:`SettingsStore.describe`.

A secret belonging to an integration is bound to the URL it was saved with and is only
used for that URL; pointing the integration somewhere else requires re-entering it.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.app_setting import AppSetting
from app.schemas.settings_api import SettingView
from app.security.secret_box import SecretBox, UndecryptableSecret, secret_box_from_settings
from app.settings_store.registry import (
    ALWAYS_LOCKED,
    INTEGRATIONS,
    SETTINGS,
    SettingDef,
    integration_secret_key,
    integration_url_key,
)

_log = logging.getLogger(__name__)


class SettingsError(Exception):
    """Base class; ``code`` is the machine-readable error code of the API."""

    code = "settings_error"

    def __init__(self, message: str, *, keys: list[str] | None = None) -> None:
        super().__init__(message)
        self.keys = keys or []


class UnknownSettingError(SettingsError):
    code = "unknown_setting"


class InvalidSettingValueError(SettingsError):
    code = "invalid_value"


class SettingLockedError(SettingsError):
    code = "setting_locked"


class UrlRequiredForSecretError(SettingsError):
    code = "url_required_for_secret"


class SecretRequiredForNewUrlError(SettingsError):
    code = "secret_required_for_new_url"


def _norm_url(url: str) -> str:
    return url.strip().rstrip("/")


def _strip_userinfo(url: str) -> str:
    """Remove ``user:pass@`` from a URL before it is shown anywhere."""
    try:
        parts = urlsplit(url)
        if parts.username is None and parts.password is None:
            return url
        host = parts.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        netloc = host if parts.port is None else f"{host}:{parts.port}"
        return parts._replace(netloc=netloc).geturl()
    except ValueError:
        return ""


def _validate(d: SettingDef, value: Any) -> Any:
    """Return the normalised value or raise; the message never contains the value."""

    def bad(msg: str) -> InvalidSettingValueError:
        return InvalidSettingValueError(f"{d.key}: {msg}", keys=[d.key])

    kind = d.kind
    if kind == "bool":
        if not isinstance(value, bool):
            raise bad("expected a boolean")
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise bad("expected an integer")
        if d.key == "jobs.retention_days" and not 1 <= value <= 3650:
            raise bad("must be between 1 and 3650")
        return value
    if kind == "float":
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise bad("expected a number")
        if not 0 < value <= 300:
            raise bad("must be greater than 0 and at most 300")
        return float(value)
    if not isinstance(value, str):
        raise bad("expected a string")
    if kind == "secret":
        # Printable ASCII only: the value ends up in an HTTP header.
        if len(value) > 4096 or any(not 0x20 <= ord(c) <= 0x7E for c in value):
            raise bad("must be printable ASCII")
        if d.key == "access.webhook_api_key":
            value = value.strip()
            if value and len(value) < 32:
                raise bad("must be empty or at least 32 characters")
        return value
    text = value.strip()
    if kind == "enum":
        if text not in d.choices:
            raise bad("must be one of: " + ", ".join(d.choices))
        return text
    if kind == "url":
        if text == "":
            return ""
        try:
            parts = urlsplit(text)
            host = parts.hostname
            _ = parts.port
        except ValueError:
            raise bad("not a valid URL") from None
        if parts.scheme not in ("http", "https") or not host or len(text) > 2048:
            raise bad("must be an http(s) URL")
        if parts.username is not None or parts.password is not None:
            raise bad("credentials in the URL are not allowed")
        if any(c.isspace() for c in text):
            raise bad("not a valid URL")
        return _norm_url(text)
    # str
    if len(text) > 256:
        raise bad("too long")
    if d.key == "general.time_zone":
        try:
            ZoneInfo(text)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            raise bad("unknown time zone") from None
    return text


class SettingsStore:
    def __init__(self, box: SecretBox | None = None) -> None:
        self._box = box
        self._values: dict[str, Any] = {}
        self._secrets: dict[str, str] = {}
        self._bound: dict[str, str] = {}
        self._secret_present: set[str] = set()
        self._undecryptable: set[str] = set()
        self._subscribers: list[Callable[[set[str]], None]] = []

    # -- plumbing -----------------------------------------------------------

    def _get_box(self) -> SecretBox:
        if self._box is None:
            self._box = secret_box_from_settings(get_settings())
        return self._box

    def subscribe(self, callback: Callable[[set[str]], None]) -> None:
        self._subscribers.append(callback)

    def _notify(self, keys: set[str]) -> None:
        for cb in list(self._subscribers):
            try:
                cb(set(keys))
            except Exception:
                _log.exception("settings subscriber failed")

    # -- env ----------------------------------------------------------------

    def _env_raw(self, d: SettingDef) -> Any:
        assert d.env_field is not None
        value = getattr(get_settings(), d.env_field)
        if isinstance(value, SecretStr):
            return value.get_secret_value()
        if d.kind == "url":
            return str(value)
        return value

    def is_locked(self, key: str) -> bool:
        d = SETTINGS[key]
        if key in ALWAYS_LOCKED:
            return True
        if d.env_field is None:
            return False
        settings = get_settings()
        if d.env_field not in settings.model_fields_set:
            return False
        raw = self._env_raw(d)
        # `${VAR:-}` in compose yields an empty value; it must not lock the field.
        return not (isinstance(raw, str) and raw.strip() == "")

    # -- reading ------------------------------------------------------------

    def get(self, key: str) -> Any:
        d = SETTINGS[key]
        if d.kind == "secret":
            return self._secret_value(key)
        if self.is_locked(key):
            return self._env_raw(d)
        return self._values.get(key, d.default)

    def _secret_value(self, key: str) -> str:
        """Plaintext of a secret, only if it may be sent to the effective URL (S1/S2)."""
        d = SETTINGS[key]
        url_key = self._url_key_for(key)
        if self.is_locked(key):
            # An environment secret is only usable together with an environment URL.
            if url_key is not None and not self.is_locked(url_key):
                return ""
            return str(self._env_raw(d))
        plain = self._secrets.get(key, "")
        if url_key is None or not plain:
            return plain
        bound = self._bound.get(key, "")
        current = _norm_url(str(self.get(url_key)))
        # Missing binding = deny.
        return plain if bound and bound == current else ""

    def describe(self) -> list[SettingView]:
        views: list[SettingView] = []
        for key, d in SETTINGS.items():
            locked = self.is_locked(key)
            if d.kind == "secret":
                is_set = bool(self._env_raw(d)) if locked else key in self._secret_present
                value: Any = None
            else:
                is_set = locked or key in self._values
                value = self.get(key)
                if d.kind == "url" and isinstance(value, str):
                    value = _strip_userinfo(value)
            state = "ok"
            if key in self._undecryptable and not locked:
                state = "undecryptable"
            elif d.kind == "secret" and locked:
                url_key = self._url_key_for(key)
                if url_key is not None and not self.is_locked(url_key) and self._env_raw(d):
                    state = "env_secret_needs_env_url"
            views.append(
                SettingView(
                    key=key,
                    kind=d.kind,
                    value=value,
                    is_set=is_set,
                    locked=locked,
                    state=state,  # type: ignore[arg-type]
                    choices=list(d.choices),
                )
            )
        return views

    # -- loading ------------------------------------------------------------

    async def load(self, session: AsyncSession) -> None:
        values: dict[str, Any] = {}
        secrets: dict[str, str] = {}
        bound: dict[str, str] = {}
        present: set[str] = set()
        undecryptable: set[str] = set()
        rows = (await session.execute(select(AppSetting))).scalars().all()
        for row in rows:
            d = SETTINGS.get(row.key)
            if d is None:
                continue
            if d.kind == "secret":
                if not row.secret_token:
                    continue
                present.add(row.key)
                bound[row.key] = _norm_url(self._bound_from_row(row))
                try:
                    secrets[row.key] = self._get_box().open(row.secret_token, aad=row.key)
                except UndecryptableSecret:
                    undecryptable.add(row.key)
                    _log.warning("stored secret %s cannot be decrypted", row.key)
                continue
            if row.value_json is None:
                continue
            try:
                values[row.key] = _validate(d, json.loads(row.value_json))
            except (ValueError, SettingsError):
                _log.warning("ignoring invalid stored setting %s", row.key)
        self._values, self._secrets, self._bound = values, secrets, bound
        self._secret_present, self._undecryptable = present, undecryptable

    @staticmethod
    def _bound_from_row(row: AppSetting) -> str:
        try:
            data = json.loads(row.value_json or "{}")
            url = data.get("bound_url", "") if isinstance(data, dict) else ""
            return url if isinstance(url, str) else ""
        except ValueError:
            return ""

    # -- secret / URL binding -----------------------------------------------

    def _bound_url_of(self, secret_key: str) -> str | None:
        """URL a stored secret is bound to; None when no stored secret exists.

        An environment secret has no stored binding here: it is usable only with an
        environment URL, see :meth:`_secret_value`.
        """
        if self.is_locked(secret_key) or secret_key not in self._secret_present:
            return None
        return self._bound.get(secret_key, "")

    @staticmethod
    def _url_key_for(secret_key: str) -> str | None:
        for name in INTEGRATIONS:
            if integration_secret_key(name) == secret_key:
                return integration_url_key(name)
        return None

    def _check_binding(self, secret_key: str, new_url: str) -> None:
        if not new_url:
            return
        bound = self._bound_url_of(secret_key)
        if bound is not None and bound != new_url:
            raise SecretRequiredForNewUrlError(
                "the URL changed; enter the secret again so it is only sent to the new URL",
                keys=[secret_key],
            )

    # -- writing ------------------------------------------------------------

    async def set_many(self, session: AsyncSession, values: dict[str, Any]) -> None:
        unknown = [k for k in values if k not in SETTINGS]
        if unknown:
            raise UnknownSettingError("unknown setting key", keys=sorted(unknown))
        locked = [k for k in values if self.is_locked(k)]
        if locked:
            raise SettingLockedError("setting is set by the environment", keys=sorted(locked))

        clean: dict[str, Any] = {}
        for key, value in values.items():
            d = SETTINGS[key]
            if value is None and d.kind != "secret":
                clean[key] = None  # reset to default
            else:
                clean[key] = _validate(d, value)

        # A secret goes only to the URL it was saved with.
        for name in INTEGRATIONS:
            url_key, sec_key = integration_url_key(name), integration_secret_key(name)
            if url_key in clean and sec_key and sec_key not in clean:
                new_url = clean[url_key] or ""
                self._check_binding(sec_key, new_url)

        for key, value in clean.items():
            pair_key = self._url_key_for(key)
            if pair_key is not None and value not in ("", None):
                effective = clean[pair_key] if pair_key in clean else self.get(pair_key)
                if not _norm_url(str(effective or "")):
                    raise UrlRequiredForSecretError(
                        "set the integration URL first; a secret is bound to its URL",
                        keys=[key],
                    )

        now = datetime.now(UTC)
        sealed: dict[str, tuple[str, str]] = {}
        for key, value in clean.items():
            d = SETTINGS[key]
            if d.kind == "secret" and value != "":
                paired_url_key = self._url_key_for(key)
                if paired_url_key is None:
                    bound_url = ""
                elif paired_url_key in clean:
                    bound_url = clean[paired_url_key] or ""
                else:
                    bound_url = _norm_url(str(self.get(paired_url_key)))
                sealed[key] = (self._get_box().seal(value, aad=key), bound_url)

        try:
            for key, value in clean.items():
                d = SETTINGS[key]
                row = await session.get(AppSetting, key)
                if d.kind == "secret":
                    if value == "":
                        if row is not None:
                            await session.delete(row)
                        continue
                    token, bound_url = sealed[key]
                    payload = json.dumps({"bound_url": bound_url})
                    if row is None:
                        session.add(
                            AppSetting(
                                key=key, value_json=payload, secret_token=token, updated_at=now
                            )
                        )
                    else:
                        row.value_json, row.secret_token, row.updated_at = payload, token, now
                    continue
                if value is None:
                    if row is not None:
                        await session.delete(row)
                    continue
                payload = json.dumps(value)
                if row is None:
                    session.add(AppSetting(key=key, value_json=payload, updated_at=now))
                else:
                    row.value_json, row.updated_at = payload, now
            await session.commit()
        except Exception:
            await session.rollback()
            raise

        for key, value in clean.items():
            d = SETTINGS[key]
            if d.kind == "secret":
                self._undecryptable.discard(key)
                if value == "":
                    self._secrets.pop(key, None)
                    self._bound.pop(key, None)
                    self._secret_present.discard(key)
                else:
                    self._secrets[key] = value
                    self._bound[key] = sealed[key][1]
                    self._secret_present.add(key)
            elif value is None:
                self._values.pop(key, None)
            else:
                self._values[key] = value
        self._notify(set(clean))

    # -- test connection ----------------------------------------------------

    def resolve_probe(self, name: str, form: dict[str, Any]) -> tuple[str, str, float]:
        """Merge unsaved form values over the effective ones: ``(url, secret, timeout)``.

        Raises :class:`SecretRequiredForNewUrlError` when a stored (or environment) secret
        would be sent to a URL it was not saved with; nothing is sent in that case.
        """
        prefix = f"integrations.{name}."
        url_key, sec_key = integration_url_key(name), integration_secret_key(name)
        timeout_key = f"{prefix}timeout"
        for key in form:
            if key not in SETTINGS:
                raise UnknownSettingError("unknown setting key", keys=[key])
            if not key.startswith(prefix):
                raise InvalidSettingValueError(
                    f"{key}: does not belong to integration {name}", keys=[key]
                )

        def pick(key: str) -> Any:
            if key in form and not self.is_locked(key):
                return _validate(SETTINGS[key], form[key])
            return self.get(key)

        url = _norm_url(str(pick(url_key) or ""))
        timeout = float(pick(timeout_key))
        secret = ""
        if sec_key:
            if sec_key in form and not self.is_locked(sec_key):
                secret = _validate(SETTINGS[sec_key], form[sec_key])
            elif self.is_locked(sec_key):
                if not self.is_locked(url_key):
                    # Environment secret without an environment URL: unconfigured.
                    raise SecretRequiredForNewUrlError(
                        "the secret comes from the environment; set the URL there too",
                        keys=[sec_key],
                    )
                secret = str(self._env_raw(SETTINGS[sec_key]))
            else:
                self._check_binding(sec_key, url)
                secret = self._secrets.get(sec_key, "")
        return url, secret, timeout
