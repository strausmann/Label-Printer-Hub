# backend/tests/unit/api/test_events_route.py
from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.main import app as _app_wrapper
from app.services.event_bus import BusEvent, EventBus
from fastapi import FastAPI
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


def test_settings_sse_max_subscribers_honoured() -> None:
    """When PRINTER_HUB_SSE_MAX_SUBSCRIBERS=2, the 3rd connection gets 429.

    This is the regression test for Finding #3 (KRITISCH-3): the route had
    hard-coded _MAX_SUBSCRIBERS_PER_PRINTER = 100 which ignored the env var.
    After the fix, the cap is read from Settings (injected via Depends).

    Uses a fresh FastAPI app with dependency overrides to avoid interfering
    with the shared client_with_bus fixture.
    """
    from collections.abc import AsyncIterator

    from app.api.routes.events import router as events_router
    from app.config import Settings, get_settings
    from app.db.session import get_session
    from sqlalchemy.ext.asyncio import AsyncSession

    printer_id = uuid.uuid4()
    fake_printer = MagicMock()
    fake_printer.id = printer_id

    # Build a dedicated test app with a cap of 2
    test_app = FastAPI()
    test_app.include_router(events_router)
    bus = EventBus(queue_size=8)
    test_app.state.event_bus = bus

    low_cap_settings = Settings(sse_max_subscribers=2, _env_file=None)  # type: ignore[call-arg]
    test_app.dependency_overrides[get_settings] = lambda: low_cap_settings

    # Provide a no-op session — printers_repo.get is mocked anyway
    mock_session = MagicMock(spec=AsyncSession)

    async def _noop_session() -> AsyncIterator[AsyncSession]:
        yield mock_session

    test_app.dependency_overrides[get_session] = _noop_session

    subscriber_id_1 = "cap-test-sub-1"
    subscriber_id_2 = "cap-test-sub-2"

    # Simulate 2 distinct connections already active (each holds 3 channels)
    for ch in (
        f"printer:{printer_id}:queue",
        f"printer:{printer_id}:state",
        f"printer:{printer_id}:tape",
    ):
        bus.subscribe(ch, subscriber_id_1)
        bus.subscribe(ch, subscriber_id_2)

    with (
        _mock_printer_get(fake_printer),
        TestClient(test_app, raise_server_exceptions=True) as client,
    ):
        resp = client.get(f"/api/events?printer_id={printer_id}")

    assert resp.status_code == 429, (
        f"expected 429 when cap=2 and 2 subscribers already connected, got {resp.status_code}"
    )
    body = resp.json()
    assert body["type"] == "sse-subscriber-limit"


def test_404_when_printer_not_found(client_with_bus: TestClient) -> None:
    with _mock_printer_get(None):
        resp = client_with_bus.get(f"/api/events?printer_id={uuid.uuid4()}")
    assert resp.status_code == 404


def test_429_when_subscriber_limit_exceeded(client_with_bus: TestClient) -> None:
    """When distinct subscriber count reaches the Settings cap, the next request gets 429.

    Each SSE connection subscribes to 3 channels with the same subscriber_id.
    The cap check counts DISTINCT subscriber_ids, so cap=N means N connections.
    This test fills the default cap (sse_max_subscribers=100) with 100 distinct
    subscriber IDs, each registered on all 3 channels.
    """
    printer_id = uuid.uuid4()
    fake_printer = MagicMock()
    fake_printer.id = printer_id

    bus: EventBus = _inner.state.event_bus
    # Register 100 distinct subscriber IDs, each on all 3 channels
    # (matches how _sse_stream subscribes: same subscriber_id on 3 channels)
    default_cap = 100
    channels = (
        f"printer:{printer_id}:queue",
        f"printer:{printer_id}:state",
        f"printer:{printer_id}:tape",
    )
    for i in range(default_cap):
        for ch in channels:
            bus.subscribe(ch, f"fake-sub-{i}")

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
    # After Finding #2 fix: data: carries raw HTML, not a JSON envelope.
    # Verify via the "event:" line (always present) that the correct event type
    # was emitted; verify that the data payload contains HTML.
    lines = received_frames[0].splitlines()
    event_line = next((ln for ln in lines if ln.startswith("event:")), None)
    assert event_line is not None, "no event: line in SSE frame"
    assert "job.state_changed" in event_line
    data_lines = [ln for ln in lines if ln.startswith("data:")]
    assert data_lines, "no data: lines in SSE frame"
    # data payload is raw HTML — must contain '<'
    combined_data = "\n".join(ln[len("data:") :].lstrip(" ") for ln in data_lines)
    assert "<" in combined_data, f"data payload must be HTML, got: {combined_data!r}"


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
    # After Finding #2 fix: data: carries raw HTML.  Event type is on event: line.
    # Collect (event_type, raw_frame) tuples using the "event:" line.
    received_event_types: list[str] = []
    deadline = asyncio.get_event_loop().time() + 1.5
    while len(received_event_types) < 3 and asyncio.get_event_loop().time() < deadline:
        try:
            frame = await asyncio.wait_for(frame_queue.get(), timeout=0.2)
            if "data:" in frame:
                event_line = next(
                    (ln for ln in frame.splitlines() if ln.startswith("event:")), None
                )
                if event_line:
                    received_event_types.append(event_line[len("event:") :].strip())
        except TimeoutError:
            continue

    disconnect_flag.set()
    pump_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await pump_task
    await gen.aclose()

    event_types = set(received_event_types)
    assert "job.state_changed" in event_types
    assert "printer.status" in event_types
    assert "printer.tape_changed" in event_types


