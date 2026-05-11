"""Shared exception base types for App-Lookup clients."""

from __future__ import annotations


class AppLookupNotFoundError(Exception):
    """Raised when an App-Lookup client cannot find the requested entity.

    All concrete not-found errors (SnipeITNotFoundError, GrocyNotFoundError,
    SpoolmanNotFoundError) inherit from this base so callers can catch any
    client's not-found in a single ``except AppLookupNotFoundError`` clause.
    """
