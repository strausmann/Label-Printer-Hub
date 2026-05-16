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
import contextlib
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.repositories import printers as printers_repo
from app.schemas.problem import ProblemDetail
from app.services.event_bus import BusEvent, EventBus

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["events"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# Module-level constants — mirror Settings defaults
_MAX_SUBSCRIBERS_PER_PRINTER: int = 100
_HEARTBEAT_INTERVAL_S: float = 30.0
_IDLE_TIMEOUT_S: float = 300.0

# Shared Jinja2Templates instance — same root as qr.py
_templates_dir = Path(__file__).parent.parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_templates_dir))

# event_type → fragment template path (relative to templates dir)
_FRAGMENT_MAP: dict[str, str] = {
    "job.state_changed": "fragments/job_state.html",
    "printer.status": "fragments/printer_status.html",
    "printer.tape_changed": "fragments/tape_status.html",
}


async def _render_fragment(event: BusEvent) -> str:
    """Render a Jinja2 HTML fragment for the event.

    Returns an HTML string for HTMX sse-swap injection, or an empty string
    if no template is registered for the event type or if the template file
    does not exist yet (safe fallback — client retains its existing DOM).

    Note: ``TemplateResponse`` requires a ``Request`` object (Starlette ≥ 0.37
    API). Fragment templates are rendered synchronously here by reading the
    Jinja2 template directly via ``_templates.get_template`` so we avoid the
    need to thread a dummy ``Request`` through the event path. Full Jinja2
    context rendering is intentional — this keeps the event payload and the
    rendered HTML in sync without a separate serialisation step.
    """
    tmpl_name = _FRAGMENT_MAP.get(event.event_type)
    if not tmpl_name:
        return ""
    try:
        tmpl = _templates.get_template(tmpl_name)
        return tmpl.render({**event.data, "timestamp": event.timestamp.isoformat()})
    except Exception:
        _log.exception("_render_fragment: failed for event_type=%s", event.event_type)
        return ""


async def _sse_stream(
    printer_id: uuid.UUID,
    bus: EventBus,
    request: Request,
    subscriber_id: str,
    channels: list[str],
) -> AsyncGenerator[str, None]:
    """Core SSE generator. Yields SSE-formatted strings.

    Subscribes to all three channels for ``printer_id``, multiplexes them
    with ``asyncio.wait``, and emits SSE frames. A keepalive comment is sent
    every ``_HEARTBEAT_INTERVAL_S`` seconds. The connection is closed after
    ``_IDLE_TIMEOUT_S`` seconds of inactivity. Subscribers are unsubscribed
    in a ``finally`` block so no queue leaks occur on client disconnect.

    The subscriber-cap check is performed in ``sse_events`` before this
    generator is created so the 429 response can be returned before the
    ``StreamingResponse`` is constructed (raising inside a started stream
    is not catchable by normal exception handlers).
    """
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

    # Connection-confirmation comment frame so the client knows the stream is live
    yield ": connected\n\n"

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
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await t

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
        _log.info("SSE cleanup: printer=%s subscriber=%s", printer_id, subscriber_id)


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
    response_model=None,
    tags=["events"],
)
async def sse_events(
    printer_id: uuid.UUID,
    request: Request,
    session: SessionDep,
) -> StreamingResponse | JSONResponse:
    """SSE endpoint for a printer's live event stream."""
    bus: EventBus = request.app.state.event_bus

    # 404: printer must exist before we open the stream
    printer = await printers_repo.get(session, printer_id)
    if printer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"printer {printer_id} not found",
        )

    # 429: subscriber-cap check before constructing StreamingResponse so the
    # HTTP error response can still be returned cleanly (raising inside a
    # started stream is not catchable by normal exception handlers).
    channels = [
        f"printer:{printer_id}:queue",
        f"printer:{printer_id}:state",
        f"printer:{printer_id}:tape",
    ]
    total = sum(bus.subscriber_count(c) for c in channels)
    if total >= _MAX_SUBSCRIBERS_PER_PRINTER:
        problem = ProblemDetail(
            type="sse-subscriber-limit",
            title="Too many SSE subscribers for this printer",
            status=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Limit of {_MAX_SUBSCRIBERS_PER_PRINTER} concurrent subscribers"
                " per printer reached."
            ),
        )
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content=problem.model_dump(exclude_none=True),
        )

    subscriber_id = str(uuid.uuid4())
    return StreamingResponse(
        _sse_stream(printer_id, bus, request, subscriber_id, channels),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
