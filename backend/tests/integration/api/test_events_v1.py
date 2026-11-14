"""Global JSON event stream GET /api/v1/events (web UI foundation, Task 6).

All keys and tokens are obviously fake test values. The stream never ends on its
own, so these tests drive the ASGI app directly and read the body chunk by chunk.
Tests that publish job events with made-up job ids use admin keys: a plain key gets job
events of its own jobs only (#294, test_events_job_ownership.py).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import app.models  # noqa: F401
import pytest
import pytest_asyncio
from app.models.job import Job
from app.models.ui_session import UiSession
from app.services.event_bus import BusEvent, EventBus
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from tests.integration.api.test_auth_session import (
    _factory,
    _insert_key,
    _insert_printer,
    _set_env,
    _sign_in,
)

STREAM_PATH = "/api/v1/events"
FRAME_TIMEOUT_S = 3.0


@pytest_asyncio.fixture
async def hub_app():
    """The full app (lifespan runs on the first request) plus an HTTP client."""
    import app.db.engine as _engine_module
    import app.db.session as _session_module
    from app.integrations import (  # type: ignore[attr-defined]
        IntegrationRegistry,
        _discover_plugins,
    )
    from app.main import create_app

    _session_module.async_session = _engine_module.async_session
    if not IntegrationRegistry.names():
        _discover_plugins()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        assert (await client.get("/healthz")).status_code == 200  # starts the lifespan
        yield app, client


def _bus(app) -> EventBus:
    bus = app._app.state.event_bus
    assert isinstance(bus, EventBus)
    return bus


class Stream:
    """One open GET against the ASGI app, read chunk by chunk."""

    def __init__(self, app, path: str, headers: dict[str, str]) -> None:
        self.status: int | None = None
        self.headers: dict[str, str] = {}
        self._chunks: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._buffer = ""
        self._disconnect = asyncio.Event()
        self._started = asyncio.Event()
        path_only, _, query = path.partition("?")
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path_only,
            "raw_path": path_only.encode(),
            "query_string": query.encode(),
            "root_path": "",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": ("192.0.2.1", 50000),
            "server": ("t", 80),
        }
        sent_request = False

        async def receive() -> dict[str, Any]:
            nonlocal sent_request
            if not sent_request:
                sent_request = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await self._disconnect.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                self.status = message["status"]
                self.headers = {k.decode().lower(): v.decode() for k, v in message["headers"]}
                self._started.set()
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                if body:
                    await self._chunks.put(body)
                if not message.get("more_body", False):
                    await self._chunks.put(None)

        self._task = asyncio.create_task(app(scope, receive, send))

    async def wait_started(self) -> int:
        await asyncio.wait_for(self._started.wait(), FRAME_TIMEOUT_S)
        assert self.status is not None
        return self.status

    async def frame(self, timeout: float = FRAME_TIMEOUT_S) -> str | None:
        """Next complete frame (text before a blank line), ``None`` when the stream ended."""
        while "\n\n" not in self._buffer:
            chunk = await asyncio.wait_for(self._chunks.get(), timeout)
            if chunk is None:
                return None
            self._buffer += chunk.decode()
        frame, _, self._buffer = self._buffer.partition("\n\n")
        return frame

    async def body(self) -> str:
        """Everything up to the end of a finite response."""
        text = self._buffer
        while (chunk := await asyncio.wait_for(self._chunks.get(), FRAME_TIMEOUT_S)) is not None:
            text += chunk.decode()
        return text

    async def event(self, timeout: float = FRAME_TIMEOUT_S) -> dict[str, Any] | None:
        """Next data frame as ``{"event", "id", "payload"}``; comment frames are skipped."""
        while True:
            frame = await self.frame(timeout)
            if frame is None:
                return None
            if frame.startswith(":"):
                continue
            fields = dict(line.split(": ", 1) for line in frame.split("\n"))
            return {
                "event": fields["event"],
                "id": fields["id"],
                "payload": json.loads(fields["data"]),
            }

    async def event_of_type(self, event_type: str) -> dict[str, Any]:
        while True:
            ev = await self.event()
            assert ev is not None, f"stream ended before {event_type}"
            if ev["event"] == event_type:
                return ev

    async def close(self) -> None:
        self._disconnect.set()
        self._task.cancel()
        # Bounded: a stream that does not end must fail the test, not hang the run.
        await asyncio.wait({self._task}, timeout=2.0)


async def _open(app, headers: dict[str, str], query: str = "") -> Stream:
    return Stream(app, STREAM_PATH + (f"?{query}" if query else ""), headers)


def _job_event(
    bus: EventBus, printer_id: UUID, to_state: str = "printing", job_id: str = "job-1"
) -> None:
    channel = f"printer:{printer_id}:queue"
    bus.publish(
        channel,
        BusEvent(
            channel=channel,
            event_id=bus.next_event_id(channel),
            event_type="job.state_changed",
            timestamp=datetime.now(UTC),
            data={
                "job_id": job_id,
                "from_state": "queued",
                "to_state": to_state,
                "queue_depth": 0,
                "error_code": None,
            },
        ),
    )


async def _connected(stream: Stream) -> None:
    assert await stream.wait_started() == 200
    assert await stream.frame() == ": connected"
    # The version greeting follows at once; test_stream_greets_with_the_version checks its content.
    hello = await stream.frame()
    assert hello is not None and hello.startswith("event: hello\n")


def _key_header(key: str) -> dict[str, str]:
    return {"X-Label-Hub-Key": key}


def _printer_body(slug: str) -> dict[str, Any]:
    return {
        "name": f"Printer {slug}",
        "slug": slug,
        "model": "PT-P750W",
        "backend": "ptouch",
        "connection": {"host": "192.0.2.40", "port": 9100},
    }


@pytest.mark.asyncio
async def test_stream_requires_auth(hub_app):
    _, client = hub_app
    resp = await client.get(STREAM_PATH)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_stream_greets_with_the_version(hub_app):
    from app.main import HUB_VERSION

    app, _ = hub_app
    key, _ = await _insert_key(["admin"])
    stream = await _open(app, _key_header(key))
    try:
        assert await stream.wait_started() == 200
        assert await stream.frame() == ": connected"
        # EventSource cannot read response headers, so the greeting carries the version.
        assert await stream.frame() == f'event: hello\ndata: {{"version": "{HUB_VERSION}"}}'
    finally:
        await stream.close()


@pytest.mark.asyncio
async def test_stream_json_frames(hub_app):
    app, _ = hub_app
    key, _ = await _insert_key(["admin"])
    printer_id = await _insert_printer("alpha")
    stream = await _open(app, _key_header(key))
    try:
        await _connected(stream)
        assert stream.headers["content-type"].startswith("text/event-stream")
        _job_event(_bus(app), printer_id)
        ev = await stream.event_of_type("job.state_changed")
        payload = ev["payload"]
        assert payload["type"] == "job.state_changed"
        assert payload["channel"] == f"printer:{printer_id}:queue"
        assert payload["printer_id"] == str(printer_id)
        assert payload["data"]["to_state"] == "printing"
        assert datetime.fromisoformat(payload["ts"]).tzinfo is not None
        assert set(payload) == {"channel", "printer_id", "type", "ts", "data"}
        assert int(ev["id"]) >= 1
    finally:
        await stream.close()


@pytest.mark.asyncio
async def test_stream_without_printer_filter_gets_all_printers(hub_app):
    app, _ = hub_app
    key, _ = await _insert_key(["admin"])
    first = await _insert_printer("alpha")
    second = await _insert_printer("beta")
    stream = await _open(app, _key_header(key))
    try:
        await _connected(stream)
        _job_event(_bus(app), first)
        _job_event(_bus(app), second)
        seen = {
            (await stream.event_of_type("job.state_changed"))["payload"]["printer_id"]
            for _ in range(2)
        }
        assert seen == {str(first), str(second)}
    finally:
        await stream.close()


@pytest.mark.asyncio
async def test_printer_filter_limits_the_stream(hub_app):
    app, _ = hub_app
    key, _ = await _insert_key(["admin"])
    first = await _insert_printer("alpha")
    second = await _insert_printer("beta")
    stream = await _open(app, _key_header(key), f"printer_id={first}")
    try:
        await _connected(stream)
        _job_event(_bus(app), second)
        _job_event(_bus(app), first)
        ev = await stream.event_of_type("job.state_changed")
        assert ev["payload"]["printer_id"] == str(first)
    finally:
        await stream.close()


@pytest.mark.asyncio
async def test_unknown_printer_filter_is_404(hub_app):
    app, _ = hub_app
    key, _ = await _insert_key(["read"])
    stream = await _open(app, _key_header(key), "printer_id=00000000-0000-0000-0000-000000000000")
    try:
        assert await stream.wait_started() == 404
        body = json.loads(await stream.body())
        assert body["detail"]["error_code"] == "printer_not_found"
    finally:
        await stream.close()


@pytest.mark.asyncio
async def test_snapshot_is_emitted_per_printer(hub_app, monkeypatch):
    app, _ = hub_app
    # The row is inserted directly, so the runtime does not poll this printer; a polled one
    # keeps its reading in the snapshot (an unpolled or stale one is covered in
    # test_printer_status_staleness.py).
    monkeypatch.setattr(app._app.state.printer_runtime, "is_polled", lambda _id: True)
    key, _ = await _insert_key(["read"])
    printer_id = await _insert_printer("alpha")
    from app.repositories import printer_status_cache as status_cache_repo

    async with _factory()() as db:
        await status_cache_repo.upsert(
            db,
            printer_id,
            raw_block=b"\x00",
            parsed={"hr_printer_status": "idle", "online": True, "loaded_tape_mm": 12},
            captured_at=datetime.now(UTC),
        )
    stream = await _open(app, _key_header(key))
    try:
        await _connected(stream)
        status_ev = await stream.event_of_type("printer.status")
        tape_ev = await stream.event_of_type("printer.tape_changed")
        assert status_ev["id"] == "0"
        assert status_ev["payload"]["printer_id"] == str(printer_id)
        assert status_ev["payload"]["data"]["online"] is True
        assert tape_ev["payload"]["data"]["to_mm"] == 12
    finally:
        await stream.close()


@pytest.mark.asyncio
async def test_printer_created_emits_hub_event(hub_app):
    app, client = hub_app
    key, _ = await _insert_key(["admin"])
    stream = await _open(app, _key_header(key))
    try:
        await _connected(stream)
        resp = await client.post(
            "/api/v1/admin/printers", json=_printer_body("gamma"), headers=_key_header(key)
        )
        assert resp.status_code == 201, resp.text
        ev = await stream.event_of_type("hub.printers_changed")
        assert ev["payload"]["channel"] == "hub"
        assert ev["payload"]["printer_id"] is None
        assert ev["payload"]["data"] == {"printer_id": resp.json()["id"], "change": "created"}
    finally:
        await stream.close()


@pytest.mark.asyncio
async def test_printer_update_disable_enable_emit_hub_events(hub_app):
    app, client = hub_app
    key, _ = await _insert_key(["admin"])
    headers = _key_header(key)
    created = await client.post(
        "/api/v1/admin/printers", json=_printer_body("delta"), headers=headers
    )
    assert created.status_code == 201, created.text
    stream = await _open(app, headers)
    try:
        await _connected(stream)
        assert (
            await client.put(
                "/api/v1/admin/printers/delta", json={"name": "Renamed"}, headers=headers
            )
        ).status_code == 200
        assert (
            await client.post("/api/v1/admin/printers/delta/disable", headers=headers)
        ).status_code == 200
        assert (
            await client.post("/api/v1/admin/printers/delta/enable", headers=headers)
        ).status_code == 200
        changes = [
            (await stream.event_of_type("hub.printers_changed"))["payload"]["data"]["change"]
            for _ in range(3)
        ]
        assert changes == ["updated", "disabled", "enabled"]
    finally:
        await stream.close()


@pytest.mark.asyncio
async def test_new_printer_events_reach_an_open_stream(hub_app):
    app, client = hub_app
    key, _ = await _insert_key(["admin"])
    headers = _key_header(key)
    stream = await _open(app, headers)
    try:
        await _connected(stream)
        resp = await client.post(
            "/api/v1/admin/printers", json=_printer_body("eps"), headers=headers
        )
        assert resp.status_code == 201, resp.text
        await stream.event_of_type("hub.printers_changed")
        _job_event(_bus(app), UUID(resp.json()["id"]))
        ev = await stream.event_of_type("job.state_changed")
        assert ev["payload"]["printer_id"] == resp.json()["id"]
    finally:
        await stream.close()


@pytest.mark.asyncio
async def test_revoked_session_gets_auth_expired(hub_app, monkeypatch):
    app, client = hub_app
    _set_env(monkeypatch, sse_heartbeat_s="0.05")
    key, _ = await _insert_key(["print"])
    assert (await _sign_in(client, key)).status_code == 204
    cookie = f"lph_session={client.cookies.get('lph_session')}"
    stream = await _open(app, {"Cookie": cookie})
    try:
        await _connected(stream)
        async with _factory()() as db:
            await db.execute(update(UiSession).values(revoked_at=datetime.now(UTC)))
            await db.commit()
        ev = await stream.event_of_type("auth.expired")
        assert ev["payload"]["type"] == "auth.expired"
        assert await stream.frame() is None  # the stream is closed
    finally:
        await stream.close()


@pytest.mark.asyncio
async def test_disabled_key_gets_auth_expired(hub_app, monkeypatch):
    app, _ = hub_app
    _set_env(monkeypatch, sse_heartbeat_s="0.05")
    key, key_id = await _insert_key(["read"])
    stream = await _open(app, _key_header(key))
    try:
        await _connected(stream)
        from app.models.api_key import ApiKey

        async with _factory()() as db:
            await db.execute(update(ApiKey).where(ApiKey.id == key_id).values(enabled=False))  # type: ignore[arg-type]
            await db.commit()
        await stream.event_of_type("auth.expired")
        assert await stream.frame() is None
    finally:
        await stream.close()


@pytest.mark.asyncio
async def test_valid_session_gets_keepalive_not_auth_expired(hub_app, monkeypatch):
    app, _ = hub_app
    _set_env(monkeypatch, sse_heartbeat_s="0.05")
    key, _ = await _insert_key(["read"])
    stream = await _open(app, _key_header(key))
    try:
        await _connected(stream)
        assert await stream.frame() == ": keepalive"
        assert await stream.frame() == ": keepalive"
    finally:
        await stream.close()


@pytest.mark.asyncio
async def test_restricted_key_stream_excludes_other_printers(hub_app):
    app, _ = hub_app
    allowed = await _insert_printer("alpha")
    other = await _insert_printer("beta")
    # A plain key sees only its own jobs (#294), so the key owns a job on each printer and
    # only the printer list separates them. An admin key is never restricted (#283).
    key, key_id = await _insert_key(["print"], allowed_printer_ids=[str(allowed)])
    async with _factory()() as db:
        owned = {}
        for printer in (allowed, other):
            job = Job(printer_id=printer, template_key=None, payload={}, state="queued")
            job.api_key_id = key_id
            db.add(job)
            await db.flush()
            owned[printer] = str(job.id)
        await db.commit()
    stream = await _open(app, _key_header(key))
    try:
        await _connected(stream)
        _job_event(_bus(app), other, job_id=owned[other])
        _job_event(_bus(app), allowed, job_id=owned[allowed])
        ev = await stream.event_of_type("job.state_changed")
        assert ev["payload"]["printer_id"] == str(allowed)
        # nothing of the other printer is subscribed at all
        assert _bus(app).subscriber_count(f"printer:{other}:queue") == 0
    finally:
        await stream.close()


@pytest.mark.asyncio
async def test_admin_key_with_a_stored_printer_list_streams_every_printer(hub_app):
    """#283: the list an older version stored on an admin key is ignored by the stream."""
    app, _ = hub_app
    allowed = await _insert_printer("alpha")
    other = await _insert_printer("beta")
    key, _ = await _insert_key(["admin"], allowed_printer_ids=[str(allowed)])
    stream = await _open(app, _key_header(key), f"printer_id={other}")
    try:
        await _connected(stream)
        _job_event(_bus(app), other)
        ev = await stream.event_of_type("job.state_changed")
        assert ev["payload"]["printer_id"] == str(other)
    finally:
        await stream.close()


