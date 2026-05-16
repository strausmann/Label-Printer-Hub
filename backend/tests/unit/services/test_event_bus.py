from __future__ import annotations

from datetime import UTC, datetime

from app.services.event_bus import BusEvent, EventBus


def _make_event(channel: str = "printer:abc:queue", eid: int = 1) -> BusEvent:
    return BusEvent(
        channel=channel,
        event_id=eid,
        event_type="job.state_changed",
        timestamp=datetime.now(UTC),
        data={
            "job_id": "x",
            "from_state": "queued",
            "to_state": "printing",
            "queue_depth": 0,
            "error_code": None,
        },
    )


def test_publish_reaches_subscriber() -> None:
    bus = EventBus(queue_size=8)
    q = bus.subscribe("printer:abc:queue", "sub-1")
    event = _make_event()
    bus.publish("printer:abc:queue", event)
    assert q.qsize() == 1
    assert q.get_nowait() is event


def test_multiple_subscribers_all_receive() -> None:
    bus = EventBus(queue_size=8)
    q1 = bus.subscribe("printer:abc:queue", "sub-1")
    q2 = bus.subscribe("printer:abc:queue", "sub-2")
    event = _make_event()
    bus.publish("printer:abc:queue", event)
    assert q1.get_nowait() is event
    assert q2.get_nowait() is event


def test_drop_oldest_when_full() -> None:
    bus = EventBus(queue_size=2)
    q = bus.subscribe("printer:abc:queue", "sub-1")
    e1 = _make_event(eid=1)
    e2 = _make_event(eid=2)
    e3 = _make_event(eid=3)
    bus.publish("printer:abc:queue", e1)
    bus.publish("printer:abc:queue", e2)
    # queue is full; e1 must be evicted
    bus.publish("printer:abc:queue", e3)
    assert q.qsize() == 2
    first = q.get_nowait()
    second = q.get_nowait()
    assert first is e2
    assert second is e3
    assert bus.get_dropped_count("sub-1") == 1


def test_unsubscribe_cleans_up() -> None:
    bus = EventBus(queue_size=8)
    q = bus.subscribe("printer:abc:queue", "sub-1")
    bus.unsubscribe("printer:abc:queue", "sub-1")
    bus.publish("printer:abc:queue", _make_event())
    assert q.qsize() == 0


def test_channel_isolation() -> None:
    bus = EventBus(queue_size=8)
    qa = bus.subscribe("printer:abc:queue", "sub-a")
    qb = bus.subscribe("printer:abc:state", "sub-b")
    bus.publish("printer:abc:queue", _make_event(channel="printer:abc:queue"))
    assert qa.qsize() == 1
    assert qb.qsize() == 0


def test_next_event_id_monotonic() -> None:
    bus = EventBus()
    ids = [bus.next_event_id("printer:abc:queue") for _ in range(100)]
    assert ids == list(range(1, 101))


def test_subscriber_count() -> None:
    bus = EventBus(queue_size=8)
    bus.subscribe("printer:abc:queue", "sub-1")
    bus.subscribe("printer:abc:queue", "sub-2")
    assert bus.subscriber_count("printer:abc:queue") == 2
    bus.unsubscribe("printer:abc:queue", "sub-1")
    assert bus.subscriber_count("printer:abc:queue") == 1


def test_total_subscriber_count() -> None:
    bus = EventBus(queue_size=8)
    bus.subscribe("printer:abc:queue", "sub-1")
    bus.subscribe("printer:abc:state", "sub-2")
    assert bus.total_subscriber_count() == 2


def test_unsubscribe_idempotent() -> None:
    bus = EventBus(queue_size=8)
    bus.subscribe("printer:abc:queue", "sub-1")
    bus.unsubscribe("printer:abc:queue", "sub-1")
    bus.unsubscribe("printer:abc:queue", "sub-1")  # second call must not raise
    assert bus.subscriber_count("printer:abc:queue") == 0


# ---------------------------------------------------------------------------
# Finding #8 — distinct_subscriber_count vs total_subscriber_count
# ---------------------------------------------------------------------------


