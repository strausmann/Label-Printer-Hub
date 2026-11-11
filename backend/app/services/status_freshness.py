"""How old a cached printer status may be before it is shown as unknown (#227).

The age is measured from ``printer_status_cache.updated_at``, the time of the last probe
*attempt* (an offline write keeps ``captured_at`` but still refreshes ``updated_at``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.services.producers.ipp_status_producer import MAX_BACKOFF_S

# An ``updated_at`` further ahead of the hub clock than this is a clock jump, not a fresh probe.
FUTURE_TOLERANCE_S = 60
_FLOOR_S = 90.0
_INTERVAL_MULTIPLE = 3.0


def stale_after_s(probe_interval_s: float, max_backoff_s: float = 0.0) -> float:
    """Seconds after which a status counts as stale.

    ``max(90, 3 * probe interval, 2 * max backoff)``: it must cover the producer's longest
    legitimate gap between two writes. A tape printer writes every interval; an IPP printer that
    stopped answering is written only after its failure backoff (60, 120, 240, then 300 s), so its
    rows pass the producer's ``MAX_BACKOFF_S``.
    """
    return max(_FLOOR_S, _INTERVAL_MULTIPLE * probe_interval_s, 2.0 * max_backoff_s)


def is_stale(
    updated_at: datetime, now: datetime, probe_interval_s: float, max_backoff_s: float = 0.0
) -> bool:
    """True when the last probe attempt is older than the bound or implausibly in the future."""
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    age_s = (now - updated_at).total_seconds()
    return age_s > stale_after_s(probe_interval_s, max_backoff_s) or age_s < -FUTURE_TOLERANCE_S


def backoff_of(parsed: dict[str, Any] | None) -> float:
    """The longest write gap of the producer behind a cache row: the IPP backoff for page rows."""
    return MAX_BACKOFF_S if (parsed or {}).get("kind") == "page" else 0.0
