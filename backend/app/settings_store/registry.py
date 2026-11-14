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


GROCY_LABEL_TYPES: tuple[str, ...] = ("product", "stock_entry", "chore", "battery", "recipe")
GROCY_LABEL_CONTENT_TYPES: tuple[str, ...] = (
    "qr_only",
    "qr_one_line",
    "qr_two_lines",
    "qr_three_lines",
)


GROCY_LABEL_DEFAULT_PRINTER_KEY = "integrations.grocy.label.printer"


def grocy_label_content_type_key(label_type: str) -> str:
    return f"integrations.grocy.label.{label_type}.content_type"


def grocy_label_printer_key(label_type: str) -> str:
    return f"integrations.grocy.label.{label_type}.printer"


def _grocy_label() -> list[SettingDef]:
    """#281 R-281-7: the Grocy label printer webhook, one content type and printer per type.

    Printers are printer slugs. A type's ``""`` uses the default target
    (``integrations.grocy.label.printer``), whose ``""`` is the first enabled tape printer
    (maintainer ruling on #281, 2026-11-14).
    """
    defs = [
        SettingDef("integrations.grocy.label.enabled", "bool", False, None),
        SettingDef(GROCY_LABEL_DEFAULT_PRINTER_KEY, "str", "", None),
    ]
    for label_type in GROCY_LABEL_TYPES:
        default = "qr_three_lines" if label_type == "stock_entry" else "qr_two_lines"
        defs.append(
            SettingDef(
                grocy_label_content_type_key(label_type),
                "enum",
                default,
                None,
                choices=GROCY_LABEL_CONTENT_TYPES,
            )
        )
        defs.append(SettingDef(grocy_label_printer_key(label_type), "str", "", None))
    return defs


_DEFS: list[SettingDef] = [
    SettingDef("general.display_name", "str", "Labelyard", None),
    SettingDef("general.language", "enum", "en", None, choices=("en", "de")),
    SettingDef("general.time_zone", "str", "UTC", None),
    # D4: shown read-only, always taken from the environment.
    SettingDef("general.public_url", "url", "", "public_url"),
    *_integration("snipeit", secret="api_key", secret_env="snipeit_api_key"),
    *_integration("grocy", secret="api_key", secret_env="grocy_api_key"),
    *_grocy_label(),
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
