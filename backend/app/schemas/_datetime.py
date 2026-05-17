"""Helpers for datetime serialisation in Pydantic schemas.

The Go frontend's oapi-codegen client uses strict RFC3339 parsing which
rejects naive datetimes (no `Z` or `+HH:MM` suffix). This helper normalises
every datetime to a timezone-aware UTC value before serialisation.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any


def serialize_datetime_utc(dt: _dt.datetime, _info: Any) -> str:
    """Pydantic field-serializer: emit RFC3339 with `Z` for UTC values.

    - naive datetimes are treated as UTC (matches SQLite legacy behaviour)
    - UTC-aware datetimes are emitted with `Z`
    - non-UTC-aware datetimes keep their explicit offset
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.UTC)
    return dt.isoformat().replace("+00:00", "Z")