def test_distinct_subscriber_count_counts_connections_not_channels() -> None:
    """distinct_subscriber_count() must count unique subscriber_ids, not channel subs.

    Bug (Finding #8): total_subscriber_count() summed all channel subscriptions.
    A single SSE connection subscribes to 3 channels with the same subscriber_id,
    so total_subscriber_count() returned 3 for 1 actual connection. The 429 cap
    check then allowed only 33 connections instead of 100.

    Fix: add distinct_subscriber_count() which counts unique subscriber_ids
    across all channels. total_subscriber_count() semantics are preserved for
    Prometheus channel-load metrics.
    """
    bus = EventBus(queue_size=8)
    # Simulate 2 SSE connections, each subscribing to 3 channels
    for ch in ("printer:abc:queue", "printer:abc:state", "printer:abc:tape"):
        bus.subscribe(ch, "conn-1")
        bus.subscribe(ch, "conn-2")

    # total_subscriber_count() counts all channel subscriptions (3 channels x 2 subs = 6)
    assert bus.total_subscriber_count() == 6

    # distinct_subscriber_count() counts unique subscriber_ids (2 connections)
    assert bus.distinct_subscriber_count() == 2


def test_distinct_subscriber_count_empty_bus_returns_zero() -> None:
    """distinct_subscriber_count() on an empty bus returns 0."""
    bus = EventBus(queue_size=8)
    assert bus.distinct_subscriber_count() == 0


def test_distinct_subscriber_count_after_unsubscribe() -> None:
    """After unsubscribing all channels for a subscriber, count drops."""
    bus = EventBus(queue_size=8)
    for ch in ("printer:abc:queue", "printer:abc:state", "printer:abc:tape"):
        bus.subscribe(ch, "conn-1")

    assert bus.distinct_subscriber_count() == 1

    for ch in ("printer:abc:queue", "printer:abc:state", "printer:abc:tape"):
        bus.unsubscribe(ch, "conn-1")

    assert bus.distinct_subscriber_count() == 0


# ---------------------------------------------------------------------------
# F5 — distinct_subscriber_count(channels=...) scoped to a channel subset
# ---------------------------------------------------------------------------


def test_distinct_subscriber_count_with_channels_returns_subset() -> None:
    """distinct_subscriber_count(channels=[...]) must count only the supplied
    channels (bot-review Finding F5).

    Two printers share the same bus.  conn-A subscribes to printer-1 only;
    conn-B subscribes to printer-2 only.  Counting with channels=printer-1-*
    must return 1 (conn-A), not 2.
    """
    bus = EventBus(queue_size=8)
    p1_channels = ["printer:p1:queue", "printer:p1:state", "printer:p1:tape"]
    p2_channels = ["printer:p2:queue", "printer:p2:state", "printer:p2:tape"]

    for ch in p1_channels:
        bus.subscribe(ch, "conn-A")
    for ch in p2_channels:
        bus.subscribe(ch, "conn-B")

    # Scoped to printer-1 channels → only conn-A
    assert bus.distinct_subscriber_count(channels=p1_channels) == 1
    # Scoped to printer-2 channels → only conn-B
    assert bus.distinct_subscriber_count(channels=p2_channels) == 1
    # No filter → both connections
    assert bus.distinct_subscriber_count() == 2


def test_distinct_subscriber_count_channels_empty_list_returns_zero() -> None:
    """An empty channels list has no subscribers → 0."""
    bus = EventBus(queue_size=8)
    bus.subscribe("printer:abc:queue", "conn-1")
    assert bus.distinct_subscriber_count(channels=[]) == 0


def test_distinct_subscriber_count_channels_none_equals_no_arg() -> None:
    """channels=None is equivalent to calling with no argument (full bus)."""
    bus = EventBus(queue_size=8)
    for ch in ("printer:abc:queue", "printer:abc:state", "printer:abc:tape"):
        bus.subscribe(ch, "conn-1")
        bus.subscribe(ch, "conn-2")
    assert bus.distinct_subscriber_count(channels=None) == bus.distinct_subscriber_count()
