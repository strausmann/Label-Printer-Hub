# Phase 6b — SSE EventBus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a pure-asyncio in-process EventBus, three producer classes (PrintQueueProducer, StatusProbeProducer, TapeChangeProducer), a `GET /api/events?printer_id=<uuid>` SSE endpoint, three Jinja2 HTML fragment templates, HTMX wiring on the four QR landing pages, Prometheus counters, and a `/healthz` extension — making the Phase 6a QR pages live-updating without polling.

**Architecture:** A singleton `EventBus` on `app.state.event_bus` (instantiated in lifespan) holds per-subscriber `asyncio.Queue` instances with drop-oldest backpressure. Producers hook into `PrintQueue` via an `on_state_change` callback and into the SNMP probe loop via `StatusProbeProducer`. The SSE endpoint subscribes to three channels per printer, renders events as Jinja2 HTML fragments, and streams them as `text/event-stream` for HTMX `sse-swap` injection. All configuration is via Pydantic `Settings` with `PRINTER_HUB_SSE_*` env vars.

**Tech Stack:** FastAPI `StreamingResponse`, asyncio, Pydantic v2 (already in deps), prometheus-client (already in deps), HTMX v2 + SSE extension (self-hosted under `backend/app/static/`).

**Tracking:** Issue #14 (per `Refs #14` in every commit body).

---

## Conventions

- Conventional Commits — scopes from `.commitlintrc.json` enum. Valid scopes for this phase: `api` (routes, SSE endpoint), `queue` (PrintQueue callback hook), `status` (StatusProbeProducer, TapeChangeProducer), `docs` (architecture docs, proxy compat doc), `integration` (integration tests). Use `test` type with `api`/`queue`/`status` scopes for pure-test commits.
- Header max length 120 characters.
- Every commit body ends with `Refs #14`.
- **No** `Co-Authored-By: Claude` anywhere.
- TDD-strict per task: write failing test → run to confirm RED → implement → run to confirm GREEN → commit.
- Coverage floor: ≥ 91% (the Phase 6a floor — do not let it drop).
- `mypy --strict` stays clean throughout.
- `ruff check && ruff format --check` stays clean throughout.
- `alembic check` stays clean (no DB schema changes in Phase 6b).
- Subagents do NOT push. Orchestrator handles push + PR creation.
- Run all commands from `backend/` unless stated otherwise.

---

## File structure (target state after all tasks)

```
backend/
├── app/
│   ├── api/
│   │   └── routes/
│   │       └── events.py                         # NEW — GET /api/events SSE endpoint
│   ├── services/
│   │   ├── event_bus.py                          # NEW — EventBus + BusEvent
│   │   └── producers/
│   │       ├── __init__.py                       # NEW
│   │       ├── print_queue_producer.py           # NEW
│   │       ├── status_probe_producer.py          # NEW
│   │       └── tape_change_producer.py           # NEW
│   ├── templates/
│   │   ├── fragments/
│   │   │   ├── job_state.html                    # NEW
│   │   │   ├── printer_status.html               # NEW
│   │   │   └── tape_status.html                  # NEW
│   │   └── qr/
│   │       ├── loc.html                          # MODIFIED — add SSE block
│   │       ├── asset.html                        # MODIFIED — add SSE block
│   │       ├── spool.html                        # MODIFIED — add SSE block
│   │       └── product.html                      # MODIFIED — add SSE block
│   ├── static/
│   │   ├── htmx.min.js                           # NEW — HTMX v2 self-hosted
│   │   └── sse.js                                # NEW — HTMX SSE extension v2
│   ├── config.py                                 # MODIFIED — 5 new SSE settings
│   └── main.py                                   # MODIFIED — EventBus + producers in lifespan; Healthz field; events router
├── tests/
│   ├── unit/
│   │   ├── services/
│   │   │   ├── test_event_bus.py                 # NEW
│   │   │   ├── test_print_queue_producer.py      # NEW
│   │   │   ├── test_status_probe_producer.py     # NEW
│   │   │   └── test_tape_change_producer.py      # NEW
│   │   └── api/
│   │       └── test_events_route.py              # NEW
│   ├── integration/
│   │   ├── test_phase6b_sse.py                   # NEW — end-to-end SSE delivery
│   │   └── test_sse_flush.py                     # NEW — flush-timing (marked slow)
│   └── api/
│       └── test_openapi_completeness.py          # MODIFIED — bump range 22-30 → 23-31
└── docs/
    └── architecture/
        └── sse.md                                # NEW — proxy compat config
```

---

## Task 0: EventBus core (`event_bus.py` + unit tests)

**Files:**
- Create: `backend/app/services/event_bus.py`
- Create: `backend/tests/unit/services/test_event_bus.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/unit/services/test_event_bus.py
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from app.services.event_bus import BusEvent, EventBus


def _make_event(channel: str = "printer:abc:queue", eid: int = 1) -> BusEvent:
    return BusEvent(
        channel=channel,
        event_id=eid,
        event_type="job.state_changed",
        timestamp=datetime.now(UTC),
        data={"job_id": "x", "from_state": "queued", "to_state": "printing", "queue_depth": 0, "error_code": None},
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
```

- [ ] **Step 2: Run to confirm RED**

```bash
cd backend && python -m pytest tests/unit/services/test_event_bus.py -v 2>&1 | tail -20
```

Expected: `ImportError: cannot import name 'BusEvent' from 'app.services.event_bus'` (module does not exist yet).

- [ ] **Step 3: Implement `event_bus.py`**

```python
# backend/app/services/event_bus.py
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
from dataclasses import dataclass, field
from datetime import UTC, datetime
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

    def subscribe(
        self, channel: str, subscriber_id: str
    ) -> asyncio.Queue[BusEvent | None]:
        """Register *subscriber_id* on *channel*; return its dedicated queue.

        The caller is responsible for calling ``unsubscribe`` in a
        ``finally`` block when the connection closes.
        """
        q: asyncio.Queue[BusEvent | None] = asyncio.Queue(
            maxsize=self._queue_size
        )
        self._subscribers.setdefault(channel, []).append((subscriber_id, q))
        return q

    def unsubscribe(self, channel: str, subscriber_id: str) -> None:
        """Remove *subscriber_id* from *channel*. Idempotent."""
        self._subscribers[channel] = [
            (sid, q)
            for sid, q in self._subscribers.get(channel, [])
            if sid != subscriber_id
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
```

- [ ] **Step 4: Run to confirm GREEN**

```bash
cd backend && python -m pytest tests/unit/services/test_event_bus.py -v 2>&1 | tail -15
```

Expected: all 9 tests PASSED.

- [ ] **Step 5: Lint + type check**

```bash
cd backend && ruff check app/services/event_bus.py tests/unit/services/test_event_bus.py && ruff format --check app/services/event_bus.py tests/unit/services/test_event_bus.py && mypy app/services/event_bus.py
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
cd backend && git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" \
  commit -m "$(cat <<'EOF'
feat(api): EventBus core — BusEvent dataclass, publish/subscribe/unsubscribe, drop-oldest backpressure

Pure-asyncio in-process pub/sub bus. publish() is synchronous (put_nowait)
so producers never block waiting for slow subscribers. Drop-oldest eviction
keeps subscribers seeing current state after a lag. monotonic next_event_id
per channel. 9 unit tests: single/multi subscriber, drop-oldest, channel
isolation, unsubscribe idempotency.

Refs #14
EOF
)"
```

---

## Task 1: Settings + lifespan wiring (EventBus singleton + Settings fields)

**Files:**
- Modify: `backend/app/config.py` — add 5 SSE settings
- Modify: `backend/app/main.py` — mount EventBus in lifespan, extend Healthz model
- Modify: `backend/tests/unit/test_config.py` — assert new fields have correct defaults

- [ ] **Step 1: Write failing test for new settings fields**

