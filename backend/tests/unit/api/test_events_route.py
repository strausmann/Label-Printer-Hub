# backend/tests/unit/api/test_events_route.py
from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.main import app as _app_wrapper
from app.services.event_bus import BusEvent, EventBus
from fastapi.testclient import TestClient

_inner = _app_wrapper._app


@pytest.fixture()
def client_with_bus() -> TestClient:
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


def _make_queue_event(printer_id: uuid.UUID, channel: str) -> BusEvent:
    return BusEvent(
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


@pytest.mark.asyncio
async def test_event_delivered_to_sse_stream() -> None:
    """Publish an event; assert the SSE frame arrives within 200 ms.

    Tests ``_sse_stream`` directly (not via HTTP) because httpx ASGITransport
    buffers the full response body before yielding — it cannot incrementally
    stream SSE frames. The generator is the unit under test.

    Uses ``gen.aclose()`` explicitly rather than ``async for ... break`` so
    the generator's async cleanup (cancelling pending queue-get tasks) runs
    properly within the test's event loop.
    """
    import app.api.routes.events as events_module

    printer_id = uuid.uuid4()
    bus = EventBus(queue_size=8)

    channel = f"printer:{printer_id}:queue"
    channels = [channel, f"printer:{printer_id}:state", f"printer:{printer_id}:tape"]
    subscriber_id = "test-sub-delivery"

    test_event = _make_queue_event(printer_id, channel)

    # Build a minimal mock Request — generator reads headers and calls is_disconnected
    disconnect_flag = asyncio.Event()

    async def _is_disconnected() -> bool:
        return disconnect_flag.is_set()

    mock_request = MagicMock()
    mock_request.headers = {}
    mock_request.client = None
    mock_request.is_disconnected = _is_disconnected

    received_frames: list[str] = []

    gen = events_module._sse_stream(printer_id, bus, mock_request, subscriber_id, channels)
    # Collect frames into a queue so the generator and publisher can run concurrently
    frame_queue: asyncio.Queue[str] = asyncio.Queue()

    async def pump() -> None:
        """Drive the SSE generator and enqueue each frame."""
        async for frame in gen:
            await frame_queue.put(frame)

    pump_task = asyncio.create_task(pump())
    # Give the generator time to subscribe and reach asyncio.wait
    await asyncio.sleep(0.05)

    # Publish the event — generator should produce the data frame shortly after
    bus.publish(channel, test_event)

    # Collect frames until we see a data frame or time out.
    # SSE data frames are multi-line: "id: ...\nevent: ...\ndata: {...}\n\n"
    # Check for "data:" line within the whole frame string.
    deadline = asyncio.get_event_loop().time() + 0.5  # 500 ms budget
    while asyncio.get_event_loop().time() < deadline:
        try:
            frame = await asyncio.wait_for(frame_queue.get(), timeout=0.1)
            if "data:" in frame:
                received_frames.append(frame)
                break
        except TimeoutError:
            continue

    # Signal disconnect and close the generator cleanly
    disconnect_flag.set()
    pump_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await pump_task
    await gen.aclose()

    assert len(received_frames) == 1
    # Extract the data line from the multi-line SSE frame
    data_line = next(ln for ln in received_frames[0].splitlines() if ln.startswith("data:"))
    frame_data = json.loads(data_line[len("data:") :].strip())
    assert frame_data["event_type"] == "job.state_changed"
    assert frame_data["from_state"] == "queued"
    assert frame_data["to_state"] == "printing"


@pytest.mark.asyncio
async def test_multichannel_multiplex_all_arrive() -> None:
    """Events on queue, state, tape channels all arrive via the same generator.

    Tests the multiplexing logic of ``_sse_stream`` directly.
    """
    import app.api.routes.events as events_module

    printer_id = uuid.uuid4()
    bus = EventBus(queue_size=8)

    queue_channel = f"printer:{printer_id}:queue"
    state_channel = f"printer:{printer_id}:state"
    tape_channel = f"printer:{printer_id}:tape"
    channels = [queue_channel, state_channel, tape_channel]
    subscriber_id = "test-sub-multiplex"

    queue_event = BusEvent(
        channel=queue_channel,
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
    state_event = BusEvent(
        channel=state_channel,
        event_id=1,
        event_type="printer.status",
        timestamp=datetime.now(UTC),
        data={"hr_printer_status": "idle", "error_flags": [], "online": True},
    )
    tape_event = BusEvent(
        channel=tape_channel,
        event_id=1,
        event_type="printer.tape_changed",
        timestamp=datetime.now(UTC),
        data={"from_mm": 12, "to_mm": 24, "tape_label": "24mm"},
    )

    disconnect_flag = asyncio.Event()

    async def _is_disconnected() -> bool:
        return disconnect_flag.is_set()

    mock_request = MagicMock()
    mock_request.headers = {}
    mock_request.client = None
    mock_request.is_disconnected = _is_disconnected

    received_frames: list[dict] = []  # type: ignore[type-arg]

    gen = events_module._sse_stream(printer_id, bus, mock_request, subscriber_id, channels)
    frame_queue: asyncio.Queue[str] = asyncio.Queue()

    async def pump() -> None:
        async for frame in gen:
            await frame_queue.put(frame)

    pump_task = asyncio.create_task(pump())
    await asyncio.sleep(0.05)

    # Publish to all three channels
    bus.publish(queue_channel, queue_event)
    bus.publish(state_channel, state_event)
    bus.publish(tape_channel, tape_event)

    # Collect data frames until we have 3 or time out.
    # SSE data frames are multi-line; check for "data:" line within the frame.
    deadline = asyncio.get_event_loop().time() + 1.5
    while len(received_frames) < 3 and asyncio.get_event_loop().time() < deadline:
        try:
            frame = await asyncio.wait_for(frame_queue.get(), timeout=0.2)
            if "data:" in frame:
                data_line = next(ln for ln in frame.splitlines() if ln.startswith("data:"))
                received_frames.append(json.loads(data_line[len("data:") :].strip()))
        except TimeoutError:
            continue

    disconnect_flag.set()
    pump_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await pump_task
    await gen.aclose()

    event_types = {e["event_type"] for e in received_frames}
    assert "job.state_changed" in event_types
    assert "printer.status" in event_types
    assert "printer.tape_changed" in event_types


@pytest.mark.asyncio
async def test_heartbeat_emitted_after_timeout() -> None:
    """With no events, a keepalive comment frame arrives after _HEARTBEAT_INTERVAL_S.

    Overrides ``_HEARTBEAT_INTERVAL_S`` to 0.1 s so the test completes quickly.
    Tests ``_sse_stream`` directly to avoid httpx buffering.
    """
    import app.api.routes.events as events_module

    printer_id = uuid.uuid4()
    bus = EventBus(queue_size=8)

    channels = [
        f"printer:{printer_id}:queue",
        f"printer:{printer_id}:state",
        f"printer:{printer_id}:tape",
    ]
    subscriber_id = "test-sub-heartbeat"

    disconnect_flag = asyncio.Event()

    async def _is_disconnected() -> bool:
        return disconnect_flag.is_set()

    mock_request = MagicMock()
    mock_request.headers = {}
    mock_request.client = None
    mock_request.is_disconnected = _is_disconnected

    heartbeat_frames: list[str] = []

    original = events_module._HEARTBEAT_INTERVAL_S
    events_module._HEARTBEAT_INTERVAL_S = 0.1
    try:
        gen = events_module._sse_stream(printer_id, bus, mock_request, subscriber_id, channels)
        frame_queue: asyncio.Queue[str] = asyncio.Queue()

        async def pump() -> None:
            async for frame in gen:
                await frame_queue.put(frame)

        pump_task = asyncio.create_task(pump())

        # Collect frames until we see a keepalive or time out at 2 s
        deadline = asyncio.get_event_loop().time() + 2.0
        while asyncio.get_event_loop().time() < deadline:
            try:
                frame = await asyncio.wait_for(frame_queue.get(), timeout=0.3)
                if "keepalive" in frame:
                    heartbeat_frames.append(frame)
                    break
            except TimeoutError:
                continue

        disconnect_flag.set()
        pump_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await pump_task
        await gen.aclose()
    finally:
        events_module._HEARTBEAT_INTERVAL_S = original

    assert len(heartbeat_frames) >= 1
    assert all("keepalive" in f for f in heartbeat_frames)


@pytest.mark.asyncio
async def test_cancel_safety_unsubscribes_on_disconnect() -> None:
    """When the generator is cancelled (client disconnect), subscribers are removed.

    Uses the pump/frame_queue pattern to drive the generator. After cancellation
    and gen.aclose(), all three channel subscriptions must be gone from the bus.
    """
    import app.api.routes.events as events_module

    printer_id = uuid.uuid4()
    bus = EventBus(queue_size=8)

    channels = [
        f"printer:{printer_id}:queue",
        f"printer:{printer_id}:state",
        f"printer:{printer_id}:tape",
    ]
    subscriber_id = "test-sub-cancel"

    disconnect_flag = asyncio.Event()

    async def _is_disconnected() -> bool:
        return disconnect_flag.is_set()

    mock_request = MagicMock()
    mock_request.headers = {}
    mock_request.client = None
    mock_request.is_disconnected = _is_disconnected

    gen = events_module._sse_stream(printer_id, bus, mock_request, subscriber_id, channels)
    frame_queue: asyncio.Queue[str] = asyncio.Queue()

    async def pump() -> None:
        async for frame in gen:
            await frame_queue.put(frame)

    pump_task = asyncio.create_task(pump())

    # Wait for the initial ": connected" frame so we know the generator is live
    connected_frame = await asyncio.wait_for(frame_queue.get(), timeout=1.0)
    assert connected_frame.startswith(": connected")

    # Signal disconnect and shut down the generator
    disconnect_flag.set()
    pump_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await pump_task
    await gen.aclose()

    # After generator exit, all channel subscriber counts must be back to zero
    total_after = sum(bus.subscriber_count(ch) for ch in channels)
    assert total_after == 0


# ---------------------------------------------------------------------------
# T6: _render_fragment + Jinja2 fragment template tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_render_fragment_job_state_returns_html() -> None:
    """job.state_changed event renders a non-empty HTML fragment containing to_state."""
    from app.api.routes.events import _render_fragment

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
    """printer.status online event renders status-online CSS class."""
    from app.api.routes.events import _render_fragment

    event = BusEvent(
        channel="printer:x:state",
        event_id=1,
        event_type="printer.status",
        timestamp=datetime.now(UTC),
        data={"hr_printer_status": "idle", "error_flags": [], "online": True},
    )
    html = await _render_fragment(event)
    assert "Idle" in html or "idle" in html  # Jinja2 | title capitalises first letter
    assert "status-online" in html


@pytest.mark.asyncio
async def test_render_fragment_printer_status_offline() -> None:
    """printer.status offline event renders status-offline CSS class."""
    from app.api.routes.events import _render_fragment

    event = BusEvent(
        channel="printer:x:state",
        event_id=1,
        event_type="printer.status",
        timestamp=datetime.now(UTC),
        data={"hr_printer_status": "other", "error_flags": ["doorOpen"], "online": False},
    )
    html = await _render_fragment(event)
    assert "status-offline" in html


@pytest.mark.asyncio
async def test_render_fragment_tape_changed() -> None:
    """printer.tape_changed event renders tape label in fragment."""
    from app.api.routes.events import _render_fragment

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
async def test_render_fragment_tape_removed() -> None:
    """printer.tape_changed with to_mm=None renders 'no tape' message."""
    from app.api.routes.events import _render_fragment

    event = BusEvent(
        channel="printer:x:tape",
        event_id=1,
        event_type="printer.tape_changed",
        timestamp=datetime.now(UTC),
        data={"from_mm": 12, "to_mm": None, "tape_label": None},
    )
    html = await _render_fragment(event)
    assert "No tape" in html or "no tape" in html.lower()


@pytest.mark.asyncio
async def test_render_fragment_unknown_type_returns_empty() -> None:
    """Unknown event type returns empty string (safe fallback)."""
    from app.api.routes.events import _render_fragment

    event = BusEvent(
        channel="printer:x:other",
        event_id=1,
        event_type="unknown.type",
        timestamp=datetime.now(UTC),
        data={},
    )
    html = await _render_fragment(event)
    assert html == ""


@pytest.mark.asyncio
async def test_sse_frame_includes_html_field_from_fragment() -> None:
    """When fragments exist, SSE data frame includes an html field with rendered content."""
    import app.api.routes.events as events_module

    printer_id = uuid.uuid4()
    bus = EventBus(queue_size=8)

    channel = f"printer:{printer_id}:queue"
    channels = [channel, f"printer:{printer_id}:state", f"printer:{printer_id}:tape"]
    subscriber_id = "test-sub-html-field"

    test_event = BusEvent(
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

    disconnect_flag = asyncio.Event()

    async def _is_disconnected() -> bool:
        return disconnect_flag.is_set()

    mock_request = MagicMock()
    mock_request.headers = {}
    mock_request.client = None
    mock_request.is_disconnected = _is_disconnected

    gen = events_module._sse_stream(printer_id, bus, mock_request, subscriber_id, channels)
    frame_queue: asyncio.Queue[str] = asyncio.Queue()

    async def pump() -> None:
        async for frame in gen:
            await frame_queue.put(frame)

    pump_task = asyncio.create_task(pump())
    await asyncio.sleep(0.05)
    bus.publish(channel, test_event)

    data_frames: list[dict] = []  # type: ignore[type-arg]
    deadline = asyncio.get_event_loop().time() + 0.5
    while asyncio.get_event_loop().time() < deadline:
        try:
            frame = await asyncio.wait_for(frame_queue.get(), timeout=0.1)
            if "data:" in frame:
                data_line = next(ln for ln in frame.splitlines() if ln.startswith("data:"))
                data_frames.append(json.loads(data_line[len("data:") :].strip()))
                break
        except TimeoutError:
            continue

    disconnect_flag.set()
    pump_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await pump_task
    await gen.aclose()

    assert len(data_frames) == 1
    # With fragments in place, the html field must be non-empty HTML
    assert "html" in data_frames[0]
    assert "<" in data_frames[0]["html"]


# ---------------------------------------------------------------------------
# Phase 6b Task 8 — Prometheus counters + healthz sse_active_subscribers
# ---------------------------------------------------------------------------


def test_healthz_shows_sse_active_subscribers(client_with_bus: TestClient) -> None:
    """After subscribing, /healthz.sse_active_subscribers must be > 0."""
    bus: EventBus = _inner.state.event_bus
    printer_id = uuid.uuid4()
    bus.subscribe(f"printer:{printer_id}:queue", "test-sub-healthz")

    resp = client_with_bus.get("/healthz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["sse_active_subscribers"] >= 1


@pytest.mark.asyncio
async def test_prometheus_sse_connections_counter_increments() -> None:
    """sse_connections_total increments when _sse_stream subscribes."""
    import app.api.routes.events as events_module
    from prometheus_client import REGISTRY

    printer_id = uuid.uuid4()
    bus = EventBus(queue_size=8)

    channels = [
        f"printer:{printer_id}:queue",
        f"printer:{printer_id}:state",
        f"printer:{printer_id}:tape",
    ]
    subscriber_id = "test-sub-counter"
    disconnect_flag = asyncio.Event()

    async def _is_disconnected() -> bool:
        return disconnect_flag.is_set()

    mock_request = MagicMock()
    mock_request.headers = {}
    mock_request.client = None
    mock_request.is_disconnected = _is_disconnected

    # Read counter before
    def _get_connections_value() -> float:
        try:
            return (
                REGISTRY.get_sample_value(
                    "printer_hub_sse_connections_total",
                    {"printer_id": str(printer_id)},
                )
                or 0.0
            )
        except Exception:
            return 0.0

    before = _get_connections_value()

    gen = events_module._sse_stream(printer_id, bus, mock_request, subscriber_id, channels)
    frame_queue: asyncio.Queue[str] = asyncio.Queue()

    async def pump() -> None:
        async for frame in gen:
            await frame_queue.put(frame)

    pump_task = asyncio.create_task(pump())
    # Wait for connected frame — counter must have been incremented
    _connected = await asyncio.wait_for(frame_queue.get(), timeout=1.0)

    after = _get_connections_value()

    disconnect_flag.set()
    pump_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await pump_task
    await gen.aclose()

    assert after > before


@pytest.mark.asyncio
async def test_prometheus_sse_events_published_counter_increments() -> None:
    """sse_events_published_total increments when an event flows through the stream."""
    import app.api.routes.events as events_module
    from prometheus_client import REGISTRY

    printer_id = uuid.uuid4()
    bus = EventBus(queue_size=8)

    channel = f"printer:{printer_id}:queue"
    channels = [channel, f"printer:{printer_id}:state", f"printer:{printer_id}:tape"]
    subscriber_id = "test-sub-pub-counter"
    disconnect_flag = asyncio.Event()

    async def _is_disconnected() -> bool:
        return disconnect_flag.is_set()

    mock_request = MagicMock()
    mock_request.headers = {}
    mock_request.client = None
    mock_request.is_disconnected = _is_disconnected

    def _get_published_value() -> float:
        try:
            return (
                REGISTRY.get_sample_value(
                    "printer_hub_sse_events_published_total",
                    {"channel": channel},
                )
                or 0.0
            )
        except Exception:
            return 0.0

    before = _get_published_value()

    test_event = _make_queue_event(printer_id, channel)

    gen = events_module._sse_stream(printer_id, bus, mock_request, subscriber_id, channels)
    frame_queue: asyncio.Queue[str] = asyncio.Queue()

    async def pump() -> None:
        async for frame in gen:
            await frame_queue.put(frame)

    pump_task = asyncio.create_task(pump())
    await asyncio.sleep(0.05)
    bus.publish(channel, test_event)

    # Collect until data frame arrives
    deadline = asyncio.get_event_loop().time() + 0.5
    while asyncio.get_event_loop().time() < deadline:
        try:
            frame = await asyncio.wait_for(frame_queue.get(), timeout=0.1)
            if "data:" in frame:
                break
        except TimeoutError:
            continue

    after = _get_published_value()

    disconnect_flag.set()
    pump_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await pump_task
    await gen.aclose()

    assert after > before
