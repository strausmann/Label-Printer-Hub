"""The staleness bound of a cached printer status (#227)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.status_freshness import FUTURE_TOLERANCE_S, is_stale, stale_after_s

NOW = datetime(2026, 11, 9, 12, 0, 0, tzinfo=UTC)


def test_stale_after_floor_and_multiple() -> None:
    assert stale_after_s(5) == 90
    assert stale_after_s(30) == 90
    assert stale_after_s(60) == 180


def test_is_stale_at_the_bound() -> None:
    assert not is_stale(NOW - timedelta(seconds=90), NOW, 30)
    assert is_stale(NOW - timedelta(seconds=91), NOW, 30)


def test_future_updated_at_is_stale() -> None:
    assert is_stale(NOW + timedelta(hours=1), NOW, 30)
    assert not is_stale(NOW + timedelta(seconds=FUTURE_TOLERANCE_S), NOW, 30)
    assert is_stale(NOW + timedelta(seconds=FUTURE_TOLERANCE_S + 1), NOW, 30)


def test_naive_updated_at_is_read_as_utc() -> None:
    naive = (NOW - timedelta(seconds=10)).replace(tzinfo=None)
    assert not is_stale(naive, NOW, 30)
    assert is_stale((NOW - timedelta(days=1)).replace(tzinfo=None), NOW, 30)