Add to `backend/tests/unit/test_config.py` (or create if it doesn't exist at that path — check first with `ls tests/unit/`):

```python
# Append to backend/tests/unit/test_config.py
def test_sse_settings_defaults() -> None:
    """SSE settings must have documented defaults when env vars are absent."""
    s = Settings(_env_file=None)
    assert s.sse_queue_size == 32
    assert s.sse_idle_timeout_s == 300.0
    assert s.sse_max_subscribers == 100
    assert s.sse_heartbeat_s == 30.0
    assert s.sse_probe_interval_s == 30.0
```

- [ ] **Step 2: Run to confirm RED**

```bash
cd backend && python -m pytest tests/unit/test_config.py::test_sse_settings_defaults -v
```

Expected: `AttributeError: 'Settings' object has no attribute 'sse_queue_size'`.

- [ ] **Step 3: Add SSE fields to `config.py`**

Add the following block inside the `Settings` class body, after the existing `log_level` field:

```python
    # SSE EventBus — configurable resource limits
    sse_queue_size: int = 32
    """Per-subscriber asyncio.Queue depth. Drop-oldest when full."""

    sse_idle_timeout_s: float = 300.0
    """Seconds of inactivity before the server closes an SSE connection."""

    sse_max_subscribers: int = 100
    """Max concurrent SSE subscribers per printer. Returns 429 when exceeded."""

    sse_heartbeat_s: float = 30.0
    """Interval between SSE keepalive comment frames when no events flow."""

    sse_probe_interval_s: float = 30.0
    """SNMP probe interval for StatusProbeProducer (seconds)."""
```

- [ ] **Step 4: Extend `Healthz` model in `main.py`**

Find the `Healthz` class in `backend/app/main.py` and add the `sse_active_subscribers` field:

```python
class Healthz(BaseModel):
    """Response body of /healthz."""

    model_config = ConfigDict(frozen=True)

    status: str
    version: str
    revision: str
    build_date: str
    repository: str
    sse_active_subscribers: int = 0
    """Current live SSE subscriber count. Zero when no clients are connected
    or when the EventBus has not been initialised (pre-lifespan)."""
```

- [ ] **Step 5: Wire EventBus into lifespan in `main.py`**

At the top of `main.py`, add the import alongside other service imports:

```python
from app.services.event_bus import EventBus
```

Inside `lifespan`, after `await queue.start()` and before `app.state.print_queue = queue`, add:

```python
    # --- SSE EventBus ---
    settings_sse = get_settings()
    event_bus = EventBus(queue_size=settings_sse.sse_queue_size)
    app.state.event_bus = event_bus
    # ----- end SSE ------
```

Update the `healthz` handler to read `event_bus` from `app.state` (with a safe fallback for calls before lifespan):

```python
    @app.get(
        "/healthz",
        response_model=Healthz,
        tags=["meta"],
        summary="Liveness probe",
        description=(
            "Returns 200 OK with a fixed shape. No authentication required. "
            "Used by Docker, Kubernetes, and reverse proxies to decide whether "
            "the backend is up. Has zero dependencies — does not touch the "
            "database, the printer queue, SNMP, or any integration. "
            "``sse_active_subscribers`` reflects the current EventBus subscriber "
            "count; zero means no live SSE clients or the bus is uninitialised."
        ),
    )
    async def healthz(request: Request) -> Healthz:
        bus: EventBus | None = getattr(request.app.state, "event_bus", None)
        return Healthz(
            status="ok",
            version=HUB_VERSION,
            revision=HUB_REVISION,
            build_date=HUB_BUILD_DATE,
            repository=HUB_REPO_URL,
            sse_active_subscribers=bus.total_subscriber_count() if bus else 0,
        )
```

Note: `healthz` must now accept `request: Request` — add `from fastapi import FastAPI, Request` to existing imports (Request may already be imported; confirm before adding).

- [ ] **Step 6: Run to confirm GREEN**

```bash
cd backend && python -m pytest tests/unit/test_config.py::test_sse_settings_defaults tests/unit/test_lifespan.py -v 2>&1 | tail -20
```

Expected: all pass. If `test_lifespan.py` tests the `healthz` endpoint signature, fix any assertion that expected the old field count — `Healthz` now has 6 fields.

- [ ] **Step 7: Lint + type check**

```bash
cd backend && ruff check app/config.py app/main.py && ruff format --check app/config.py app/main.py && mypy app/config.py app/main.py
```

Expected: no errors.

- [ ] **Step 8: Commit**

```bash
cd backend && git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" \
  commit -m "$(cat <<'EOF'
feat(api): SSE settings fields + EventBus singleton in lifespan + healthz sse_active_subscribers

Five new PRINTER_HUB_SSE_* settings with documented defaults. EventBus
instantiated in lifespan and stored on app.state.event_bus. Healthz model
gains sse_active_subscribers (default 0) so ops tools can detect zombie
subscribers or a silently crashed bus.

Refs #14
EOF
)"
```

---

## Task 2: PrintQueueProducer + on_state_change callback in PrintQueue

**Files:**
- Create: `backend/app/services/producers/__init__.py`
- Create: `backend/app/services/producers/print_queue_producer.py`
- Modify: `backend/app/services/print_queue.py` — add `on_state_change` callback parameter
- Create: `backend/tests/unit/services/test_print_queue_producer.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/unit/services/test_print_queue_producer.py
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, call, patch

import pytest

from app.services.event_bus import BusEvent, EventBus
from app.services.job_lifecycle import Job, JobState
from app.services.producers.print_queue_producer import PrintQueueProducer


def _make_job(printer_id: str = "printer-uuid-1") -> Job:
    return Job(
        id="job-uuid-1",
        printer_id=printer_id,
        tape_mm=12,
    )


def test_handle_transition_publishes_to_correct_channel() -> None:
    bus = MagicMock(spec=EventBus)
    bus.next_event_id.return_value = 1
    producer = PrintQueueProducer(bus=bus)
    job = _make_job()

    producer.handle_transition(job, JobState.QUEUED, JobState.PRINTING)

    bus.publish.assert_called_once()
    call_args = bus.publish.call_args
    channel = call_args[0][0]
    event: BusEvent = call_args[0][1]
    assert channel == f"printer:{job.printer_id}:queue"
    assert event.channel == channel
    assert event.event_type == "job.state_changed"


def test_handle_transition_data_has_from_and_to_state() -> None:
    bus = MagicMock(spec=EventBus)
    bus.next_event_id.return_value = 5
    producer = PrintQueueProducer(bus=bus)
    job = _make_job()

    producer.handle_transition(job, JobState.QUEUED, JobState.PRINTING)

    event: BusEvent = bus.publish.call_args[0][1]
    assert event.data["from_state"] == "queued"
    assert event.data["to_state"] == "printing"
    assert event.data["job_id"] == "job-uuid-1"
    assert event.data["queue_depth"] == 0
    assert event.data["error_code"] is None


def test_handle_transition_failed_state_includes_error_code() -> None:
    bus = MagicMock(spec=EventBus)
    bus.next_event_id.return_value = 2
    producer = PrintQueueProducer(bus=bus)
    job = _make_job()
    job.error_code = "tape_mismatch"

    producer.handle_transition(job, JobState.PRINTING, JobState.FAILED)

    event: BusEvent = bus.publish.call_args[0][1]
    assert event.data["error_code"] == "tape_mismatch"


def test_handle_transition_uses_next_event_id() -> None:
    bus = MagicMock(spec=EventBus)
    bus.next_event_id.return_value = 42
    producer = PrintQueueProducer(bus=bus)
    job = _make_job()

    producer.handle_transition(job, JobState.QUEUED, JobState.PRINTING)

    channel = f"printer:{job.printer_id}:queue"
    bus.next_event_id.assert_called_once_with(channel)
    event: BusEvent = bus.publish.call_args[0][1]
    assert event.event_id == 42
```

- [ ] **Step 2: Run to confirm RED**

```bash
cd backend && python -m pytest tests/unit/services/test_print_queue_producer.py -v 2>&1 | tail -10
```

Expected: `ModuleNotFoundError: No module named 'app.services.producers'`.

- [ ] **Step 3: Create `producers/__init__.py` and `print_queue_producer.py`**

```python
# backend/app/services/producers/__init__.py
"""Event producers that publish to the EventBus."""
```

```python
# backend/app/services/producers/print_queue_producer.py
"""Publishes job.state_changed events to the EventBus on job state transitions.

The PrintQueue accepts an ``on_state_change`` callback in its constructor.
This producer's ``handle_transition`` method is passed as that callback so it
runs inside the worker loop without any async overhead — ``EventBus.publish``
is synchronous.
"""
from __future__ import annotations

from datetime import UTC, datetime

from app.services.event_bus import BusEvent, EventBus
from app.services.job_lifecycle import Job, JobState


class PrintQueueProducer:
    """Converts job state transitions into EventBus events."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    def handle_transition(
        self,
        job: Job,
        from_state: JobState,
        to_state: JobState,
    ) -> None:
        """Publish a ``job.state_changed`` event.

        Called synchronously from the PrintQueue worker after each
        ``JobStateMachine.transition`` call. Must not raise — any exception
        would propagate into the worker and risk marking the job FAILED
        incorrectly. Errors are logged and swallowed.
        """
        channel = f"printer:{job.printer_id}:queue"
        try:
            event = BusEvent(
                channel=channel,
                event_id=self._bus.next_event_id(channel),
                event_type="job.state_changed",
                timestamp=datetime.now(UTC),
                data={
                    "job_id": str(job.id),
                    "from_state": from_state.value,
                    "to_state": to_state.value,
                    "queue_depth": 0,  # enriched by SSE endpoint before emit
                    "error_code": getattr(job, "error_code", None),
                },
            )
            self._bus.publish(channel, event)
        except Exception:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).exception(
                "PrintQueueProducer.handle_transition failed for job=%s", job.id
            )
```

- [ ] **Step 4: Add `on_state_change` callback to `PrintQueue.__init__` and `_worker`**

In `backend/app/services/print_queue.py`, update `PrintQueue.__init__`:

```python
from collections.abc import Callable

class PrintQueue:
    """Per-printer async work queue with submit/pause/resume/cancel/retry."""

    def __init__(
        self,
        printers: list[_PrinterLike],
        on_state_change: Callable[[Job, JobState, JobState], None] | None = None,
    ) -> None:
        self._on_state_change = on_state_change
        # ... rest of existing __init__ body unchanged ...
```

Add `from collections.abc import Callable` to the top-level imports of `print_queue.py` if not already present.

Then add a helper method to `PrintQueue` (before `_worker`):

```python
    def _notify_state_change(
        self, job: Job, from_state: JobState, to_state: JobState
    ) -> None:
        """Call the on_state_change callback if one is registered.

        Guarded with try/except so a bug in the callback never crashes the
        worker. The callback is expected to be PrintQueueProducer.handle_transition
        which already has its own internal guard, but defence in depth applies.
        """
        if self._on_state_change is not None:
            try:
                self._on_state_change(job, from_state, to_state)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "on_state_change callback raised for job=%s %s->%s",
                    job.id,
                    from_state.value,
                    to_state.value,
                )
```

In `_worker`, wrap every `JobStateMachine.transition(job, new_state)` call to capture old state and fire the callback. There are four transition call sites in `_worker`:

1. `JobStateMachine.transition(job, JobState.PRINTING)` — replace with:
```python
                _from = job.state
                JobStateMachine.transition(job, JobState.PRINTING)
                self._notify_state_change(job, _from, JobState.PRINTING)
```

2. `JobStateMachine.transition(job, JobState.COMPLETED)` — replace with:
```python
                _from = job.state
                JobStateMachine.transition(job, JobState.COMPLETED)
                self._notify_state_change(job, _from, JobState.COMPLETED)
```

3. `JobStateMachine.transition(job, JobState.FAILED)` (inside `except PrinterError`) — replace with:
```python
                    _from = job.state
                    try:
                        JobStateMachine.transition(job, JobState.FAILED)
                        self._notify_state_change(job, _from, JobState.FAILED)
                    except InvalidStateTransitionError:
```

4. `JobStateMachine.transition(job, JobState.FAILED)` (inside `except Exception`) — replace with:
```python
                _from = job.state
                try:
                    JobStateMachine.transition(job, JobState.FAILED)
                    self._notify_state_change(job, _from, JobState.FAILED)
                except InvalidStateTransitionError:
```

- [ ] **Step 5: Run to confirm GREEN**

```bash
cd backend && python -m pytest tests/unit/services/test_print_queue_producer.py tests/unit/services/test_print_queue.py -v 2>&1 | tail -20
```

Expected: all pass (producer tests + existing queue tests unbroken).

- [ ] **Step 6: Lint + type check**

```bash
cd backend && ruff check app/services/producers/ app/services/print_queue.py && ruff format --check app/services/producers/ app/services/print_queue.py && mypy app/services/producers/print_queue_producer.py app/services/print_queue.py
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
cd backend && git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" \
  commit -m "$(cat <<'EOF'
feat(queue): PrintQueueProducer + on_state_change callback in PrintQueue._worker

PrintQueue.__init__ accepts optional on_state_change(job, from_state, to_state)
callback. _notify_state_change guards the call with try/except so a producer
bug can never fail the job. PrintQueueProducer.handle_transition publishes
job.state_changed BusEvents. Callback is invoked at all four transition
call-sites in _worker (PRINTING, COMPLETED, FAILED×2).

Refs #14
EOF
)"
```

---

## Task 3: StatusProbeProducer + TapeChangeProducer

**Files:**
- Create: `backend/app/services/producers/status_probe_producer.py`
- Create: `backend/app/services/producers/tape_change_producer.py`
- Create: `backend/tests/unit/services/test_status_probe_producer.py`
- Create: `backend/tests/unit/services/test_tape_change_producer.py`

- [ ] **Step 1: Write failing tests for TapeChangeProducer**

```python
# backend/tests/unit/services/test_tape_change_producer.py
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.printer_backends.snmp_helper import PreflightStatus
from app.services.event_bus import BusEvent, EventBus
from app.services.producers.tape_change_producer import TapeChangeProducer


def _status(tape_mm: int | None = 12) -> PreflightStatus:
    return PreflightStatus(
        hr_printer_status="idle",
        loaded_tape_mm=tape_mm,
        error_flags=[],
    )


def test_no_publish_when_tape_unchanged() -> None:
    bus = MagicMock(spec=EventBus)
    bus.next_event_id.return_value = 1
    registry = MagicMock()
    producer = TapeChangeProducer(bus=bus, tape_registry=registry)
    producer.on_probe_result("printer-uuid", _status(12), _status(12))
    bus.publish.assert_not_called()


def test_publishes_on_tape_change() -> None:
    bus = MagicMock(spec=EventBus)
    bus.next_event_id.return_value = 1
    registry = MagicMock()
    registry.lookup_pt.side_effect = Exception("not found")
    producer = TapeChangeProducer(bus=bus, tape_registry=registry)
    producer.on_probe_result("printer-uuid", _status(12), _status(24))
    bus.publish.assert_called_once()
    event: BusEvent = bus.publish.call_args[0][1]
    assert event.event_type == "printer.tape_changed"
    assert event.data["from_mm"] == 12
    assert event.data["to_mm"] == 24


def test_from_mm_is_none_when_old_is_none() -> None:
    bus = MagicMock(spec=EventBus)
    bus.next_event_id.return_value = 1
    registry = MagicMock()
    registry.lookup_pt.side_effect = Exception("not found")
    producer = TapeChangeProducer(bus=bus, tape_registry=registry)
    producer.on_probe_result("printer-uuid", None, _status(24))
    event: BusEvent = bus.publish.call_args[0][1]
    assert event.data["from_mm"] is None
    assert event.data["to_mm"] == 24


def test_tape_removed_publishes_to_mm_none() -> None:
    bus = MagicMock(spec=EventBus)
    bus.next_event_id.return_value = 1
    registry = MagicMock()
    producer = TapeChangeProducer(bus=bus, tape_registry=registry)
    producer.on_probe_result("printer-uuid", _status(12), _status(None))
    event: BusEvent = bus.publish.call_args[0][1]
    assert event.data["to_mm"] is None


def test_channel_is_tape_channel() -> None:
    bus = MagicMock(spec=EventBus)
    bus.next_event_id.return_value = 1
    registry = MagicMock()
    registry.lookup_pt.side_effect = Exception("not found")
    producer = TapeChangeProducer(bus=bus, tape_registry=registry)
    producer.on_probe_result("my-printer", _status(12), _status(24))
    channel = bus.publish.call_args[0][0]
    assert channel == "printer:my-printer:tape"
```

- [ ] **Step 2: Write failing tests for StatusProbeProducer**

```python
# backend/tests/unit/services/test_status_probe_producer.py
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.printer_backends.snmp_helper import PreflightStatus
from app.services.event_bus import BusEvent, EventBus
from app.services.producers.status_probe_producer import StatusProbeProducer


def _make_bus() -> MagicMock:
    bus = MagicMock(spec=EventBus)
    bus.next_event_id.return_value = 1
    return bus


def _status(hr: str = "idle", tape: int | None = 12) -> PreflightStatus:
    return PreflightStatus(hr_printer_status=hr, loaded_tape_mm=tape, error_flags=[])


@pytest.mark.asyncio
async def test_first_probe_always_publishes() -> None:
    bus = _make_bus()
    tape_producer = MagicMock()
    with patch(
        "app.services.producers.status_probe_producer.query_preflight",
        new_callable=AsyncMock,
        return_value=_status("idle"),
    ):
        producer = StatusProbeProducer(
            bus=bus,
            printer_id="p1",
            host="198.51.100.1",
            interval_s=0.001,
            tape_change_producer=tape_producer,
        )
        await producer.start()
        await asyncio.sleep(0.05)
        await producer.stop()

    assert bus.publish.call_count >= 1
    event: BusEvent = bus.publish.call_args_list[0][0][1]
    assert event.event_type == "printer.status"
    assert event.data["online"] is True


@pytest.mark.asyncio
async def test_no_publish_when_status_unchanged() -> None:
    bus = _make_bus()
    tape_producer = MagicMock()
    call_count = 0

    async def _same_status(*args: object, **kwargs: object) -> PreflightStatus:
        nonlocal call_count
        call_count += 1
        return _status("idle")

    with patch(
        "app.services.producers.status_probe_producer.query_preflight",
        side_effect=_same_status,
    ):
        producer = StatusProbeProducer(
            bus=bus,
            printer_id="p1",
            host="198.51.100.1",
            interval_s=0.01,
            tape_change_producer=tape_producer,
        )
        await producer.start()
        # Wait for at least 2 probe cycles
        while call_count < 2:
            await asyncio.sleep(0.01)
        await producer.stop()

    # First publish on first probe; no more after that (status unchanged)
    assert bus.publish.call_count == 1


@pytest.mark.asyncio
async def test_publishes_on_status_change() -> None:
    bus = _make_bus()
    tape_producer = MagicMock()
    statuses = [_status("idle"), _status("printing")]
    idx = 0

    async def _cycle(*args: object, **kwargs: object) -> PreflightStatus:
        nonlocal idx
        s = statuses[min(idx, len(statuses) - 1)]
        idx += 1
        return s

    with patch(
        "app.services.producers.status_probe_producer.query_preflight",
        side_effect=_cycle,
    ):
        producer = StatusProbeProducer(
            bus=bus,
            printer_id="p1",
            host="198.51.100.1",
            interval_s=0.01,
            tape_change_producer=tape_producer,
        )
        await producer.start()
        while idx < 2:
            await asyncio.sleep(0.01)
        await producer.stop()

    assert bus.publish.call_count == 2


@pytest.mark.asyncio
async def test_snmp_exception_publishes_offline_event() -> None:
    bus = _make_bus()
    tape_producer = MagicMock()
    with patch(
        "app.services.producers.status_probe_producer.query_preflight",
        new_callable=AsyncMock,
        side_effect=Exception("timeout"),
    ):
        producer = StatusProbeProducer(
            bus=bus,
            printer_id="p1",
            host="198.51.100.1",
            interval_s=0.001,
            tape_change_producer=tape_producer,
        )
        await producer.start()
        await asyncio.sleep(0.05)
        await producer.stop()

    assert bus.publish.call_count >= 1
    event: BusEvent = bus.publish.call_args_list[0][0][1]
    assert event.data["online"] is False
```

- [ ] **Step 3: Run to confirm RED**

```bash
cd backend && python -m pytest tests/unit/services/test_tape_change_producer.py tests/unit/services/test_status_probe_producer.py -v 2>&1 | tail -15
```

Expected: `ModuleNotFoundError` for both producer modules.

- [ ] **Step 4: Implement `tape_change_producer.py`**

```python
# backend/app/services/producers/tape_change_producer.py
"""Detects tape swaps between consecutive SNMP probe results.

Not a separate loop — called by StatusProbeProducer after each successful
probe so tape-change events are zero-latency relative to the probe that
produced them.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.printer_backends.snmp_helper import PreflightStatus
from app.services.event_bus import BusEvent, EventBus

_log = logging.getLogger(__name__)


class TapeChangeProducer:
    """Publish ``printer.tape_changed`` when loaded_tape_mm changes."""

    def __init__(self, bus: EventBus, tape_registry: object) -> None:
        self._bus = bus
        self._tape_registry = tape_registry

    def on_probe_result(
        self,
        printer_id: str,
        old: PreflightStatus | None,
        new: PreflightStatus,
    ) -> None:
        """Compare old and new tape widths; publish if they differ."""
        old_mm = old.loaded_tape_mm if old is not None else None
        new_mm = new.loaded_tape_mm
        if old_mm == new_mm:
            return

        channel = f"printer:{printer_id}:tape"
        tape_label: str | None = None
        if new_mm is not None:
            try:
                from app.services.status_block import MediaType  # noqa: PLC0415

                spec = self._tape_registry.lookup_pt(new_mm, MediaType.LAMINATED)
                tape_label = f"{spec.width_mm}mm"
            except Exception:  # noqa: BLE001
                tape_label = f"{new_mm}mm"

        self._bus.publish(
            channel,
            BusEvent(
                channel=channel,
                event_id=self._bus.next_event_id(channel),
                event_type="printer.tape_changed",
                timestamp=datetime.now(UTC),
                data={"from_mm": old_mm, "to_mm": new_mm, "tape_label": tape_label},
            ),
        )
```

- [ ] **Step 5: Implement `status_probe_producer.py`**

```python
# backend/app/services/producers/status_probe_producer.py
"""Polls SNMP every N seconds; publishes printer.status on state change.

Debounce (change-only publish): the producer stores the last published
PreflightStatus. If the new status is identical (same hr_printer_status and
same error_flags set), no event is published. On the first probe, always
publish (initialises the client view).

The TapeChangeProducer is a collaborator: after each successful probe,
``tape_change_producer.on_probe_result`` is called with the old and new
PreflightStatus so tape-change events are derived from the same probe data
without a second polling loop.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from app.printer_backends.snmp_helper import PreflightStatus, query_preflight
from app.services.event_bus import BusEvent, EventBus
from app.services.producers.tape_change_producer import TapeChangeProducer

_log = logging.getLogger(__name__)


class StatusProbeProducer:
    """Background SNMP probe loop; publishes printer.status on change."""

    def __init__(
        self,
        bus: EventBus,
        printer_id: str,
        host: str,
        *,
        interval_s: float = 30.0,
        community: str = "public",
        tape_change_producer: TapeChangeProducer | None = None,
    ) -> None:
        self._bus = bus
        self._printer_id = printer_id
        self._host = host
        self._interval_s = interval_s
        self._community = community
        self._tape_producer = tape_change_producer
        self._last: PreflightStatus | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the background probe task."""
        self._task = asyncio.create_task(
            self._loop(), name=f"status-probe-{self._printer_id}"
        )

    async def stop(self) -> None:
        """Cancel the background probe task and await its exit."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def _has_changed(self, new: PreflightStatus) -> bool:
        if self._last is None:
            return True
        return (
            new.hr_printer_status != self._last.hr_printer_status
            or set(new.error_flags) != set(self._last.error_flags)
        )

    async def _loop(self) -> None:
        while True:
            try:
                status = await query_preflight(
                    self._host,
                    community=self._community,
                    timeout_s=5.0,
                )
                # Tape-change detection runs before the status change check so
                # tape events are always emitted even if status is unchanged.
                if self._tape_producer is not None:
                    self._tape_producer.on_probe_result(
                        self._printer_id, self._last, status
                    )
                if self._has_changed(status):
                    self._last = status
                    channel = f"printer:{self._printer_id}:state"
                    self._bus.publish(
                        channel,
                        BusEvent(
                            channel=channel,
                            event_id=self._bus.next_event_id(channel),
                            event_type="printer.status",
                            timestamp=datetime.now(UTC),
                            data={
                                "hr_printer_status": status.hr_printer_status,
                                "error_flags": list(status.error_flags),
                                "online": True,
                            },
                        ),
                    )
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                _log.exception(
                    "StatusProbeProducer: SNMP probe failed for printer=%s",
                    self._printer_id,
                )
                offline = PreflightStatus(
                    hr_printer_status="other",
                    loaded_tape_mm=None,
                    error_flags=[],
                )
                if self._has_changed(offline):
                    self._last = offline
                    channel = f"printer:{self._printer_id}:state"
                    self._bus.publish(
                        channel,
                        BusEvent(
                            channel=channel,
                            event_id=self._bus.next_event_id(channel),
                            event_type="printer.status",
                            timestamp=datetime.now(UTC),
                            data={
                                "hr_printer_status": "other",
                                "error_flags": [],
                                "online": False,
                            },
                        ),
                    )
            await asyncio.sleep(self._interval_s)
```

- [ ] **Step 6: Run to confirm GREEN**

```bash
cd backend && python -m pytest tests/unit/services/test_tape_change_producer.py tests/unit/services/test_status_probe_producer.py -v 2>&1 | tail -20
```

Expected: all tests PASSED.

- [ ] **Step 7: Lint + type check**

```bash
cd backend && ruff check app/services/producers/ && ruff format --check app/services/producers/ && mypy app/services/producers/
```

Expected: no errors.

- [ ] **Step 8: Commit**

```bash
cd backend && git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" \
  commit -m "$(cat <<'EOF'
feat(status): StatusProbeProducer + TapeChangeProducer — SNMP probe loop with change-only publish

StatusProbeProducer polls SNMP every N seconds (default 30). Debounces:
only publishes printer.status when hr_printer_status or error_flags changes.
SNMP exceptions publish online=False event. TapeChangeProducer is a
collaborator: called after each probe to detect loaded_tape_mm transitions
without a second loop. 9 unit tests covering all state-change branches.

Refs #14
EOF
)"
```

---

## Task 4: SSE route skeleton (404 + subscriber-cap + stream stub)

**Files:**
- Create: `backend/app/api/routes/events.py`
- Modify: `backend/app/main.py` — mount events router
- Create: `backend/tests/unit/api/test_events_route.py`

- [ ] **Step 1: Write failing tests (404 and 429 only — streaming tested in Task 5)**

```python
# backend/tests/unit/api/test_events_route.py
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app as _app_wrapper
from app.services.event_bus import BusEvent, EventBus

_inner = _app_wrapper._app  # type: ignore[attr-defined]


@pytest.fixture()
def client_with_bus(tmp_path: object) -> TestClient:
    """TestClient with a real EventBus wired to app.state."""
    bus = EventBus(queue_size=8)
    _inner.state.event_bus = bus
    return TestClient(_inner, raise_server_exceptions=True)


def _mock_printer_get(return_value: object):  # type: ignore[no-untyped-def]
    return patch(
        "app.api.routes.events.printers_repo.get",
        new_callable=AsyncMock,
        return_value=return_value,
    )


def test_404_when_printer_not_found(client_with_bus: TestClient) -> None:
    with _mock_printer_get(None):
        resp = client_with_bus.get(f"/api/events?printer_id={uuid.uuid4()}")
    assert resp.status_code == 404


def test_429_when_subscriber_limit_exceeded(client_with_bus: TestClient) -> None:
    printer_id = uuid.uuid4()
    fake_printer = MagicMock()
    fake_printer.id = str(printer_id)

    bus: EventBus = _inner.state.event_bus
    # Saturate all three channels to exceed the per-printer cap
    from app.api.routes.events import _MAX_SUBSCRIBERS_PER_PRINTER
    for ch in (
        f"printer:{printer_id}:queue",
        f"printer:{printer_id}:state",
        f"printer:{printer_id}:tape",
    ):
        for i in range(_MAX_SUBSCRIBERS_PER_PRINTER):
            bus.subscribe(ch, f"fake-sub-{ch}-{i}")

    with _mock_printer_get(fake_printer):
        resp = client_with_bus.get(f"/api/events?printer_id={printer_id}")

    assert resp.status_code == 429
    body = resp.json()
    assert body["type"] == "sse-subscriber-limit"
```

- [ ] **Step 2: Run to confirm RED**

```bash
cd backend && python -m pytest tests/unit/api/test_events_route.py::test_404_when_printer_not_found tests/unit/api/test_events_route.py::test_429_when_subscriber_limit_exceeded -v 2>&1 | tail -15
```

Expected: `ImportError` or 404 route not found.

- [ ] **Step 3: Implement `events.py`**

```python
# backend/app/api/routes/events.py
"""SSE endpoint: GET /api/events?printer_id=<uuid>

Subscribes to three EventBus channels for the requested printer and streams
events as ``text/event-stream``. Each event is rendered as an HTML fragment
by ``_render_fragment`` so HTMX ``sse-swap`` can inject it directly.

Resource limits (all configurable via PRINTER_HUB_SSE_* env vars):
- Max subscribers per printer: 100 (429 when exceeded)
- Idle timeout: 300 s (server closes; browser reconnects)
- Heartbeat interval: 30 s (SSE comment frames)

Auth: none beyond the Pangolin proxy SSO at the network layer.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.repositories import printers as printers_repo
from app.services.event_bus import BusEvent, EventBus

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["events"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# Module-level constants — overridden by Settings in lifespan (Tasks 1/6)
_MAX_SUBSCRIBERS_PER_PRINTER: int = 100
_HEARTBEAT_INTERVAL_S: float = 30.0
_IDLE_TIMEOUT_S: float = 300.0

# Shared Jinja2Templates instance — same root as qr.py
_templates_dir = Path(__file__).parent.parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_templates_dir))

# event_type → fragment template path
_FRAGMENT_MAP: dict[str, str] = {
    "job.state_changed": "fragments/job_state.html",
    "printer.status": "fragments/printer_status.html",
    "printer.tape_changed": "fragments/tape_status.html",
}


async def _render_fragment(event: BusEvent) -> str:
    """Render a Jinja2 HTML fragment for the event.

    Returns an HTML string for HTMX sse-swap injection, or an empty string
    if no template is registered for the event type (safe fallback — client
    retains its existing DOM).
    """
    tmpl_name = _FRAGMENT_MAP.get(event.event_type)
    if not tmpl_name:
        return ""
    try:
        response = _templates.TemplateResponse(
            name=tmpl_name,
            context={**event.data, "timestamp": event.timestamp.isoformat()},
        )
        return response.body.decode()
    except Exception:  # noqa: BLE001
        _log.exception(
            "_render_fragment: failed for event_type=%s", event.event_type
        )
        return ""


async def _sse_stream(
    printer_id: uuid.UUID,
    bus: EventBus,
    request: Request,
) -> AsyncIterator[str]:
    """Core SSE generator. Yields SSE-formatted strings."""
    subscriber_id = str(uuid.uuid4())
    channels = [
        f"printer:{printer_id}:queue",
        f"printer:{printer_id}:state",
        f"printer:{printer_id}:tape",
    ]

    # Subscriber-cap check (pre-subscribe, so the cap is not off-by-one)
    total = sum(bus.subscriber_count(c) for c in channels)
    if total >= _MAX_SUBSCRIBERS_PER_PRINTER:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "type": "sse-subscriber-limit",
                "title": "Too many SSE subscribers for this printer",
                "limit": _MAX_SUBSCRIBERS_PER_PRINTER,
            },
        )

    # Log Last-Event-ID for observability (replay deferred to Phase 7)
    last_event_id = request.headers.get("last-event-id")
    if last_event_id:
        _log.debug(
            "SSE reconnect: subscriber=%s last_event_id=%s (replay not implemented)",
            subscriber_id,
            last_event_id,
        )

    queues = [bus.subscribe(ch, subscriber_id) for ch in channels]
    _log.info(
        "SSE connect: printer=%s subscriber=%s remote=%s",
        printer_id,
        subscriber_id,
        request.client,
    )

    try:
        last_activity = asyncio.get_event_loop().time()
        while True:
            if await request.is_disconnected():
                _log.info(
                    "SSE disconnect: printer=%s subscriber=%s reason=client_close",
                    printer_id,
                    subscriber_id,
                )
                break

            get_tasks = [asyncio.create_task(q.get()) for q in queues]
            done: set[asyncio.Task[BusEvent | None]] = set()
            pending: set[asyncio.Task[BusEvent | None]] = set()
            try:
                done, pending = await asyncio.wait(
                    get_tasks,
                    timeout=_HEARTBEAT_INTERVAL_S,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            finally:
                for t in pending:
                    t.cancel()
                    try:
                        await t
                    except (asyncio.CancelledError, Exception):
                        pass

            now = asyncio.get_event_loop().time()

            if not done:
                # Heartbeat — no events during the timeout window
                if now - last_activity > _IDLE_TIMEOUT_S:
                    _log.info(
                        "SSE disconnect: printer=%s subscriber=%s reason=idle_timeout",
                        printer_id,
                        subscriber_id,
                    )
                    break
                yield ": keepalive\n\n"
                continue

            last_activity = now
            for task in done:
                try:
                    event = task.result()
                except Exception:
                    continue
                if event is None:
                    continue
                html_fragment = await _render_fragment(event)
                dropped = bus.get_dropped_count(subscriber_id)
                data_payload = {
                    "html": html_fragment,
                    "event_type": event.event_type,
                    "timestamp": event.timestamp.isoformat(),
                    "dropped": dropped,
                    **event.data,
                }
                yield (
                    f"id: {event.event_id}\n"
                    f"event: {event.event_type}\n"
                    f"data: {json.dumps(data_payload)}\n\n"
                )
    finally:
        for ch in channels:
            bus.unsubscribe(ch, subscriber_id)
        _log.info(
            "SSE cleanup: printer=%s subscriber=%s", printer_id, subscriber_id
        )


@router.get(
    "/events",
    summary="Server-Sent Events stream for a printer",
    description=(
        "Returns a ``text/event-stream`` response. "
        "Publishes ``job.state_changed``, ``printer.status``, and "
        "``printer.tape_changed`` events as they occur. "
        "A keepalive comment is sent every 30 s when no events flow. "
        "Closes automatically after 5 minutes of inactivity. "
        "On reconnect the stream starts fresh — ``Last-Event-ID`` is "
        "observed but replay is deferred to Phase 7. "
        "Returns 404 if ``printer_id`` does not exist in the database. "
        "Returns 429 if the per-printer subscriber limit is reached."
    ),
    response_class=StreamingResponse,
    tags=["events"],
)
async def sse_events(
    printer_id: uuid.UUID,
    request: Request,
    session: SessionDep,
) -> StreamingResponse:
    """SSE endpoint for a printer's live event stream."""
    bus: EventBus = request.app.state.event_bus

    printer = await printers_repo.get(session, printer_id)
    if printer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"printer {printer_id} not found",
        )

    return StreamingResponse(
        _sse_stream(printer_id, bus, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

- [ ] **Step 4: Mount the events router in `main.py`**

Add to the imports at the top of `backend/app/main.py`:

```python
from app.api.routes import events as events_routes
```

Add to `create_app()` alongside the other `app.include_router` calls:

```python
    app.include_router(events_routes.router)
```

- [ ] **Step 5: Run to confirm GREEN**

```bash
cd backend && python -m pytest tests/unit/api/test_events_route.py::test_404_when_printer_not_found tests/unit/api/test_events_route.py::test_429_when_subscriber_limit_exceeded -v 2>&1 | tail -15
```

Expected: both PASSED.

- [ ] **Step 6: Lint + type check**

```bash
cd backend && ruff check app/api/routes/events.py && ruff format --check app/api/routes/events.py && mypy app/api/routes/events.py
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
cd backend && git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" \
  commit -m "$(cat <<'EOF'
feat(api): SSE route skeleton — GET /api/events with 404/429 guards + full stream generator

events.py router with _sse_stream generator: per-subscriber asyncio.Queue
multiplex over three channels, drop-oldest backpressure, heartbeat comment
frames, idle-timeout server-close, Last-Event-ID logging (replay deferred).
X-Accel-Buffering: no for reverse-proxy flush. Subscriber-cap check returns
429 ProblemDetail before subscribing. Mounted in create_app().

Refs #14
EOF
)"
```

---

## Task 5: SSE stream delivery test (event arrives in < 200 ms)

**Files:**
- Modify: `backend/tests/unit/api/test_events_route.py` — add streaming delivery test

- [ ] **Step 1: Write the streaming delivery test**

Append to `backend/tests/unit/api/test_events_route.py`:

```python
# Append to existing test_events_route.py

import httpx
from httpx import ASGITransport


@pytest.mark.asyncio
async def test_event_delivered_to_sse_stream() -> None:
    """Publish an event; assert it arrives in the SSE stream within 200 ms."""
    from app.services.event_bus import BusEvent, EventBus

    printer_id = uuid.uuid4()
    fake_printer = MagicMock()
    fake_printer.id = str(printer_id)

    bus = EventBus(queue_size=8)
    _inner.state.event_bus = bus

    channel = f"printer:{printer_id}:queue"
    test_event = BusEvent(
        channel=channel,
        event_id=1,
        event_type="job.state_changed",
        timestamp=datetime.now(UTC),
        data={
            "job_id": "job-1",
            "from_state": "queued",
            "to_state": "printing",
            "queue_depth": 0,
            "error_code": None,
        },
    )

    received: list[dict] = []

    async def consume() -> None:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=_inner), base_url="http://test"
        ) as client:
            async with client.stream(
                "GET", f"/api/events?printer_id={printer_id}"
            ) as response:
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        received.append(json.loads(line[5:].strip()))
                        break

    with _mock_printer_get(fake_printer):
        task = asyncio.create_task(consume())
        # Give the SSE connection time to establish
        await asyncio.sleep(0.05)
        bus.publish(channel, test_event)
        await asyncio.wait_for(task, timeout=0.5)

    assert len(received) == 1
    assert received[0]["event_type"] == "job.state_changed"
    assert received[0]["from_state"] == "queued"
    assert received[0]["to_state"] == "printing"
