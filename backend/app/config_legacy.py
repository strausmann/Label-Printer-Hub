"""Environment prefix handling for the ``PRINTER_HUB_`` -> ``LABELYARD_`` rename.

The project is now called Labelyard and reads ``LABELYARD_*`` settings. Deployments that
still set only ``PRINTER_HUB_*`` keep working: the old prefix is read as a fallback and a
single deprecation warning names the variables that should be renamed (names only, never
values).

Source order in :meth:`app.config.Settings.settings_customise_sources`::

    init kwargs -> LABELYARD_ env -> LABELYARD_ .env
        -> PRINTER_HUB_ env -> PRINTER_HUB_ .env -> secrets

So a ``LABELYARD_`` variable always wins over its ``PRINTER_HUB_`` twin, and an empty
legacy value (``${PRINTER_HUB_X:-}`` in a compose file) never overrides anything.

``Settings`` keeps ``extra="forbid"``. Each dotenv reader would hand the keys of the *other*
prefix to pydantic as unknown extras and fail with ``Extra inputs are not permitted``, so
each reader drops the keys of the other prefix before pydantic sees them. Unknown keys with
the reader's *own* prefix are still rejected, exactly as before the rename.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic_settings import DotEnvSettingsSource, EnvSettingsSource

if TYPE_CHECKING:
    from pydantic_settings import BaseSettings

ENV_PREFIX = "LABELYARD_"
LEGACY_ENV_PREFIX = "PRINTER_HUB_"


class LegacyPrefixEnvSource(EnvSettingsSource):
    """``PRINTER_HUB_*`` process environment; empty values are ignored."""

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        super().__init__(settings_cls, env_prefix=LEGACY_ENV_PREFIX, env_ignore_empty=True)


class PrefixFilteredDotEnvSource(DotEnvSettingsSource):
    """``.env`` reader for the new prefix that drops every ``PRINTER_HUB_*`` key."""

    _other_prefix = LEGACY_ENV_PREFIX.lower()

    def _load_env_vars(self) -> Mapping[str, str | None]:
        return {
            key: value
            for key, value in super()._load_env_vars().items()
            if not key.lower().startswith(self._other_prefix)
        }


class LegacyPrefixDotEnvSource(DotEnvSettingsSource):
    """``.env`` reader for the old prefix; drops every ``LABELYARD_*`` key, ignores empties."""

    _other_prefix = ENV_PREFIX.lower()

    def __init__(self, settings_cls: type[BaseSettings], **kwargs: Any) -> None:
        super().__init__(
            settings_cls, env_prefix=LEGACY_ENV_PREFIX, env_ignore_empty=True, **kwargs
        )

    def _load_env_vars(self) -> Mapping[str, str | None]:
        return {
            key: value
            for key, value in super()._load_env_vars().items()
            if not key.lower().startswith(self._other_prefix)
        }


@dataclass(frozen=True)
class LegacyReport:
    """Variable names (never values) that still use the old prefix."""

    used: list[str] = field(default_factory=list)
    """Old names that take effect: non-empty and without a ``LABELYARD_`` twin."""
    shadowed: list[str] = field(default_factory=list)
    """Old names that are ignored because the ``LABELYARD_`` twin is set."""


def legacy_env_report(environ: Mapping[str, str], dotenv_keys: Iterable[str] = ()) -> LegacyReport:
    """Classify the ``PRINTER_HUB_*`` variables found in the environment and ``.env`` keys.

    ``dotenv_keys`` are the keys of the ``.env`` file that have a non-empty value.
    """
    env_names = {name.upper(): value for name, value in environ.items()}
    dotenv_names = {name.upper() for name in dotenv_keys}
    # An empty value counts as not set (Settings ignores it), so it shadows nothing.
    new_names = {n for n, v in env_names.items() if n.startswith(ENV_PREFIX) and v} | {
        n for n in dotenv_names if n.startswith(ENV_PREFIX)
    }

    used: set[str] = set()
    shadowed: set[str] = set()
    for name in (*env_names, *dotenv_names):
        if not name.startswith(LEGACY_ENV_PREFIX):
            continue
        twin = ENV_PREFIX + name[len(LEGACY_ENV_PREFIX) :]
        if twin in new_names:
            shadowed.add(name)
        elif name in env_names and env_names[name] == "":
            continue  # an empty process variable is ignored and, without a .env twin, unused
        else:
            used.add(name)
    return LegacyReport(used=sorted(used), shadowed=sorted(shadowed))


def warn_legacy_env(report: LegacyReport, logger: logging.Logger) -> None:
    """Log one warning per non-empty list. Names only; values never reach the log."""
    if report.used:
        logger.warning(
            "Deprecated %s* variables in use, rename them to %s*: %s",
            LEGACY_ENV_PREFIX,
            ENV_PREFIX,
            ", ".join(report.used),
        )
    if report.shadowed:
        logger.warning(
            "Ignored %s* variables, the %s* twin is set and wins: %s",
            LEGACY_ENV_PREFIX,
            ENV_PREFIX,
            ", ".join(report.shadowed),
        )


def report_from_process(env_file: str | os.PathLike[str] | None = ".env") -> LegacyReport:
    """Build the report from ``os.environ`` and the keys of ``env_file`` (if it exists)."""
    keys: list[str] = []
    if env_file is not None and Path(env_file).is_file():
        from dotenv import dotenv_values

        keys = [k for k, v in dotenv_values(env_file).items() if v]
    return legacy_env_report(os.environ, keys)


def setting_variable_label(field: str, report: LegacyReport) -> str:
    """Variable to fix for ``field``; names the legacy one when that is the one in use."""
    name = ENV_PREFIX + field.upper()
    legacy = LEGACY_ENV_PREFIX + field.upper()
    return f"{name} (legacy {legacy})" if legacy in report.used else name
