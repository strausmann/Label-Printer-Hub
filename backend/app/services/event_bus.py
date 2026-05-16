"""In-process asyncio pub/sub EventBus.

All publishers and the SSE endpoint run in the same asyncio event loop, so
no thread-safety primitives are needed. ``publish`` is intentionally
synchronous (not ``async def``) so producers never yield to the event loop
mid-publish and never block waiting for a slow subscriber.

Drop-oldest backpressure: when a subscriber queue is full the oldest item is
discarded and the new event is appended. This ensures a reconnecting client
always receives the current state rather than a storm of stale transitions.

Thread-safety: NOT thread-safe. Callers must operate from the same event loop.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BusEvent:
    """Wire-level event carried between producers and the SSE endpoint.

    ``event_id`` is monotonically increasing per channel; it is NOT globally
    unique across channels. Clients must not rely on cross-channel ordering.
    ``data`` is a JSON-serialisable dict whose shape is determined by
    ``event_type``. The EventBus does not validate it.
    """

    channel: str
    event_id: int
    event_type: str
    timestamp: datetime
    data: dict[str, Any]


class EventBus:
    """In-process asyncio pub/sub bus with bounded per-subscriber queues."""

    def __init__(self, queue_size: int = 32) -> None:
        self._queue_size = queue_size
        # channel → list of (subscriber_id, queue)
        self._subscribers: dict[str, list[tuple[str, asyncio.Queue[BusEvent | None]]]] = {}
        self._counters: dict[str, itertools.count[int]] = {}
        self._dropped: dict[str, int] = {}  # subscriber_id → pending drop count

    def publish(self, channel: str, event: BusEvent) -> None:
        """Publish *event* to every subscriber on *channel*.

        Synchronous — never suspends. Uses ``put_nowait`` with drop-oldest
        overflow handling. Safe to call from any async context without
        ``await``.
        """
        for sub_id, q in list(self._subscribers.get(channel, [])):
            if q.full():
                try:
                    q.get_nowait()  # discard oldest
                    self._dropped[sub_id] = self._dropped.get(sub_id, 0) + 1
                    _log.debug(
                        "EventBus drop-oldest on channel=%s subscriber=%s",
                        channel,
                        sub_id,
                    )
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Rare race: queue refilled between get and put.
                self._dropped[sub_id] = self._dropped.get(sub_id, 0) + 1
                _log.warning(
                    "EventBus full-race drop on channel=%s subscriber=%s",
                    channel,
                    sub_id,
                )

    def subscribe(self, channel: str, subscriber_id: str) -> asyncio.Queue[BusEvent | None]:
        """Register *subscriber_id* on *channel*; return its dedicated queue.

        The caller is responsible for calling ``unsubscribe`` in a
        ``finally`` block when the connection closes.
        """
        q: asyncio.Queue[BusEvent | None] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.setdefault(channel, []).append((subscriber_id, q))
        return q

    def unsubscribe(self, channel: str, subscriber_id: str) -> None:
        """Remove *subscriber_id* from *channel*. Idempotent."""
        self._subscribers[channel] = [
            (sid, q) for sid, q in self._subscribers.get(channel, []) if sid != subscriber_id
        ]

    def next_event_id(self, channel: str) -> int:
        """Return the next monotonic event ID for *channel* (1-based)."""
        if channel not in self._counters:
            self._counters[channel] = itertools.count(1)
        return next(self._counters[channel])

    def subscriber_count(self, channel: str) -> int:
        """Count of active subscribers on *channel*."""
        return len(self._subscribers.get(channel, []))

    def total_subscriber_count(self) -> int:
        """Count of active subscribers across all channels."""
        return sum(len(v) for v in self._subscribers.values())

    def get_dropped_count(self, subscriber_id: str) -> int:
        """Consume and return the accumulated drop count for *subscriber_id*.

        Resets the counter to zero on each call. Callers should include the
        returned value in the next SSE frame's ``dropped`` field so clients
        can detect gaps.
        """
        return self._dropped.pop(subscriber_id, 0)