```

- [ ] **Step 2: Run to confirm RED (likely passes immediately if streaming works, but confirm)**

```bash
cd backend && python -m pytest tests/unit/api/test_events_route.py::test_event_delivered_to_sse_stream -v 2>&1 | tail -20
```

If RED: fix the streaming test harness (ensure `ASGITransport` and `_inner` are correctly referenced).
If GREEN immediately: note it and move on.

- [ ] **Step 3: Run full events test file**

```bash
cd backend && python -m pytest tests/unit/api/test_events_route.py -v 2>&1 | tail -20
```

Expected: all 3 tests PASSED.

- [ ] **Step 4: Commit**

```bash
cd backend && git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" \
  commit -m "$(cat <<'EOF'
test(api): SSE stream delivery test — event arrives via httpx AsyncClient within 200 ms

Uses httpx ASGITransport to consume the streaming response. Publishes a
BusEvent directly to app.state.event_bus after a 50 ms settle; asserts
the parsed data frame arrives within 500 ms total.

Refs #14
EOF
)"
```

---

## Task 6: Fragment templates + `_render_fragment` wiring

**Files:**
- Create: `backend/app/templates/fragments/job_state.html`
- Create: `backend/app/templates/fragments/printer_status.html`
- Create: `backend/app/templates/fragments/tape_status.html`
- Modify: `backend/tests/unit/api/test_events_route.py` — add fragment render test

- [ ] **Step 1: Write failing fragment render test**

Append to `backend/tests/unit/api/test_events_route.py`:

```python
@pytest.mark.asyncio
async def test_render_fragment_job_state_returns_html() -> None:
    from app.api.routes.events import _render_fragment
    from app.services.event_bus import BusEvent
    from datetime import UTC, datetime

    event = BusEvent(
        channel="printer:x:queue",
        event_id=1,
        event_type="job.state_changed",
        timestamp=datetime.now(UTC),
        data={
            "job_id": "j1",
            "from_state": "queued",
            "to_state": "printing",
            "queue_depth": 2,
            "error_code": None,
        },
    )
    html = await _render_fragment(event)
    assert "<" in html  # non-empty HTML fragment
    assert "printing" in html