@pytest.mark.asyncio
async def test_restricted_key_cannot_ask_for_other_printer(hub_app):
    app, _ = hub_app
    allowed = await _insert_printer("alpha")
    other = await _insert_printer("beta")
    key, _ = await _insert_key(["read"], allowed_printer_ids=[str(allowed)])
    stream = await _open(app, _key_header(key), f"printer_id={other}")
    try:
        assert await stream.wait_started() == 403
    finally:
        await stream.close()


@pytest.mark.asyncio
async def test_subscriber_cap_429(hub_app, monkeypatch):
    app, _ = hub_app
    _set_env(monkeypatch, sse_max_subscribers="1")
    key, _ = await _insert_key(["read"])
    first = await _open(app, _key_header(key))
    second = None
    try:
        await _connected(first)
        second = await _open(app, _key_header(key))
        assert await second.wait_started() == 429
    finally:
        await first.close()
        if second is not None:
            await second.close()


@pytest.mark.asyncio
async def test_disconnect_releases_subscriptions(hub_app):
    app, _ = hub_app
    key, _ = await _insert_key(["read"])
    printer_id = await _insert_printer("alpha")
    stream = await _open(app, _key_header(key))
    await _connected(stream)
    assert _bus(app).subscriber_count("hub") == 1
    await stream.close()
    await asyncio.sleep(0.1)
    assert _bus(app).subscriber_count("hub") == 0
    assert _bus(app).subscriber_count(f"printer:{printer_id}:queue") == 0


