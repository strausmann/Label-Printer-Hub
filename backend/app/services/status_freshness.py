"""How old a cached printer status may be before it is shown as unknown (#227).

The age is measured from ``printer_status_cache.updated_at``, the time of the last probe
*attempt* (an offline write keeps ``captured_at`` but still refreshes ``updated_at``).
"""

from __future__ import annotations

from datetime import UTC, datetime

# An ``updated_at`` further ahead of the hub clock than this is a clock jump, not a fresh probe.
FUTURE_TOLERANCE_S = 60
_FLOOR_S = 90.0
_INTERVAL_MULTIPLE = 3.0


def stale_after_s(probe_interval_s: float) -> float:
    """Seconds after which a status counts as stale: ``max(90, 3 * probe interval)``."""
    return max(_FLOOR_S, _INTERVAL_MULTIPLE * probe_interval_s)


def is_stale(updated_at: datetime, now: datetime, probe_interval_s: float) -> bool:
    """True when the last probe attempt is older than the bound or implausibly in the future."""
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    age_s = (now - updated_at).total_seconds()
    return age_s > stale_after_s(probe_interval_s) or age_s < -FUTURE_TOLERANCE_S