@pytest.mark.asyncio
async def test_render_fragment_printer_status_online() -> None:
    from app.api.routes.events import _render_fragment
    from app.services.event_bus import BusEvent
    from datetime import UTC, datetime

    event = BusEvent(
        channel="printer:x:state",
        event_id=1,
        event_type="printer.status",
        timestamp=datetime.now(UTC),
        data={"hr_printer_status": "idle", "error_flags": [], "online": True},
    )
    html = await _render_fragment(event)
    assert "idle" in html
    assert "status-online" in html


@pytest.mark.asyncio
async def test_render_fragment_tape_changed() -> None:
    from app.api.routes.events import _render_fragment
    from app.services.event_bus import BusEvent
    from datetime import UTC, datetime

    event = BusEvent(
        channel="printer:x:tape",
        event_id=1,
        event_type="printer.tape_changed",
        timestamp=datetime.now(UTC),
        data={"from_mm": 12, "to_mm": 24, "tape_label": "24mm"},
    )
    html = await _render_fragment(event)
    assert "24mm" in html


@pytest.mark.asyncio
async def test_render_fragment_unknown_type_returns_empty() -> None:
    from app.api.routes.events import _render_fragment
    from app.services.event_bus import BusEvent
    from datetime import UTC, datetime

    event = BusEvent(
        channel="printer:x:other",
        event_id=1,
        event_type="unknown.type",
        timestamp=datetime.now(UTC),
        data={},
    )
    html = await _render_fragment(event)
    assert html == ""
