"""Global JSON event stream: ``GET /api/v1/events[?printer_id=<uuid>]`` (web UI).

One ``EventSource`` per browser tab. Authenticates like every ``read`` route
(API key header, session cookie, SSO), so the cookie of a signed-in browser works.

Frames (``text/event-stream``):

* ``: connected`` right after the subscriptions are in place,
* a snapshot per visible printer (``id: 0``), then live events,
* ``id: N`` / ``event: <type>`` / ``data: {"channel", "printer_id", "type", "ts", "data"}``,
* ``: keepalive`` every ``sse_heartbeat_s``; on the same beat the credentials are
  re-checked and the stream ends with ``event: auth.expired`` once they are gone.

The stream subscribes to ``hub`` and to ``printer:{id}:{queue,state,tape}`` of each
enabled printer (or only the requested one), never to printers outside the caller's
``allowed_printer_ids``. Printers that appear later (``hub.printers_changed``) are
picked up without reconnecting.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.engine as db_engine
from app.auth import sessions as ui_sessions
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_read
from app.config import Settings, get_settings
from app.db.session import get_session
from app.observability.sse_metrics import (
    sse_active_subscribers,
    sse_connections_total,
    sse_events_dropped_total,
    sse_events_published_total,
)
from app.repositories import printers as printers_repo
from app.schemas.problem import ProblemDetail
from app.services.event_bus import BusEvent, EventBus
from app.services.sse_snapshot import build_snapshot

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["events"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
ReadAuthDep = Annotated[AuthContext, Depends(require_read)]

HUB_CHANNEL = "hub"
PRINTERS_CHANGED = "hub.printers_changed"
AUTH_EXPIRED = "auth.expired"
_PRINTER_CHANNEL_SUFFIXES = ("queue", "state", "tape")


def printer_channels(printer_id: str | uuid.UUID) -> list[str]:
    return [f"printer:{printer_id}:{suffix}" for suffix in _PRINTER_CHANNEL_SUFFIXES]


def _printer_id_of(channel: str) -> str | None:
    parts = channel.split(":")
    return parts[1] if len(parts) == 3 and parts[0] == "printer" else None


def _frame(event_id: int, event_type: str, payload: dict[str, Any]) -> str:
    # json.dumps never emits a raw newline, so one ``data:`` line is always enough.
    data = json.dumps(payload, separators=(",", ":"))
    return f"id: {event_id}\nevent: {event_type}\ndata: {data}\n\n"


def _event_frame(event: BusEvent) -> str:
    return _frame(
        event.event_id,
        event.event_type,
        {
            "channel": event.channel,
            "printer_id": _printer_id_of(event.channel),
            "type": event.event_type,
            "ts": event.timestamp.isoformat(),
            "data": event.data,
        },
    )


def _snapshot_frame(item: dict[str, Any]) -> str:
    return _frame(
        0,
        item["type"],
        {
            "channel": item["channel"],
            "printer_id": _printer_id_of(item["channel"]),
            "type": item["type"],
            "ts": item["ts"].isoformat(),
            "data": item["data"],
        },
    )


def _expired_frame() -> str:
    return _frame(
        0,
        AUTH_EXPIRED,
        {
            "channel": HUB_CHANNEL,
            "printer_id": None,
            "type": AUTH_EXPIRED,
            "ts": datetime.now(UTC).isoformat(),
            "data": {},
        },
    )


async def _current_printer_ids(
    auth: AuthContext, token: str, settings: Settings
) -> list[str] | None:
    """Re-check the credentials in a short-lived DB session.

    Returns the caller's current ``allowed_printer_ids`` (empty = unrestricted), or
    ``None`` when the session or key is no longer usable. Header-based sources (SSO,
    Basic bypass) carry no stored state and stay valid for the life of the connection.
    """
    async with db_engine.async_session() as db:
        if auth.session_id is not None:
            valid = await ui_sessions.load_valid(db, token, settings)
            if valid is None or valid.row.id != auth.session_id:
                return None
            return valid.allowed_printer_ids
        if auth.api_key_id is not None:
            return await ui_sessions.usable_key_printer_ids(db, auth.api_key_id)
    return list(auth.allowed_printer_ids)


class _Subscriptions:
    """The queues one stream listens on, keyed by channel."""

    def __init__(self, bus: EventBus, subscriber_id: str) -> None:
        self._bus = bus
        self._subscriber_id = subscriber_id
        self.queues: dict[str, asyncio.Queue[BusEvent | None]] = {}

    def add(self, channels: list[str]) -> None:
        for channel in channels:
            if channel not in self.queues:
                self.queues[channel] = self._bus.subscribe(channel, self._subscriber_id)

    def drop(self, channels: list[str]) -> None:
        for channel in channels:
            if self.queues.pop(channel, None) is not None:
                self._bus.unsubscribe(channel, self._subscriber_id)

    def close(self) -> None:
        self.drop(list(self.queues))


async def _event_stream(
    request: Request,
    bus: EventBus,
    *,
    auth: AuthContext,
    token: str,
    settings: Settings,
    printer_ids: list[str],
    only_printer: str | None,
    allowed: list[str],
) -> AsyncGenerator[str, None]:
    subscriber_id = str(uuid.uuid4())
    subs = _Subscriptions(bus, subscriber_id)
    subs.add([HUB_CHANNEL])
    for pid in printer_ids:
        subs.add(printer_channels(pid))
    sse_connections_total.labels(printer_id=only_printer or "all").inc()
    sse_active_subscribers.inc()
    _log.info("SSE v1 connect: subscriber=%s printers=%d", subscriber_id, len(printer_ids))
    try:
        yield ": connected\n\n"

        # Subscriptions are in place before the snapshot, so nothing between the two is lost.
        async with db_engine.async_session() as db:
            for pid in printer_ids:
                for item in await build_snapshot(db, uuid.UUID(pid)):
                    yield _snapshot_frame(item)

        loop = asyncio.get_running_loop()
        last_activity = loop.time()
        while True:
            if await request.is_disconnected():
                break
            tasks = {asyncio.create_task(q.get()): ch for ch, q in subs.queues.items()}
            try:
                await asyncio.wait(
                    tasks, timeout=settings.sse_heartbeat_s, return_when=asyncio.FIRST_COMPLETED
                )
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                for task in tasks:
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await task

            # A getter that finished between the wait and the cancel has consumed an event.
            done = {t for t in tasks if t.done() and not t.cancelled()}
            if not done:
                current = await _current_printer_ids(auth, token, settings)
                if current is None or set(current) != set(allowed):
                    # Gone, or the restriction changed: end the stream so the client
                    # reconnects (and, if the credentials are gone, signs in again).
                    yield _expired_frame()
                    break
                if loop.time() - last_activity > settings.sse_idle_timeout_s:
                    break
                yield ": keepalive\n\n"
                continue

            last_activity = loop.time()
            for task in done:
                try:
                    event = task.result()
                except Exception:
                    continue
                if event is None:
                    continue
                dropped = bus.get_dropped_count(subscriber_id)
                if dropped:
                    sse_events_dropped_total.labels(
                        channel=event.channel, subscriber_id=subscriber_id
                    ).inc(dropped)
                sse_events_published_total.labels(channel=event.channel).inc()
                if event.event_type == PRINTERS_CHANGED and only_printer is None:
                    async for frame in _follow_printer_change(subs, event, allowed):
                        yield frame
                yield _event_frame(event)
    finally:
        subs.close()
        sse_active_subscribers.dec()
        _log.info("SSE v1 cleanup: subscriber=%s", subscriber_id)


async def _follow_printer_change(
    subs: _Subscriptions, event: BusEvent, allowed: list[str]
) -> AsyncGenerator[str, None]:
    """Subscribe to a printer that appeared (or enabled), drop one that was disabled."""
    pid = str(event.data.get("printer_id", ""))
    change = event.data.get("change")
    if not pid or (allowed and pid not in allowed):
        return
    if change in ("created", "enabled"):
        subs.add(printer_channels(pid))
        async with db_engine.async_session() as db:
            for item in await build_snapshot(db, uuid.UUID(pid)):
                yield _snapshot_frame(item)
    elif change == "disabled":
        subs.drop(printer_channels(pid))


@router.get(
    "/events",
    summary="Server-Sent Events stream for the web UI",
    description=(
        "``text/event-stream`` with JSON frames ``{channel, printer_id, type, ts, data}``. "
        "Without ``printer_id`` it carries every printer the caller may see plus the "
        "``hub`` channel (``hub.printers_changed``). Ends with ``auth.expired`` when the "
        "session or key stops being valid. Returns 404 for an unknown ``printer_id``, 403 "
        "when the credentials exclude it, 429 when ``PRINTER_HUB_SSE_MAX_SUBSCRIBERS`` "
        "connections are open."
    ),
    response_class=StreamingResponse,
    response_model=None,
)
async def stream_events(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    auth: ReadAuthDep,
    printer_id: uuid.UUID | None = None,
) -> StreamingResponse | JSONResponse:
    bus: EventBus = request.app.state.event_bus
    allowed = list(auth.allowed_printer_ids)

    if printer_id is not None:
        if await printers_repo.get(session, printer_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error_code": "printer_not_found",
                    "error_message": f"Printer {printer_id} not found.",
                },
            )
        if allowed and str(printer_id) not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error_code": "printer_not_allowed",
                    "error_message": (
                        f"These credentials are not authorised for printer {printer_id}."
                    ),
                },
            )
        printer_ids = [str(printer_id)]
    else:
        printer_ids = [
            str(p.id)
            for p in await printers_repo.list_all(session)
            if not allowed or str(p.id) in allowed
        ]

    # Every stream of this kind is subscribed to ``hub``, so its subscriber count is the
    # number of open connections. The 429 is returned before the response starts.
    max_subs = settings.sse_max_subscribers
    if bus.distinct_subscriber_count(channels=[HUB_CHANNEL]) >= max_subs:
        problem = ProblemDetail(
            type="sse-subscriber-limit",
            title="Too many SSE subscribers",
            status=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Limit of {max_subs} concurrent event streams reached.",
        )
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content=problem.model_dump(exclude_none=True),
        )

    session_cookie, _ = ui_sessions.cookie_names(settings)
    return StreamingResponse(
        _event_stream(
            request,
            bus,
            auth=auth,
            token=request.cookies.get(session_cookie, ""),
            settings=settings,
            printer_ids=printer_ids,
            only_printer=str(printer_id) if printer_id else None,
            allowed=allowed,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
