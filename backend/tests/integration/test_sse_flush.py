"""SSE flush-timing tests — verify bytes arrive promptly, not buffered.

Marked @pytest.mark.slow so they are excluded from the fast CI run:
    pytest -m "not slow" tests/
They are included in the nightly / extended integration run:
    pytest -m slow tests/integration/test_sse_flush.py

NOTE on test strategy (why we call _sse_stream directly):
    httpx ASGITransport buffers the complete response body before yielding
    lines, so it cannot be used for incremental SSE timing tests. We invoke
    the ``_sse_stream`` generator directly — same pattern as the unit tests —
    and measure wall-clock time from ``bus.publish`` to when the generator
    yields its first data frame.

Why generous thresholds (200 ms, 500 ms)?
    The architectural goal is first-byte latency < 50 ms. Tests must not be
    flaky in CI (disk-encrypted VMs, resource-constrained containers). 200 ms
    is ~4x the real-world target — enough headroom to tolerate scheduler jitter
    without masking genuine buffering bugs.

    Heartbeat threshold: _HEARTBEAT_INTERVAL_S + 500 ms (plan requirement).
    With sse_heartbeat_s=0.1 the effective threshold is 0.6 s.

    Idle-timeout threshold: with sse_idle_timeout_s=0.5 we expect the server
    to close the stream within 3 s total (the generator checks the idle
    condition after every heartbeat cycle of 0.05 s).
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from app.main import app as _app_wrapper
from app.services.event_bus import BusEvent, EventBus

_inner = _app_wrapper._app  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_request() -> MagicMock:
    """Minimal mock Request with controllable disconnect signal."""
    disconnect_flag = asyncio.Event()

    async def _is_disconnected() -> bool:
        return disconnect_flag.is_set()

    req = MagicMock()
    req.headers = {}
    req.client = None
    req.is_disconnected = _is_disconnected
    req._disconnect_flag = disconnect_flag
    return req


# ---------------------------------------------------------------------------
# T9.3 — First byte within 200 ms of publish
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.asyncio
async def test_first_sse_byte_arrives_within_200ms() -> None:
    """The first SSE data frame must arrive within 200 ms of EventBus.publish.

    Measures wall-clock latency from ``bus.publish(...)`` to when the generator
    yields a frame containing ``data:``. 200 ms is 4x the target 50 ms
    architectural budget — enough for CI scheduler jitter.
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
    subscriber_id = "flush-test-latency"

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

    first_frame_time: list[float] = []
    publish_time: list[float] = []
    request = _mock_request()
    gen = events_mod._sse_stream(printer_id, bus, request, subscriber_id, channels)

    frame_queue: asyncio.Queue[str] = asyncio.Queue()

    async def pump() -> None:
        async for frame in gen:
            await frame_queue.put(frame)

    pump_task = asyncio.create_task(pump())
    await asyncio.sleep(0.05)  # let generator subscribe

    publish_time.append(time.monotonic())
    bus.publish(channel, event)

    deadline = asyncio.get_event_loop().time() + 0.5
    while asyncio.get_event_loop().time() < deadline:
        try:
            frame = await asyncio.wait_for(frame_queue.get(), timeout=0.1)
            if "data:" in frame:
                first_frame_time.append(time.monotonic())
                break
        except TimeoutError:
            continue

    request._disconnect_flag.set()
    pump_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await pump_task
    await gen.aclose()

    assert first_frame_time, "no data frame received within 500 ms"
    latency = first_frame_time[0] - publish_time[0]
    assert latency < 0.2, f"SSE latency {latency:.3f}s exceeds 200 ms threshold"


# ---------------------------------------------------------------------------
# T9.4 — Heartbeat arrives after silence (heartbeat_s=0.1, threshold=0.6 s)
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.asyncio
async def test_heartbeat_arrives_after_silence() -> None:
    """With heartbeat interval 0.1 s, a keepalive comment must arrive within 0.6 s.

    Overrides the module-level ``_HEARTBEAT_INTERVAL_S`` to 0.1 s so the test
    does not wait 30 s. Threshold = 0.1 + 0.5 = 0.6 s, per the plan.
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
    subscriber_id = "flush-test-heartbeat"
    request = _mock_request()

    heartbeat_override = 0.1  # seconds

    original = events_mod._HEARTBEAT_INTERVAL_S
    events_mod._HEARTBEAT_INTERVAL_S = heartbeat_override
    try:
        gen = events_mod._sse_stream(printer_id, bus, request, subscriber_id, channels)

        frame_queue: asyncio.Queue[str] = asyncio.Queue()

        async def pump() -> None:
            async for frame in gen:
                await frame_queue.put(frame)

        pump_task = asyncio.create_task(pump())
        connect_time = time.monotonic()

        keepalive_time: list[float] = []
        # Wait up to 1.0 s for the keepalive frame
        deadline = asyncio.get_event_loop().time() + 1.0
        while asyncio.get_event_loop().time() < deadline:
            try:
                frame = await asyncio.wait_for(frame_queue.get(), timeout=0.2)
                # ": connected" is the first comment (immediate) — skip it
                if frame.strip() == ": connected":
                    continue
                if "keepalive" in frame:
                    keepalive_time.append(time.monotonic())
                    break
            except TimeoutError:
                continue

        request._disconnect_flag.set()
        pump_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await pump_task
        await gen.aclose()
    finally:
        events_mod._HEARTBEAT_INTERVAL_S = original

    assert keepalive_time, "no keepalive frame received within 1 s"
    elapsed = keepalive_time[0] - connect_time
    threshold = heartbeat_override + 0.5
    assert elapsed < threshold, f"heartbeat took {elapsed:.3f}s; expected < {threshold:.3f}s"


# ---------------------------------------------------------------------------
# T9.5 — Idle-timeout: server closes stream after idle
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.asyncio
async def test_idle_timeout_closes_stream() -> None:
    """With idle_timeout_s=0.5 and heartbeat_s=0.05, stream closes after idle.

    The generator checks idle condition after each heartbeat timeout. With
    heartbeat=0.05 s and idle=0.5 s the server will emit ~10 keepalive frames
    before closing the connection. The pump task finishes when the generator
    exits (StopAsyncIteration), which proves the server closed the stream.
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
    subscriber_id = "flush-test-idle"
    request = _mock_request()

    orig_heartbeat = events_mod._HEARTBEAT_INTERVAL_S
    orig_idle = events_mod._IDLE_TIMEOUT_S
    events_mod._HEARTBEAT_INTERVAL_S = 0.05
    events_mod._IDLE_TIMEOUT_S = 0.5
    try:
        gen = events_mod._sse_stream(printer_id, bus, request, subscriber_id, channels)

        pump_done = asyncio.Event()

        async def pump() -> None:
            async for _frame in gen:
                pass  # drain all frames until generator exits
            pump_done.set()

        pump_task = asyncio.create_task(pump())
        # Give the server up to 3 s to close the idle stream
        await asyncio.wait_for(pump_done.wait(), timeout=3.0)
    finally:
        events_mod._HEARTBEAT_INTERVAL_S = orig_heartbeat
        events_mod._IDLE_TIMEOUT_S = orig_idle
        # Cancel any lingering pump task
        pump_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await pump_task
        await gen.aclose()

    assert pump_done.is_set(), "server did not close the idle stream within 3 s"
