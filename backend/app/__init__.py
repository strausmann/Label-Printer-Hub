"""Label Printer Hub — backend application package."""

from __future__ import annotations

import importlib.metadata


def get_version() -> str:
    """Return the installed package version, or '0.0.0-dev' when running from source.

    The container build resolves this from the package metadata
    (`importlib.metadata.version`), which hatchling fills in from
    `pyproject.toml`'s `[project] version` at install time. In editable
    development installs the value is whatever the pyproject declares
    (typically ``"0.0.0-dev"``).
    """
    try:
        return importlib.metadata.version("label-printer-hub-backend")
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0-dev"


__version__: str = get_version()