# --------------------------------------------------------------------------
# Fix round 1
# --------------------------------------------------------------------------


def _hub_event(bus: EventBus, printer_id: UUID | str, change: str = "updated") -> None:
    bus.publish(
        "hub",
        BusEvent(
            channel="hub",
            event_id=bus.next_event_id("hub"),
            event_type="hub.printers_changed",
            timestamp=datetime.now(UTC),
            data={"printer_id": str(printer_id), "change": change},
        ),
    )


@pytest.mark.asyncio
async def test_restricted_key_gets_no_hub_events_of_other_printers(hub_app):
    app, _ = hub_app
    allowed = await _insert_printer("alpha")
    other = await _insert_printer("beta")
    key, _ = await _insert_key(["read"], allowed_printer_ids=[str(allowed)])
    stream = await _open(app, _key_header(key))
    try:
        await _connected(stream)
        _hub_event(_bus(app), other, "disabled")
        _hub_event(_bus(app), allowed, "updated")
        ev = await stream.event_of_type("hub.printers_changed")
        assert ev["payload"]["data"]["printer_id"] == str(allowed)
    finally:
        await stream.close()


@pytest.mark.asyncio
async def test_printer_filtered_stream_gets_no_hub_events_of_other_printers(hub_app):
    app, _ = hub_app
    first = await _insert_printer("alpha")
    second = await _insert_printer("beta")
    key, _ = await _insert_key(["read"])
    stream = await _open(app, _key_header(key), f"printer_id={first}")
    try:
        await _connected(stream)
        _hub_event(_bus(app), second, "created")
        _hub_event(_bus(app), first, "updated")
        ev = await stream.event_of_type("hub.printers_changed")
        assert ev["payload"]["data"]["printer_id"] == str(first)
    finally:
        await stream.close()


