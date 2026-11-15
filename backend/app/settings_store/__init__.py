# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Runtime settings store (D4: env wins; D5: secrets encrypted, write-only)."""

from app.settings_store.registry import SETTINGS, SettingDef
from app.settings_store.store import (
    InvalidSettingValueError,
    SecretRequiredForNewUrlError,
    SettingLockedError,
    SettingsError,
    SettingsStore,
    UnknownSettingError,
    UrlRequiredForSecretError,
)

__all__ = [
    "SETTINGS",
    "InvalidSettingValueError",
    "SecretRequiredForNewUrlError",
    "SettingDef",
    "SettingLockedError",
    "SettingsError",
    "SettingsStore",
    "UnknownSettingError",
    "UrlRequiredForSecretError",
]
