# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Shared exception base types for App-Lookup clients."""

from __future__ import annotations


class AppLookupNotFoundError(Exception):
    """Raised when an App-Lookup client cannot find the requested entity.

    All concrete not-found errors (SnipeITNotFoundError, GrocyNotFoundError,
    SpoolmanNotFoundError) inherit from this base so callers can catch any
    client's not-found in a single ``except AppLookupNotFoundError`` clause.
    """


class IntegrationNotConfiguredError(Exception):
    """Raised when a lookup targets an integration without URL (or key) in the settings."""


class LookupFailedError(Exception):
    """Resolving label data via an integration plugin failed.

    This is the umbrella exception for all lookup failures:

    - UnknownAppError: config mismatch (unknown app name)
    - LookupResponseTooLargeError: the upstream answer exceeded the size limit
    - Any runtime exception from a plugin is wrapped into this type

    The REST layer catches this single type to return HTTP 502. It lives here, not in
    ``lookup_service``, so the plugin base can raise subclasses without an import cycle;
    ``app.services.lookup_service`` re-exports it.
    """
