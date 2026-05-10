"""Label Printer Hub — backend application package."""

from __future__ import annotations

import importlib.metadata


def get_version() -> str:
    """Return the installed package version, or '0.0.0-dev' when running from source.

    The container build pins this to the released version via the
    setup.py / pyproject.toml metadata; in development, the editable install
    keeps it at whatever the pyproject declares.
    """
    try:
        return importlib.metadata.version("label-printer-hub-backend")
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0-dev"


__version__: str = get_version()