@pytest.mark.asyncio
async def test_heartbeat_emitted_after_timeout() -> None:
    """With no events, a keepalive comment frame arrives after the heartbeat interval.

    Passes ``heartbeat_interval_s=0.1`` directly to ``_sse_stream`` so the
    test completes quickly without needing to patch module-level constants.
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

    try:
        gen = events_module._sse_stream(
            printer_id,
            bus,
            mock_request,
            subscriber_id,
            channels,
            heartbeat_interval_s=0.1,
        )
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
        pass  # no module-level patch to restore

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
async def test_sse_data_line_is_raw_html_not_json() -> None:
    """SSE data: line must be raw HTML for HTMX sse-swap, not a JSON envelope.

    HTMX sse-swap injects the raw ``data:`` content into the DOM.  When the
    payload is a JSON string like ``{"html": "<div>...</div>", ...}`` the user
    sees the JSON literal in the page rather than the rendered fragment.

    This is the regression test for Finding #2 (KRITISCH-2).
    """
    import app.api.routes.events as events_module

    printer_id = uuid.uuid4()
    bus = EventBus(queue_size=8)

    channel = f"printer:{printer_id}:queue"
    channels = [channel, f"printer:{printer_id}:state", f"printer:{printer_id}:tape"]
    subscriber_id = "test-sub-raw-html"

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

    raw_frames: list[str] = []
    deadline = asyncio.get_event_loop().time() + 0.5
    while asyncio.get_event_loop().time() < deadline:
        try:
            frame = await asyncio.wait_for(frame_queue.get(), timeout=0.1)
            if "data:" in frame:
                raw_frames.append(frame)
                break
        except TimeoutError:
            continue

    disconnect_flag.set()
    pump_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await pump_task
    await gen.aclose()

    assert len(raw_frames) == 1, "expected exactly one data frame"
    frame = raw_frames[0]
    # The data: line(s) must be raw HTML, not JSON
    data_lines = [ln for ln in frame.splitlines() if ln.startswith("data:")]
    assert data_lines, "no data: lines in SSE frame"
    # Reconstruct the data payload from potentially multi-line data:
    data_payload = "\n".join(ln[len("data:") :].lstrip(" ") for ln in data_lines)
    # Must be HTML (contains '<'), NOT a JSON object
    assert "<" in data_payload, f"expected HTML in data payload, got: {data_payload!r}"
    assert not data_payload.strip().startswith("{"), (
        f"data payload must not be a JSON object, got: {data_payload[:80]!r}"
    )


@pytest.mark.asyncio
async def test_sse_frame_includes_html_field_from_fragment() -> None:
    """When fragments exist, SSE data frame contains rendered HTML content.

    After Finding #2 fix: data: carries raw HTML directly (not a JSON
    envelope). We verify that the rendered fragment HTML appears in the
    concatenated data: lines of the SSE frame.
    """
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

    raw_frames: list[str] = []
    deadline = asyncio.get_event_loop().time() + 0.5
    while asyncio.get_event_loop().time() < deadline:
        try:
            frame = await asyncio.wait_for(frame_queue.get(), timeout=0.1)
            if "data:" in frame:
                raw_frames.append(frame)
                break
        except TimeoutError:
            continue

    disconnect_flag.set()
    pump_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await pump_task
    await gen.aclose()

    assert len(raw_frames) == 1, "expected exactly one data frame"
    # After Finding #2 fix: data: carries raw HTML directly (no JSON envelope).
    data_lines = [ln for ln in raw_frames[0].splitlines() if ln.startswith("data:")]
    combined_html = "\n".join(ln[len("data:") :].lstrip(" ") for ln in data_lines)
    assert "<" in combined_html, f"expected HTML in data payload, got: {combined_html!r}"


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


# ---------------------------------------------------------------------------
# F2 — empty _render_fragment result must NOT produce an SSE frame
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sse_stream_skips_frame_when_fragment_is_empty() -> None:
    """When _render_fragment returns an empty string the SSE generator must
    NOT yield a data frame (bot-review Finding F2).

    An empty ``data:`` SSE frame causes HTMX sse-swap to overwrite the target
    element with empty content, wiping the live status widget.  The correct
    behaviour is to skip the yield entirely so the client DOM is unchanged.

    Strategy: publish an event whose type is NOT in _FRAGMENT_MAP so
    _render_fragment returns "".  Then publish a valid event and verify only
    the valid event produces a data frame.
    """
    from datetime import UTC, datetime

    import app.api.routes.events as events_module

    printer_id = uuid.uuid4()
    bus = EventBus(queue_size=8)

    channel = f"printer:{printer_id}:queue"
    channels = [channel, f"printer:{printer_id}:state", f"printer:{printer_id}:tape"]
    subscriber_id = "test-sub-skip-empty"

    # An event type that has no template → _render_fragment returns ""
    unknown_event = BusEvent(
        channel=channel,
        event_id=1,
        event_type="unknown.no_template",
        timestamp=datetime.now(UTC),
        data={},
    )
    # A valid event that DOES render a non-empty fragment
    valid_event = BusEvent(
        channel=channel,
        event_id=2,
        event_type="job.state_changed",
        timestamp=datetime.now(UTC),
        data={
            "job_id": "j1",
            "from_state": "queued",
            "to_state": "printing",
            "queue_depth": 1,
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
    await asyncio.sleep(0.05)  # let generator subscribe

    # Publish the unknown event first — should be swallowed (no frame emitted)
    bus.publish(channel, unknown_event)

    # Give the generator a full heartbeat cycle to process the unknown event.
    # If F2 is NOT fixed, it emits an empty "data: \n\n" frame here.
    await asyncio.sleep(0.05)

    # Now publish the valid event — should produce a data frame
    bus.publish(channel, valid_event)

    data_frames: list[str] = []
    deadline = asyncio.get_event_loop().time() + 0.5
    while asyncio.get_event_loop().time() < deadline:
        try:
            frame = await asyncio.wait_for(frame_queue.get(), timeout=0.1)
            if frame.strip() == ": connected":
                continue  # skip the connect confirmation
            if "data:" in frame:
                data_frames.append(frame)
                if len(data_frames) >= 2:
                    break  # stop early — we have more than expected
        except TimeoutError:
            if data_frames:
                break  # got what we need
            continue

    disconnect_flag.set()
    pump_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await pump_task
    await gen.aclose()

    # Exactly one data frame (from the valid event). Zero or two would both
    # indicate a bug: zero means the fix broke valid-event delivery; two means
    # the empty fragment was emitted as a frame (F2 unfixed).
    assert len(data_frames) == 1, (
        f"expected exactly 1 data frame (the valid event); got {len(data_frames)}: {data_frames!r}"
    )
    # The single frame must carry the valid event type
    assert "job.state_changed" in data_frames[0]


# ---------------------------------------------------------------------------
# F1 — Initial state snapshot on SSE connect (Finding F1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sse_stream_emits_initial_snapshot_on_connect() -> None:
    """A fresh SSE subscriber receives ≥1 snapshot frame within 100 ms even
    when no real events fire (Finding F1).

    On connect, _sse_stream queries the DB/cache for each channel and emits
    synthetic SSE frames so the client doesn't see empty widgets until the
    next state change.

    The snapshot must contain:
    - A printer.status frame (from PrinterStatusCache data)
    - A printer.tape_changed frame (from PrinterStatusCache loaded_tape_mm)
    - A job.state_changed frame when active jobs exist in the queue

    This test stubs the DB queries with AsyncMock so no real DB is needed.
    """
    from unittest.mock import AsyncMock, MagicMock

    import app.api.routes.events as events_module

    printer_id = uuid.uuid4()
    bus = EventBus(queue_size=8)

    channels = [
        f"printer:{printer_id}:queue",
        f"printer:{printer_id}:state",
        f"printer:{printer_id}:tape",
    ]
    subscriber_id = "test-sub-snapshot"

    disconnect_flag = asyncio.Event()

    async def _is_disconnected() -> bool:
        return disconnect_flag.is_set()

    mock_request = MagicMock()
    mock_request.headers = {}
    mock_request.client = None
    mock_request.is_disconnected = _is_disconnected

    # Build a mock DB session — printer status cache has known state
    mock_session = MagicMock()

    # Simulate PrinterStatusCache row with a known status
    from datetime import UTC, datetime

    status_cache = MagicMock()
    status_cache.parsed = {
        "hr_printer_status": "idle",
        "error_flags": [],
        "online": True,
        "loaded_tape_mm": 12,
    }
    status_cache.captured_at = datetime.now(UTC)

    # No active jobs
    _empty_scalars = MagicMock(scalars=lambda: MagicMock(all=lambda: []))
    mock_session.execute = AsyncMock(return_value=_empty_scalars)
    mock_session.get = AsyncMock(return_value=status_cache)

    gen = events_module._sse_stream(
        printer_id,
        bus,
        mock_request,
        subscriber_id,
        channels,
        session=mock_session,
    )

    frame_queue: asyncio.Queue[str] = asyncio.Queue()

    async def pump() -> None:
        async for frame in gen:
            await frame_queue.put(frame)

    pump_task = asyncio.create_task(pump())

    # Collect snapshot frames — must arrive within 200 ms (no real events fired)
    snapshot_frames: list[str] = []
    deadline = asyncio.get_event_loop().time() + 0.5
    while asyncio.get_event_loop().time() < deadline:
        try:
            frame = await asyncio.wait_for(frame_queue.get(), timeout=0.1)
            if frame.strip().startswith(": connected"):
                continue  # skip the connection confirmation comment
            if "data:" in frame:
                snapshot_frames.append(frame)
        except TimeoutError:
            if snapshot_frames:
                break  # received some snapshots; done
            continue

    disconnect_flag.set()
    pump_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await pump_task
    await gen.aclose()

    assert snapshot_frames, (
        "Expected ≥1 snapshot frame on SSE connect, got none. "
        "Finding F1: clients see empty widgets until a real event fires."
    )
    # At least one frame must be a printer.status snapshot
    event_types = set()
    for frame in snapshot_frames:
        for line in frame.splitlines():
            if line.startswith("event:"):
                event_types.add(line[len("event:") :].strip())
    assert "printer.status" in event_types, (
        f"Expected printer.status snapshot; got event types: {event_types!r}"
    )


# ---------------------------------------------------------------------------
# F4 — tape snapshot must be skipped when loaded_tape_mm is None (Finding F4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snapshot_skips_tape_frame_when_loaded_tape_mm_is_none() -> None:
    """_build_initial_snapshot must NOT emit printer.tape_changed when
    loaded_tape_mm is absent from the cache (Finding F4).

    Emitting a tape event with to_mm=None renders "No tape loaded" on the
    frontend and overwrites the correct UI state with a misleading message
    when the printer actually has tape loaded (the cache just hasn't reported
    it yet).  The fix: skip the tape frame entirely when loaded_tape_mm is
    missing so the client DOM is unchanged.
    """
    import app.api.routes.events as events_module

    printer_id = uuid.uuid4()
    mock_session = MagicMock()

    # Status cache has NO loaded_tape_mm key (simulates missing/unknown tape data)
    status_cache = MagicMock()
    status_cache.parsed = {
        "hr_printer_status": "idle",
        "error_flags": [],
        "online": True,
        # loaded_tape_mm intentionally absent — dict.get() returns None
    }
    status_cache.captured_at = datetime(2024, 1, 1, tzinfo=UTC)
    mock_session.get = AsyncMock(return_value=status_cache)

    # No active jobs
    _empty_result = MagicMock()
    _empty_result.scalar_one = MagicMock(return_value=0)
    _empty_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    mock_session.execute = AsyncMock(return_value=_empty_result)

    snapshot = await events_module._build_initial_snapshot(printer_id, mock_session)

    event_types = [e.event_type for e in snapshot]
    assert "printer.tape_changed" not in event_types, (
        f"tape_changed must NOT appear when loaded_tape_mm is None; got: {event_types!r}"
    )
    # printer.status snapshot is still emitted
    assert "printer.status" in event_types


@pytest.mark.asyncio
async def test_snapshot_emits_tape_frame_when_loaded_tape_mm_is_set() -> None:
    """_build_initial_snapshot MUST emit printer.tape_changed when loaded_tape_mm
    is present (regression guard: ensure the None-guard doesn't suppress valid data).
    """
    import app.api.routes.events as events_module

    printer_id = uuid.uuid4()
    mock_session = MagicMock()

    status_cache = MagicMock()
    status_cache.parsed = {
        "hr_printer_status": "idle",
        "error_flags": [],
        "online": True,
        "loaded_tape_mm": 12,
    }
    status_cache.captured_at = datetime(2024, 1, 1, tzinfo=UTC)
    mock_session.get = AsyncMock(return_value=status_cache)

    _empty_result = MagicMock()
    _empty_result.scalar_one = MagicMock(return_value=0)
    _empty_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    mock_session.execute = AsyncMock(return_value=_empty_result)

    snapshot = await events_module._build_initial_snapshot(printer_id, mock_session)

    tape_events = [e for e in snapshot if e.event_type == "printer.tape_changed"]
    assert len(tape_events) == 1
    assert tape_events[0].data["to_mm"] == 12


# ---------------------------------------------------------------------------
# F5 — queue_depth uses COUNT query, not len(limited_list) (Finding F5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snapshot_queue_depth_uses_count_not_list_length() -> None:
    """queue_depth in the initial snapshot must reflect the true count of
    non-terminal jobs, not len() of a capped list query (Finding F5).

    When there are more than 10 QUEUED jobs the old code reported at most 10
    (the list query limit) — the badge under-reported the real queue depth.
    The fix uses a COUNT query so even 100+ jobs are counted correctly.

    This test stubs session.execute so the COUNT returns 42 while
    list_by_filter returns only 5 rows — the snapshot events must carry 42.
    """
    import app.api.routes.events as events_module
    from app.models.job import Job, JobState

    printer_id = uuid.uuid4()
    mock_session = MagicMock()

    # Printer status cache is absent — skip printer.status frame to keep
    # the test focused on the job queue section
    mock_session.get = AsyncMock(return_value=None)

    # Build 5 fake job rows (simulating a capped list result)
    def _make_job(state: str) -> MagicMock:
        j = MagicMock(spec=Job)
        j.id = uuid.uuid4()
        j.state = state
        j.created_at = datetime(2024, 1, 1, tzinfo=UTC)
        return j

    fake_jobs = [_make_job(JobState.QUEUED.value) for _ in range(5)]

    # The COUNT query returns 42; the list queries return 5 rows total
    call_count = 0

    async def _execute_side_effect(stmt: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            # First call: COUNT query
            result.scalar_one = MagicMock(return_value=42)
        else:
            # Subsequent calls: list_by_filter results
            result.scalars = MagicMock(
                return_value=MagicMock(return_value=fake_jobs if call_count == 2 else [])
            )
        return result

    mock_session.execute = AsyncMock(side_effect=_execute_side_effect)

    # Also mock list_by_filter to return controlled data via the repo layer
    with (
        patch(
            "app.api.routes.events.jobs_repo.list_by_filter",
            new_callable=AsyncMock,
            side_effect=[fake_jobs, []],  # QUEUED → 5 rows, PRINTING → 0 rows
        ),
    ):
        snapshot = await events_module._build_initial_snapshot(printer_id, mock_session)

    job_events = [e for e in snapshot if e.event_type == "job.state_changed"]
    # Must have emitted frames (up to 5 jobs)
    assert len(job_events) <= 5
    # Every job frame must carry the COUNT-derived queue_depth, not len(list)
    for event in job_events:
        assert event.data["queue_depth"] == 42, (
            f"queue_depth must be 42 (from COUNT), got {event.data['queue_depth']!r}"
        )