```

- [ ] **Step 2: Run to confirm RED**

```bash
cd backend && python -m pytest tests/unit/api/test_events_route.py::test_render_fragment_job_state_returns_html -v 2>&1 | tail -10
```

Expected: `TemplateNotFound: fragments/job_state.html`.

- [ ] **Step 3: Create fragment templates**

```html
<!-- backend/app/templates/fragments/job_state.html -->
<div class="job-state-fragment">
  <span class="state-badge state-{{ to_state }}">{{ to_state | replace('_', ' ') | title }}</span>
  {% if queue_depth > 0 %}
  <span class="queue-depth">{{ queue_depth }} job{% if queue_depth != 1 %}s{% endif %} queued</span>
  {% endif %}
  {% if error_code %}
  <span class="error-code">Error: {{ error_code }}</span>
  {% endif %}
  <small class="ts">{{ timestamp }}</small>
</div>
```

```html
<!-- backend/app/templates/fragments/printer_status.html -->
<div class="printer-status-fragment">
  <span class="status-badge {% if online %}status-online{% else %}status-offline{% endif %}">
    {{ hr_printer_status | replace('_', ' ') | title }}
  </span>
  {% if error_flags %}
  <span class="error-flags">{{ error_flags | join(', ') }}</span>
  {% endif %}
  <small class="ts">{{ timestamp }}</small>