@pytest.mark.asyncio
async def test_open_streams_do_not_pin_db_connections(hub_app):
    import app.db.engine as _engine_module

    app, client = hub_app
    key, _ = await _insert_key(["read"])
    await _insert_printer("alpha")
    streams = [await _open(app, _key_header(key)) for _ in range(20)]
    try:
        for stream in streams:
            await _connected(stream)
        # Snapshot reads are short-lived; once they are done nothing may stay checked out.
        pool = _engine_module.engine.pool  # type: ignore[attr-defined]
        for _ in range(100):
            if pool.checkedout() == 0:
                break
            await asyncio.sleep(0.05)
        assert pool.checkedout() == 0
        resp = await asyncio.wait_for(
            client.get("/api/v1/printers", headers=_key_header(key)), timeout=3.0
        )
        assert resp.status_code == 200
    finally:
        for stream in streams:
            await stream.close()


@pytest.mark.asyncio
async def test_revoked_session_is_noticed_on_a_busy_stream(hub_app, monkeypatch):
    app, client = hub_app
    _set_env(monkeypatch, sse_heartbeat_s="0.2")
    key, _ = await _insert_key(["admin"])
    printer_id = await _insert_printer("alpha")
    assert (await _sign_in(client, key)).status_code == 204
    cookie = f"lph_session={client.cookies.get('lph_session')}"
    stream = await _open(app, {"Cookie": cookie})

    async def publisher() -> None:
        while True:
            _job_event(_bus(app), printer_id)
            await asyncio.sleep(0.02)  # far more often than the heartbeat

    async def scenario() -> None:
        await _connected(stream)
        await stream.event_of_type("job.state_changed")
        async with _factory()() as db:
            await db.execute(update(UiSession).values(revoked_at=datetime.now(UTC)))
            await db.commit()
        await stream.event_of_type("auth.expired")

    pump = asyncio.create_task(publisher())
    try:
        # One budget for everything: a stream that never notices must fail, not hang.
        await asyncio.wait_for(scenario(), timeout=8.0)
    finally:
        pump.cancel()
        await stream.close()


