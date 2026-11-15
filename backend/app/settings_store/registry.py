# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Definition of every runtime setting: kind, default and the env field that locks it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Kind = Literal["str", "int", "float", "bool", "url", "secret", "enum"]


@dataclass(frozen=True)
class SettingDef:
    key: str
    kind: Kind
    default: Any
    env_field: str | None
    choices: tuple[str, ...] = ()


def _integration(
    name: str, *, secret: str | None, secret_env: str | None, timeout: float = 5.0
) -> list[SettingDef]:
    defs = [SettingDef(f"integrations.{name}.url", "url", "", f"{name}_url")]
    if secret is not None:
        defs.append(SettingDef(f"integrations.{name}.{secret}", "secret", "", secret_env))
    defs.append(SettingDef(f"integrations.{name}.timeout", "float", timeout, f"{name}_timeout"))
    return defs


_DEFS: list[SettingDef] = [
    SettingDef("general.display_name", "str", "Labelyard", None),
    SettingDef("general.language", "enum", "en", None, choices=("en", "de")),
    SettingDef("general.time_zone", "str", "UTC", None),
    # D4: shown read-only, always taken from the environment.
    SettingDef("general.public_url", "url", "", "public_url"),
    *_integration("snipeit", secret="api_key", secret_env="snipeit_api_key"),
    *_integration("grocy", secret="api_key", secret_env="grocy_api_key"),
    *_integration("spoolman", secret=None, secret_env=None),
    *_integration("paperless", secret="token", secret_env="paperless_token"),
    SettingDef("access.webhook_api_key", "secret", "", "webhook_api_key"),
    SettingDef("jobs.retention_days", "int", 30, "job_retention_days"),
]

SETTINGS: dict[str, SettingDef] = {d.key: d for d in _DEFS}

# Settings that are always locked, whatever the environment says (the field is required).
ALWAYS_LOCKED: frozenset[str] = frozenset({"general.public_url"})

INTEGRATIONS: tuple[str, ...] = ("snipeit", "grocy", "spoolman", "paperless")


def integration_url_key(name: str) -> str:
    return f"integrations.{name}.url"


def integration_secret_key(name: str) -> str | None:
    for suffix in ("api_key", "token"):
        key = f"integrations.{name}.{suffix}"
        if key in SETTINGS:
            return key
    return None
