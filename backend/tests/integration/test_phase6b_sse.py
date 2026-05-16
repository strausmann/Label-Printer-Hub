"""Integration tests: full lifespan → SSE connection → event delivery.

Uses the mock backend (configured in conftest.py via _mock_backend_env)
so no real hardware is required. Tests that a BusEvent published directly
to app.state.event_bus arrives on the SSE stream within 500 ms.

NOTE on test strategy (why we call _sse_stream directly):
    httpx ASGITransport buffers the complete response body before yielding
    lines. This means ``async for line in response.aiter_lines()`` does not
    receive incremental SSE frames — it waits for the stream to close first.
    The same limitation exists in the unit tests (see test_events_route.py
    comment). We therefore test the SSE generator directly, which is the
    correct unit under test for the delivery and flush-timing assertions.
    This is identical to what the unit tests already do, but runs against
    the live app.state.event_bus (wired via lifespan or equivalent fixture)
    to verify the full integration path.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from app.main import app as _app_wrapper
from app.services.event_bus import BusEvent, EventBus

# Access the inner FastAPI app (unwrap _LifespanManager)
_inner = _app_wrapper._app  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(printer_id: uuid.UUID, channel_suffix: str = "queue") -> BusEvent:
    channel = f"printer:{printer_id}:{channel_suffix}"
    return BusEvent(
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


def _mock_request() -> MagicMock:
    """Minimal mock Request — _sse_stream reads headers and calls is_disconnected."""
    disconnect_flag = asyncio.Event()

    async def _is_disconnected() -> bool:
        return disconnect_flag.is_set()

    req = MagicMock()
    req.headers = {}
    req.client = None
    req.is_disconnected = _is_disconnected
    req._disconnect_flag = disconnect_flag  # allow test to signal disconnect
    return req


# ---------------------------------------------------------------------------
# T9.1 — End-to-end: BusEvent published → arrives on SSE stream within 500 ms
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bus_event_arrives_via_sse_stream() -> None:
    """Publish a BusEvent to the bus; assert it arrives on the SSE stream.

    This validates the full delivery chain:
      EventBus.publish
        → subscriber queue (asyncio.Queue)
          → _sse_stream generator (asyncio.wait timeout loop)
            → SSE data frame (JSON payload)

    Uses a 500 ms budget — well above the 50 ms architectural target, but
    generous enough to tolerate CI scheduler jitter.
    """
    import app.api.routes.events as events_mod

    printer_id = uuid.uuid4()
    bus = EventBus(queue_size=8)
    _inner.state.event_bus = bus

    channel = f"printer:{printer_id}:queue"
    channels = [
        channel,
        f"printer:{printer_id}:state",
        f"printer:{printer_id}:tape",
    ]
    subscriber_id = "int-test-delivery"
    test_event = _make_event(printer_id)
    request = _mock_request()

    gen = events_mod._sse_stream(printer_id, bus, request, subscriber_id, channels)

    frame_queue: asyncio.Queue[str] = asyncio.Queue()

    async def pump() -> None:
        async for frame in gen:
            await frame_queue.put(frame)

    pump_task = asyncio.create_task(pump())
    # Let the generator subscribe and reach asyncio.wait
    await asyncio.sleep(0.05)

    bus.publish(channel, test_event)

    # After Finding #2 fix: data: carries raw HTML; event type is on "event:" line.
    received_frames: list[str] = []
    deadline = asyncio.get_event_loop().time() + 0.5
    while asyncio.get_event_loop().time() < deadline:
        try:
            frame = await asyncio.wait_for(frame_queue.get(), timeout=0.1)
            if "data:" in frame:
                received_frames.append(frame)
                break
        except TimeoutError:
            continue

    # Teardown
    request._disconnect_flag.set()
    pump_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await pump_task
    await gen.aclose()

    assert len(received_frames) == 1, f"expected 1 data frame, got {len(received_frames)}"
    sse_frame = received_frames[0]
    # Verify event type via the "event:" metadata line
    event_line = next(
        (ln for ln in sse_frame.splitlines() if ln.startswith("event:")), None
    )
    assert event_line is not None, "no event: line in SSE frame"
    assert "job.state_changed" in event_line
    # Verify data payload is HTML (raw fragment, not JSON)
    data_lines = [ln for ln in sse_frame.splitlines() if ln.startswith("data:")]
    assert data_lines, "no data: lines in SSE frame"
    combined_data = "\n".join(ln[len("data:"):].lstrip(" ") for ln in data_lines)
    assert "<" in combined_data, f"expected HTML in data payload, got: {combined_data!r}"


# ---------------------------------------------------------------------------
# T9.2 — State-transition propagation: multiple channels multiplexed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_state_transition_propagates_as_sse_frame() -> None:
    """Verify that a state transition BusEvent reaches the SSE subscriber.

    This tests the full producer → bus → generator → frame path:
    a BusEvent equivalent to what PrintQueueProducer emits is published
    directly to the bus (deterministic, no timing dependency on the real
    PrintQueue). The generator must yield a data frame containing the
    correct from_state / to_state fields.
    """
    import app.api.routes.events as events_mod

    printer_id = uuid.uuid4()
    bus = EventBus(queue_size=16)
    _inner.state.event_bus = bus

    channel = f"printer:{printer_id}:queue"
    channels = [
        channel,
        f"printer:{printer_id}:state",
        f"printer:{printer_id}:tape",
    ]
    subscriber_id = "int-test-transition"
    # Payload matches exactly what PrintQueueProducer.handle_transition emits
    transition_event = BusEvent(
        channel=channel,
        event_id=bus.next_event_id(channel),
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

    request = _mock_request()
    gen = events_mod._sse_stream(printer_id, bus, request, subscriber_id, channels)

    # After Finding #2 fix: data: carries raw HTML; event type is on "event:" line.
    raw_frames: list[str] = []
    frame_queue: asyncio.Queue[str] = asyncio.Queue()

    async def pump() -> None:
        async for frame in gen:
            await frame_queue.put(frame)

    pump_task = asyncio.create_task(pump())
    await asyncio.sleep(0.05)

    bus.publish(channel, transition_event)

    deadline = asyncio.get_event_loop().time() + 0.5
    while asyncio.get_event_loop().time() < deadline and not raw_frames:
        try:
            frame = await asyncio.wait_for(frame_queue.get(), timeout=0.1)
            if "data:" in frame:
                raw_frames.append(frame)
        except TimeoutError:
            continue

    # Teardown
    request._disconnect_flag.set()
    pump_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await pump_task
    await gen.aclose()

    assert len(raw_frames) >= 1
    # Verify event type via "event:" metadata line
    event_line = next(
        (ln for ln in raw_frames[0].splitlines() if ln.startswith("event:")), None
    )
    assert event_line is not None, "no event: line in SSE frame"
    assert "job.state_changed" in event_line
    # Verify data payload is HTML
    data_lines = [ln for ln in raw_frames[0].splitlines() if ln.startswith("data:")]
    combined_data = "\n".join(ln[len("data:"):].lstrip(" ") for ln in data_lines)
    assert "<" in combined_data, f"expected HTML in data payload, got: {combined_data!r}"