@pytest.mark.asyncio
async def test_concurrent_opens_beyond_the_cap_get_429(hub_app, monkeypatch):
    app, _ = hub_app
    _set_env(monkeypatch, sse_max_subscribers="2")
    key, _ = await _insert_key(["read"])
    streams = [await _open(app, _key_header(key)) for _ in range(6)]
    try:
        statuses = await asyncio.gather(*(s.wait_started() for s in streams))
        assert sorted(statuses) == [200, 200, 429, 429, 429, 429]
    finally:
        for stream in streams:
            await stream.close()


def _queue_subscribers(app, printer_id: str) -> int:
    return _bus(app).subscriber_count(f"printer:{printer_id}:queue")


async def _next_hub_change(stream: Stream) -> str:
    return (await stream.event_of_type("hub.printers_changed"))["payload"]["data"]["change"]


@pytest.mark.asyncio
async def test_put_enabled_false_unsubscribes_the_printer(hub_app):
    app, client = hub_app
    key, _ = await _insert_key(["admin"])
    headers = _key_header(key)
    created = await client.post(
        "/api/v1/admin/printers", json=_printer_body("zeta"), headers=headers
    )
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    other = await _insert_printer("zeta-other")
    stream = await _open(app, headers)
    try:
        await _connected(stream)
        assert _queue_subscribers(app, pid) == 1
        resp = await client.put(
            "/api/v1/admin/printers/zeta", json={"enabled": False}, headers=headers
        )
        assert resp.status_code == 200, resp.text
        assert await _next_hub_change(stream) == "updated"
        assert _queue_subscribers(app, pid) == 0
        _job_event(_bus(app), UUID(pid))
        # Another printer's event proves the disabled one stays silent.
        _job_event(_bus(app), other)
        seen = await stream.event_of_type("job.state_changed")
        assert seen["payload"]["printer_id"] != pid
    finally:
        await stream.close()


