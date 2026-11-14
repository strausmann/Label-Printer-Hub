# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

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


def test_stale_after_covers_the_ipp_backoff() -> None:
    assert stale_after_s(30, 300) == 600
    assert stale_after_s(30, 0) == 90
    assert stale_after_s(300, 100) == 900  # the interval multiple still wins when it is larger


def test_offline_ipp_gap_is_not_stale_with_the_backoff() -> None:
    assert not is_stale(NOW - timedelta(seconds=200), NOW, 30, 300)
    assert is_stale(NOW - timedelta(seconds=200), NOW, 30)  # a tape row of the same age
    assert is_stale(NOW - timedelta(seconds=601), NOW, 30, 300)