</div>
```

```html
<!-- backend/app/templates/fragments/tape_status.html -->
<div class="tape-status-fragment">
  {% if to_mm is not none %}
  <span class="tape-badge">
    {{ tape_label if tape_label else (to_mm | string + 'mm') }} loaded
  </span>
  {% else %}
  <span class="tape-badge tape-empty">No tape loaded</span>
  {% endif %}
  <small class="ts">{{ timestamp }}</small>
</div>
```

- [ ] **Step 4: Run to confirm GREEN**

```bash
cd backend && python -m pytest tests/unit/api/test_events_route.py -v 2>&1 | tail -20
```

Expected: all 7 tests PASSED.

- [ ] **Step 5: Commit**

```bash
cd backend && git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" \
  commit -m "$(cat <<'EOF'
feat(api): SSE fragment templates — job_state, printer_status, tape_status Jinja2 partials

Three minimal HTML fragments under templates/fragments/ for HTMX sse-swap
injection. printer_status.html renders status-online/status-offline CSS class.
job_state.html shows to_state badge + queue depth. tape_status.html shows
loaded tape label or 'No tape loaded'. _render_fragment returns empty string
for unknown event types (safe fallback).

Refs #14
EOF
)"
```

---

## Task 7: HTMX wiring on QR templates + static assets

**Files:**
- Modify: `backend/app/templates/qr/loc.html`
- Modify: `backend/app/templates/qr/asset.html`
- Modify: `backend/app/templates/qr/spool.html`
- Modify: `backend/app/templates/qr/product.html`
- Create: `backend/app/static/htmx.min.js` — download HTMX v2
- Create: `backend/app/static/sse.js` — download HTMX SSE extension v2
- Modify: `backend/app/main.py` — mount `StaticFiles` for `/static`
- Modify: `backend/app/api/routes/qr.py` — pass `printer_id` to template context
- Create: `backend/tests/unit/api/test_qr_routes.py` (append) — assert SSE attributes present

- [ ] **Step 1: Write failing test for SSE attributes in QR templates**

Append to `backend/tests/unit/api/test_qr_routes.py`:

```python
# Append to existing test_qr_routes.py

def test_spool_page_has_sse_connect_attribute(client: TestClient) -> None:
    """Spool landing page must include the HTMX SSE connect block."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.services.lookup_service import LookupResult

    fake_result = LookupResult(
        title="PLA Silver 1kg",
        qr_payload="http://spoolman.example/spool/1",
        entity_id="1",
        app="spoolman",
    )
    with patch(
        "app.api.routes.qr._lookup_service.lookup",
        new_callable=AsyncMock,
        return_value=fake_result,
    ):
        resp = client.get("/spool/1")
    assert resp.status_code == 200
    assert 'sse-connect="/api/events?printer_id=' in resp.text
    assert 'hx-ext="sse"' in resp.text
```

- [ ] **Step 2: Run to confirm RED**

```bash
cd backend && python -m pytest tests/unit/api/test_qr_routes.py::test_spool_page_has_sse_connect_attribute -v 2>&1 | tail -10
```

Expected: assertion failure — `sse-connect` attribute not present yet.

- [ ] **Step 3: Download HTMX and SSE extension (self-hosted)**

```bash
mkdir -p backend/app/static
curl -fsSL https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js -o backend/app/static/htmx.min.js
curl -fsSL https://unpkg.com/htmx-ext-sse@2.2.2/sse.js -o backend/app/static/sse.js
```

Verify files are non-empty:

```bash
wc -l backend/app/static/htmx.min.js backend/app/static/sse.js
```

Expected: both show > 0 lines.

- [ ] **Step 4: Mount StaticFiles in `main.py`**

Add import at top of `main.py`:

```python
from fastapi.staticfiles import StaticFiles
```

Inside `create_app()`, after all `app.include_router` calls, add:

```python
    _static_dir = Path(__file__).parent / "static"
    if _static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")
```

Also add `from pathlib import Path` if not already imported.

- [ ] **Step 5: Update `qr.py` to pass `printer_id` to template context**

In `backend/app/api/routes/qr.py`, update each handler to read `printer_id` from `request.app.state` and pass it to the template context. Modify each handler's return call for the success path:

For `loc_landing`, `asset_landing`, `spool_landing`, `product_landing` — in the success branch, add `"printer_id": str(getattr(request.app.state, "printer_id", ""))` to the context dict. For example:

```python
        return templates.TemplateResponse(
            request=request,
            name="qr/spool.html",
            context={
                "title": data.title,
                "entity_id": entity_id,
                "name": data.title,
                "external_url": data.qr_payload,
                "not_found": False,
                "printer_id": str(getattr(request.app.state, "printer_id", "")),
            },
        )
```

Apply the same addition to all four handlers' success branches (not-found branches do not need it — they show no SSE block).

- [ ] **Step 6: Add SSE block to each QR template**

Add to `spool.html` (and equivalently to `loc.html`, `asset.html`, `product.html`) before `</body>`:

```html
  <!-- Phase 6b: SSE live updates — loaded from self-hosted static/ -->
  <script src="/static/htmx.min.js"></script>
  <script src="/static/sse.js"></script>

  {% if not not_found and printer_id %}
  <div id="sse-root"
       hx-ext="sse"
       sse-connect="/api/events?printer_id={{ printer_id }}">

    <div id="printer-status"
         sse-swap="printer.status"
         hx-swap="innerHTML">
    </div>

    <div id="job-queue"
         sse-swap="job.state_changed"
         hx-swap="innerHTML">
    </div>

    <div id="tape-status"
         sse-swap="printer.tape_changed"
         hx-swap="innerHTML">
    </div>
  </div>
  {% endif %}
```

Apply the identical block to `loc.html`, `asset.html`, and `product.html`.

- [ ] **Step 7: Run to confirm GREEN**

```bash
cd backend && python -m pytest tests/unit/api/test_qr_routes.py -v 2>&1 | tail -20
```

Expected: all QR tests pass including the new SSE attribute assertion.

- [ ] **Step 8: Lint + type check**

```bash
cd backend && ruff check app/api/routes/qr.py app/main.py && ruff format --check app/api/routes/qr.py app/main.py && mypy app/api/routes/qr.py app/main.py
```

Expected: no errors.

- [ ] **Step 9: Commit**

```bash
cd backend && git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" \
  commit -m "$(cat <<'EOF'
feat(ui): HTMX SSE wiring on QR landing pages — sse-connect + sse-swap blocks + self-hosted JS

All four QR templates (loc, asset, spool, product) get an #sse-root div
with hx-ext="sse" and sse-connect="/api/events?printer_id={{ printer_id }}".
Three child divs target printer.status, job.state_changed, tape_changed.
HTMX v2 and sse.js self-hosted under app/static/ (offline-safe deployments).
StaticFiles mounted at /static in create_app(). qr.py passes printer_id
from app.state to template context.

Refs #14
EOF
)"
```

---

## Task 8: Prometheus metrics + lifespan producer wiring

**Files:**
- Modify: `backend/app/main.py` — wire StatusProbeProducer + TapeChangeProducer + PrintQueueProducer in lifespan; add Prometheus counters
- Create: `backend/tests/unit/api/test_events_route.py` (append) — test healthz shows sse_active_subscribers > 0

- [ ] **Step 1: Write failing test for Prometheus counters**

Append to `backend/tests/unit/api/test_events_route.py`:

```python
def test_healthz_shows_sse_active_subscribers(client_with_bus: TestClient) -> None:
    """After subscribing, /healthz.sse_active_subscribers must be > 0."""
    bus: EventBus = _inner.state.event_bus
    printer_id = uuid.uuid4()
    bus.subscribe(f"printer:{printer_id}:queue", "test-sub")

    resp = client_with_bus.get("/healthz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["sse_active_subscribers"] >= 1
```

- [ ] **Step 2: Run to confirm RED**

```bash
cd backend && python -m pytest tests/unit/api/test_events_route.py::test_healthz_shows_sse_active_subscribers -v 2>&1 | tail -10
```

Expected: may fail because `healthz` now requires `Request` — if `test_lifespan.py` or the TestClient calls it without state, fix accordingly. If it already passes, move on.

- [ ] **Step 3: Add Prometheus counters to `events.py`**

Add after the imports block in `backend/app/api/routes/events.py`:

```python
from prometheus_client import Counter, Gauge

sse_connections_total = Counter(
    "printer_hub_sse_connections_total",
    "Total SSE connections opened",
    ["printer_id"],
)

sse_events_published_total = Counter(
    "printer_hub_sse_events_published_total",
    "Total events published to the SSE stream",
    ["channel"],
)

sse_events_dropped_total = Counter(
    "printer_hub_sse_events_dropped_total",
    "Total events dropped due to slow subscribers",
    ["channel", "subscriber_id"],
)

sse_active_subscribers = Gauge(
    "printer_hub_sse_active_subscribers",
    "Current number of active SSE subscribers",
)
```

In `_sse_stream`, after the subscriber-cap check passes and queues are created, add:

```python
    sse_connections_total.labels(printer_id=str(printer_id)).inc()
    sse_active_subscribers.inc()
```

In the `finally` block of `_sse_stream`, before the log line, add:

```python
        sse_active_subscribers.dec()
```

In the event-delivery loop, after computing `dropped`, add:

```python
                if dropped:
                    sse_events_dropped_total.labels(
                        channel=event.channel, subscriber_id=subscriber_id
                    ).inc(dropped)
                sse_events_published_total.labels(channel=event.channel).inc()
```

- [ ] **Step 4: Wire producers in lifespan in `main.py`**

Add imports to `main.py`:

```python
from app.services.producers.print_queue_producer import PrintQueueProducer
from app.services.producers.status_probe_producer import StatusProbeProducer
from app.services.producers.tape_change_producer import TapeChangeProducer
```

Replace the `queue = PrintQueue(printers=[printer])` line in `lifespan` with:

```python
    pq_producer = PrintQueueProducer(bus=event_bus)
    queue = PrintQueue(
        printers=[printer],
        on_state_change=pq_producer.handle_transition,
    )
```

After `await queue.start()`, add the StatusProbe + TapeChange producers:

```python
    tape_producer = TapeChangeProducer(bus=event_bus, tape_registry=tape_registry)
    status_producer: StatusProbeProducer | None = None
    if discovery_host:
        status_producer = StatusProbeProducer(
            bus=event_bus,
            printer_id=str(printer.id),
            host=discovery_host,
            interval_s=settings_sse.sse_probe_interval_s,
            community=settings_sse.printer_snmp_community,
            tape_change_producer=tape_producer,
        )
        await status_producer.start()
```

In the `finally` block of `lifespan`, before `await queue.stop(...)`, add:

```python
        if status_producer is not None:
            await status_producer.stop()
```

- [ ] **Step 5: Run full unit suite to confirm GREEN**

```bash
cd backend && python -m pytest tests/unit/ -v --tb=short 2>&1 | tail -30
```

Expected: all unit tests pass (no regressions).

- [ ] **Step 6: Lint + type check**

```bash
cd backend && ruff check app/api/routes/events.py app/main.py && ruff format --check app/api/routes/events.py app/main.py && mypy app/api/routes/events.py app/main.py
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
cd backend && git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" \
  commit -m "$(cat <<'EOF'
feat(api): Prometheus SSE counters + producers wired into lifespan

Four prometheus_client metrics: sse_connections_total, sse_events_published_total,
sse_events_dropped_total, sse_active_subscribers (Gauge). Counters incremented in
_sse_stream on connect/event/drop/disconnect. PrintQueueProducer, StatusProbeProducer,
TapeChangeProducer wired in lifespan: ProbeProducer starts only when a printer host
is configured; stopped cleanly in the finally block.

Refs #14
EOF
)"
```

---

## Task 9: Integration tests (end-to-end SSE delivery + flush timing)

**Files:**
- Create: `backend/tests/integration/test_phase6b_sse.py`
- Create: `backend/tests/integration/test_sse_flush.py`

- [ ] **Step 1: Write end-to-end integration test**

```python
# backend/tests/integration/test_phase6b_sse.py
"""Integration test: full lifespan → SSE connection → event delivery.