@pytest.mark.asyncio
async def test_printer_created_disabled_is_not_subscribed(hub_app):
    app, client = hub_app
    key, _ = await _insert_key(["admin"])
    headers = _key_header(key)
    stream = await _open(app, headers)
    try:
        await _connected(stream)
        resp = await client.post(
            "/api/v1/admin/printers",
            json={**_printer_body("eta"), "enabled": False},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        pid = resp.json()["id"]
        assert await _next_hub_change(stream) == "created"
        assert _queue_subscribers(app, pid) == 0
    finally:
        await stream.close()


@pytest.mark.asyncio
async def test_put_enabled_true_subscribes_and_sends_a_snapshot(hub_app):
    app, client = hub_app
    key, _ = await _insert_key(["admin"])
    headers = _key_header(key)
    created = await client.post(
        "/api/v1/admin/printers",
        json={**_printer_body("theta"), "enabled": False},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    from app.repositories import printer_status_cache as status_cache_repo

    async with _factory()() as db:
        await status_cache_repo.upsert(
            db,
            UUID(pid),
            raw_block=b"\x00",
            parsed={"hr_printer_status": "idle", "online": True, "loaded_tape_mm": 12},
            captured_at=datetime.now(UTC),
        )
    stream = await _open(app, headers)
    try:
        await _connected(stream)
        assert _queue_subscribers(app, pid) == 0
        resp = await client.put(
            "/api/v1/admin/printers/theta", json={"enabled": True}, headers=headers
        )
        assert resp.status_code == 200, resp.text
        # The snapshot precedes the hub frame that announced the change.
        status_ev = await stream.event_of_type("printer.status")
        assert status_ev["payload"]["printer_id"] == pid
        assert await _next_hub_change(stream) == "updated"
        assert _queue_subscribers(app, pid) == 1
    finally:
        await stream.close()


@pytest.mark.asyncio
async def test_queue_producer_transitions_reach_the_stream(hub_app):
    """The real producer (not a hand-built event) feeds the stream, one frame per transition.

    Ported from the removed fragment-stream tests, which covered the same
    producer -> bus -> stream path for the old HTML endpoint.
    """
    from app.services.job_lifecycle import Job, JobState
    from app.services.producers.print_queue_producer import PrintQueueProducer

    app, _ = hub_app
    key, _ = await _insert_key(["admin"])
    printer_id = await _insert_printer("producer")
    producer = PrintQueueProducer(_bus(app))
    stream = await _open(app, _key_header(key))
    try:
        await _connected(stream)
        job_ids = [f"job-{i}" for i in range(3)]
        for job_id in job_ids:
            job = Job(id=job_id, printer_id=printer_id)
            producer.handle_transition(job, JobState.QUEUED, JobState.PRINTING, queue_depth=2)
        seen: list[str] = []
        while len(seen) < len(job_ids):
            ev = await stream.event_of_type("job.state_changed")
            assert ev["payload"]["data"]["from_state"] == "queued"
            assert ev["payload"]["data"]["to_state"] == "printing"
            assert ev["payload"]["data"]["queue_depth"] == 2
            seen.append(ev["payload"]["data"]["job_id"])
        assert seen == job_ids
    finally:
        await stream.close()


@pytest.mark.asyncio
async def test_stream_carries_sheet_updates(hub_app):
    """Every stream subscribes to ``sheets`` (sheet archive, Task 6); no printer scope applies."""
    from app.sheets.events import publish_sheet_updated

    app, _ = hub_app
    key, _ = await _insert_key(["read"])
    stream = await _open(app, _key_header(key))
    try:
        await _connected(stream)
        assert _bus(app).subscriber_count("sheets") == 1
        publish_sheet_updated(
            _bus(app), code="L4736-0002", free=31, total=48, changed=[5], state="active"
        )
        ev = await stream.event_of_type("sheet.updated")
        assert ev["payload"]["channel"] == "sheets"
        assert ev["payload"]["printer_id"] is None
        assert ev["payload"]["data"]["code"] == "L4736-0002"
    finally:
        await stream.close()
    await asyncio.sleep(0.1)
    assert _bus(app).subscriber_count("sheets") == 0


@pytest.mark.asyncio
async def test_sheet_updated_event_on_stream(hub_app):
    """Marking a cell over HTTP reaches an open stream as ``sheet.updated`` (spec 16)."""
    from tests.integration.api.test_sheet_types_api import _body

    app, client = hub_app
    admin_key, _ = await _insert_key(["admin"])
    print_key, _ = await _insert_key(["print"])
    read_key, _ = await _insert_key(["read"])
    made = await client.post("/api/v1/sheet-types", json=_body(), headers=_key_header(admin_key))
    assert made.status_code == 201, made.text
    sheet = await client.post(
        "/api/v1/sheets",
        json={"type": "acme-t1", "id_placement": "manual"},
        headers=_key_header(print_key),
    )
    assert sheet.status_code == 201, sheet.text
    code = sheet.json()["code"]
    stream = await _open(app, _key_header(read_key))
    try:
        await _connected(stream)
        marked = await client.post(
            f"/api/v1/sheets/{code}/cells/mark",
            json={"cells": [{"cell": 7}, {"cell": 3}]},
            headers=_key_header(print_key),
        )
        assert marked.status_code == 200, marked.text
        ev = await stream.event_of_type("sheet.updated")
        assert ev["payload"]["channel"] == "sheets"
        assert ev["payload"]["data"] == {
            "code": code,
            "free": 46,
            "total": 48,
            "changed": [3, 7],
            "state": "active",
        }
    finally:
        await stream.close()
