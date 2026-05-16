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