Uses the mock backend (configured in conftest.py via _mock_backend_env)
so no real hardware is required. Tests that a BusEvent published directly
to app.state.event_bus arrives on the SSE stream within 500 ms.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app as _app_wrapper
from app.services.event_bus import BusEvent

_inner = _app_wrapper._app  # type: ignore[attr-defined]


@pytest.fixture()
def lifespan_client() -> TestClient:
    """TestClient that runs the full lifespan."""
    with TestClient(_app_wrapper, raise_server_exceptions=True) as client:
        yield client


@pytest.mark.asyncio
async def test_bus_event_arrives_via_sse_stream() -> None:
    """Publish a BusEvent to the bus; assert it arrives on the SSE stream."""
    from httpx import ASGITransport

    printer_id = uuid.uuid4()

    # Wire a live bus with a known printer_id
    bus = _inner.state.event_bus if hasattr(_inner.state, "event_bus") else None
    if bus is None:
        from app.services.event_bus import EventBus
        bus = EventBus(queue_size=8)
        _inner.state.event_bus = bus

    from unittest.mock import AsyncMock, MagicMock, patch

    fake_printer = MagicMock()
    fake_printer.id = str(printer_id)

    channel = f"printer:{printer_id}:queue"
    test_event = BusEvent(
        channel=channel,
        event_id=1,
        event_type="job.state_changed",
        timestamp=datetime.now(UTC),
        data={
            "job_id": str(uuid.uuid4()),
            "from_state": "queued",
            "to_state": "printing",
            "queue_depth": 0,
            "error_code": None,
        },
    )

    received: list[dict] = []

    async def consume() -> None:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=_inner), base_url="http://test"
        ) as client:
            async with client.stream(
                "GET", f"/api/events?printer_id={printer_id}"
            ) as response:
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        received.append(json.loads(line[5:].strip()))
                        break

    with patch(
        "app.api.routes.events.printers_repo.get",
        new_callable=AsyncMock,
        return_value=fake_printer,
    ):
        task = asyncio.create_task(consume())
        await asyncio.sleep(0.05)
        bus.publish(channel, test_event)
        await asyncio.wait_for(task, timeout=1.0)

    assert len(received) == 1
    assert received[0]["event_type"] == "job.state_changed"
```

- [ ] **Step 2: Write flush-timing test**

```python
# backend/tests/integration/test_sse_flush.py
"""SSE flush-timing tests — verify bytes arrive promptly, not buffered.

Marked @pytest.mark.slow so they are excluded from the fast CI run
(add '-m "not slow"' to the default pytest command) and included in the
nightly integration job.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.main import app as _app_wrapper
from app.services.event_bus import BusEvent, EventBus

_inner = _app_wrapper._app  # type: ignore[attr-defined]


@pytest.mark.slow
@pytest.mark.asyncio
async def test_first_sse_byte_arrives_within_200ms() -> None:
    """The first SSE data frame must arrive within 200 ms of publish."""
    from httpx import ASGITransport

    printer_id = uuid.uuid4()
    bus = EventBus(queue_size=8)
    _inner.state.event_bus = bus

    channel = f"printer:{printer_id}:queue"
    event = BusEvent(
        channel=channel,
        event_id=1,
        event_type="job.state_changed",
        timestamp=datetime.now(UTC),
        data={
            "job_id": "j1",
            "from_state": "queued",
            "to_state": "printing",
            "queue_depth": 0,
            "error_code": None,
        },
    )

    first_byte_time: list[float] = []
    publish_time: list[float] = []

    fake_printer = MagicMock()
    fake_printer.id = str(printer_id)

    async def consume() -> None:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=_inner), base_url="http://test"
        ) as client:
            async with client.stream(
                "GET", f"/api/events?printer_id={printer_id}"
            ) as response:
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        first_byte_time.append(time.monotonic())
                        break

    with patch(
        "app.api.routes.events.printers_repo.get",
        new_callable=AsyncMock,
        return_value=fake_printer,
    ):
        task = asyncio.create_task(consume())
        await asyncio.sleep(0.05)
        publish_time.append(time.monotonic())
        bus.publish(channel, event)
        await asyncio.wait_for(task, timeout=1.0)

    latency = first_byte_time[0] - publish_time[0]
    assert latency < 0.2, f"SSE latency {latency:.3f}s exceeds 200 ms threshold"
```

- [ ] **Step 3: Run integration tests**

```bash
cd backend && python -m pytest tests/integration/test_phase6b_sse.py -v 2>&1 | tail -15
```

Expected: PASSED.

```bash
cd backend && python -m pytest tests/integration/test_sse_flush.py -v -m slow 2>&1 | tail -15
```

Expected: PASSED (latency well under 200 ms in-process).

- [ ] **Step 4: Commit**

```bash
cd backend && git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" \
  commit -m "$(cat <<'EOF'
test(integration): Phase 6b SSE end-to-end + flush-timing tests

test_phase6b_sse.py: publishes BusEvent directly to app.state.event_bus;
asserts data frame arrives via httpx AsyncClient within 1s. test_sse_flush.py
(marked slow): measures wall-clock latency from publish to first SSE byte;
asserts < 200 ms. Flush test excluded from default CI run via -m "not slow".

Refs #14
EOF
)"
```

---

## Task 10: OpenAPI completeness gate update + final verification

**Files:**
- Modify: `backend/tests/api/test_openapi_completeness.py` — bump range 22-30 → 23-31

- [ ] **Step 1: Write the assertion update (test change first)**

In `backend/tests/api/test_openapi_completeness.py`, find and update the bounds:

```python
# Find this line:
    assert 22 <= count <= 30, (
        f"Operation count {count} is outside the expected 22-30 range.  "
# Replace with:
    assert 23 <= count <= 31, (
        f"Operation count {count} is outside the expected 23-31 range.  "
```

Also update the docstring comment in that test function from `22-30` to `23-31`.

- [ ] **Step 2: Run OpenAPI completeness test to confirm it passes with the new route**

```bash
cd backend && python -m pytest tests/api/test_openapi_completeness.py -v 2>&1 | tail -20
```

Expected: all assertions pass. If `test_every_route_has_tag_and_summary` fails for the new `/api/events` route, verify `events.py` has `summary=`, `description=`, and `tags=["events"]` on the `@router.get` decorator — all already present in the Task 4 implementation.

- [ ] **Step 3: Run full test suite**

```bash
cd backend && python -m pytest tests/ -m "not slow" --tb=short -q 2>&1 | tail -30
```

Expected: all tests pass, coverage ≥ 91%.

- [ ] **Step 4: Lint + type check full app**

```bash
cd backend && ruff check app/ tests/ && ruff format --check app/ tests/ && mypy app/
```

Expected: no errors.

- [ ] **Step 5: Alembic check**

```bash
cd backend && alembic check
```

Expected: clean (no pending schema changes — Phase 6b adds no DB tables).

- [ ] **Step 6: Commit**

```bash
cd backend && git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" \
  commit -m "$(cat <<'EOF'
test(api): bump OpenAPI completeness gate to 23-31 operations for GET /api/events

One new SSE endpoint registered in the OpenAPI schema. Gate range updated
from 22-30 to 23-31. All completeness assertions (tag, summary, response
model, path case) pass for the new events route.

Refs #14
EOF
)"
```

---

## Task 11: Reverse-proxy compat docs + architecture.md link

**Files:**
- Create: `docs/architecture/sse.md`
- Modify: `docs/architecture.md` (if it exists) or note in `docs/decisions/0011-openapi-as-api-contract.md` — add SSE section link

- [ ] **Step 1: Create `docs/architecture/sse.md`**

```markdown
# SSE Reverse-Proxy Compatibility

The `/api/events` endpoint streams `text/event-stream` responses. All modern
reverse proxies buffer responses by default — this breaks SSE because the
client receives nothing until the buffer flushes or the connection closes.

The backend sets `X-Accel-Buffering: no` on every SSE response. Proxies that
honour this header (Traefik v3, Nginx with the ngx_http_proxy module) will
flush immediately. For proxies that do not, explicit configuration is required.

## Traefik v3

Traefik v3 respects `X-Accel-Buffering: no` when `passHostHeader` is enabled
(the default). No extra configuration is needed beyond what the backend already
sets. To be explicit, add a middleware:

```yaml
# In Docker Compose labels or a static middleware file
traefik.http.middlewares.sse-flush.headers.customResponseHeaders.X-Accel-Buffering=no
traefik.http.routers.printer-hub-sse.rule=PathPrefix(`/api/events`)
traefik.http.routers.printer-hub-sse.middlewares=sse-flush@docker
```

## Caddy

```caddyfile
@sse path /api/events*
handle @sse {
    reverse_proxy backend:8090 {
        flush_interval -1
    }
}
```

`flush_interval -1` instructs Caddy to flush on every write. The example
compose file `examples/compose.caddy.yml` should use this block.

## Nginx / nginx-proxy

```nginx
location /api/events {
    proxy_pass http://backend:8090;
    proxy_buffering off;
    proxy_cache off;
    proxy_set_header Connection '';
    proxy_http_version 1.1;
    chunked_transfer_encoding on;
}
```

## Pangolin (HomeLab deployment)

Pangolin tunnels sit in front of Traefik. The `X-Accel-Buffering: no` header
set by the backend propagates through the tunnel chain to the browser. No
Pangolin-specific configuration is required beyond the Traefik settings above.
This pattern is verified to work with Gotify (also SSE-based) behind the same
Pangolin + Traefik stack.

## Verification

After deploying, verify SSE is working end-to-end:

```bash
# Replace <host> and <printer-id> with real values
curl -N -H "Accept: text/event-stream" \
  "https://<host>/api/events?printer_id=<printer-id>"
# You should see ": keepalive" comment lines every 30 seconds.
```

If the connection returns immediately with no output, the proxy is buffering.
Check `X-Accel-Buffering` in the response headers:

```bash
curl -I "https://<host>/api/events?printer_id=<printer-id>"
# Expect: X-Accel-Buffering: no
```
```

- [ ] **Step 2: Check if `docs/architecture.md` exists**

```bash
ls /opt/repos/label-printer-hub/docs/architecture.md 2>/dev/null || echo "NOT FOUND"
```

If found, append a link:

```markdown
## SSE EventBus (Phase 6b)

See [SSE Reverse-Proxy Compatibility](architecture/sse.md) for proxy
configuration required to make the `/api/events` endpoint work through
Traefik, Caddy, Nginx, and Pangolin.
```

If not found, add a note to `docs/decisions/0011-openapi-as-api-contract.md` under a new section heading:

```markdown
## SSE endpoint

See `docs/architecture/sse.md` for reverse-proxy flush configuration
required by the `/api/events` Server-Sent Events endpoint.
```

- [ ] **Step 3: Commit**

```bash
cd /opt/repos/label-printer-hub && git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" \
  commit -m "$(cat <<'EOF'
docs(docs): SSE reverse-proxy compat guide — Traefik, Caddy, Nginx, Pangolin flush config

New docs/architecture/sse.md documents X-Accel-Buffering: no header,
per-proxy flush configuration, and a curl verification procedure.
Pangolin section notes the header propagates through the tunnel chain
(verified with Gotify as reference). Link added to architecture docs.

Refs #14
EOF
)"
```

---

## Task 12: Final verify + PR readiness

**Orchestrator-run only — no subagent needed.**

- [ ] **Step 1: Full test suite (excluding slow)**

```bash
cd backend && python -m pytest tests/ -m "not slow" -q 2>&1 | tail -20
```

Expected: all pass, no failures.

- [ ] **Step 2: Coverage check**

```bash
cd backend && python -m pytest tests/ -m "not slow" --cov=app --cov-report=term-missing -q 2>&1 | grep "TOTAL"
```

Expected: coverage ≥ 91%.

- [ ] **Step 3: mypy strict**

```bash
cd backend && mypy app/ 2>&1 | tail -10
```

Expected: `Success: no issues found`.

- [ ] **Step 4: ruff**

```bash
cd backend && ruff check app/ tests/ && ruff format --check app/ tests/
```

Expected: no output (clean).

- [ ] **Step 5: alembic**

```bash
cd backend && alembic check
```

Expected: clean.

- [ ] **Step 6: Commit log**

```bash
git -C /opt/repos/label-printer-hub log main..HEAD --oneline
```

Expected: 12 commits (Tasks 0–11).

- [ ] **Step 7: Push and open PR**

Orchestrator pushes branch and opens PR with body:

```
## Summary

- `EventBus` singleton (in-process asyncio, drop-oldest backpressure, queue depth 32)
- `PrintQueueProducer` wired to `PrintQueue.on_state_change` callback
- `StatusProbeProducer` 30 s SNMP poll loop with change-only debounce
- `TapeChangeProducer` collaborator deriving tape-change events from probe results
- `GET /api/events?printer_id=<uuid>` SSE endpoint (429 cap, idle timeout, heartbeat)
- Three Jinja2 fragment templates under `templates/fragments/`
- HTMX SSE wiring on all four QR landing pages (`loc`, `asset`, `spool`, `product`)
- HTMX v2 + SSE extension self-hosted under `app/static/`
- Prometheus metrics: `sse_connections_total`, `sse_events_published_total`, `sse_events_dropped_total`, `sse_active_subscribers`
- `/healthz` `sse_active_subscribers` field
- Reverse-proxy compat guide (`docs/architecture/sse.md`)
- OpenAPI gate bumped to 23–31 operations

## Test plan

- [ ] All unit tests pass (`pytest tests/unit/ -q`)
- [ ] Integration tests pass (`pytest tests/integration/ -q`)
- [ ] Slow flush-timing test passes (`pytest tests/integration/test_sse_flush.py -m slow`)
- [ ] OpenAPI completeness gate passes (`pytest tests/api/ -q`)
- [ ] `mypy app/` clean
- [ ] `ruff check app/ tests/` clean
- [ ] `alembic check` clean
- [ ] Coverage ≥ 91%

Closes #14, Refs #22
```

---

## Self-review

**Spec coverage:**

| Spec section | Covered by task(s) |
|---|---|
| §2.1 Component Overview (EventBus, Producers, SSE endpoint) | T0, T2, T3, T4 |
| §2.2 EventBus API (`BusEvent`, `publish`, `subscribe`, `unsubscribe`, `next_event_id`) | T0 |
| §2.3 Channel scheme (`printer:{uuid}:queue/state/tape`) | T0, T2, T3, T4 |
| §2.4 Drop-oldest, queue depth 32, configurable | T0, T1 |
| §2.5 Event shape (all three data dicts) | T2, T3, T4, T6 |
| §3.1 PrintQueueProducer + callback hook in PrintQueue | T2 |
| §3.2 StatusProbeProducer SNMP loop + debounce | T3 |
| §3.3 TapeChangeProducer + StatusProbe integration | T3 |
| §4.1 SSE route, headers, subscriber cap, generator | T4, T5 |
| §4.2 Last-Event-ID logging (no replay) | T4 |
| §4.3 `_render_fragment` + HTML-fragment-not-JSON rationale | T6 |
| §5.1 HTMX template changes (`hx-ext="sse"`, `sse-connect`) | T7 |
| §5.2 Fragment templates (`fragments/*.html`) | T6 |
| §6 Resource limits via Settings | T1 |
| §7 Reverse-proxy compat (Traefik, Caddy, Nginx, Pangolin) | T11 |
| §8.1–8.4 Testing strategy (unit EventBus, route, producers, integration) | T0, T3, T5, T9 |
| §8.5 Flush timing (slow tests) | T9 |
| §10.1 Prometheus counters | T8 |
| §10.2 Structured logging (printer_id, subscriber_id, reason) | T4 (events.py `_log.info`) |
| §10.3 `/healthz` `sse_active_subscribers` field | T1, T8 |
| §11 Implementation order (15 spec tasks → 12 plan tasks) | all |

**Placeholder scan:** No "TBD", "Similar to Task N", "implement appropriately", or "add appropriate" in any task. Every code block is complete and copy-pasteable.

**Type consistency:**
- `BusEvent` defined in T0 — used in T2, T3, T4, T5, T6, T9 ✓
- `EventBus` defined in T0 — used in T1, T2, T3, T4, T8 ✓
- `PrintQueueProducer.handle_transition(job, from_state, to_state)` defined in T2 — wired in T8 ✓
- `StatusProbeProducer.start()/stop()` defined in T3 — called in T8 ✓
- `TapeChangeProducer.on_probe_result(printer_id, old, new)` defined in T3 — called in T3 (StatusProbeProducer._loop) ✓
- `_render_fragment(event: BusEvent) -> str` defined in T4 — tested in T6 ✓
- `_MAX_SUBSCRIBERS_PER_PRINTER` constant defined in T4 — imported in T4 test ✓
- `sse_active_subscribers` Gauge defined in T8 — incremented/decremented in T8 ✓

---

## Execution

Subagent-driven (recommended): one implementer per task, orchestrator reviews between tasks. Estimated ~3h based on Phase 6a pace at 12 tasks.
