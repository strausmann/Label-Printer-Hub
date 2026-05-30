"""SSE endpoint: GET /api/events?printer_id=<uuid>

Subscribes to three EventBus channels for the requested printer and streams
events as ``text/event-stream``. Each event is rendered as an HTML fragment
by ``_render_fragment`` so HTMX ``sse-swap`` can inject it directly.

Resource limits (all configurable via PRINTER_HUB_SSE_* env vars):
- Max subscribers per printer: PRINTER_HUB_SSE_MAX_SUBSCRIBERS (default 100)
- Idle timeout: PRINTER_HUB_SSE_IDLE_TIMEOUT_S (default 300 s)
- Heartbeat interval: PRINTER_HUB_SSE_HEARTBEAT_S (default 30 s)

Auth: none beyond the Pangolin proxy SSO at the network layer.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from prometheus_client import Counter, Gauge
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.config import Settings, get_settings
from app.db.session import get_session
from app.models.job import Job, JobState
from app.repositories import jobs as jobs_repo
from app.repositories import printer_status_cache as status_cache_repo
from app.repositories import printers as printers_repo
from app.schemas.problem import ProblemDetail
from app.services.event_bus import BusEvent, EventBus

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["events"])

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

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

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

# Module-level fallback constants — used only by tests that patch these
# directly (e.g. test_heartbeat_emitted_after_timeout) and by _sse_stream
# when no explicit limit is passed.  The route handler always reads from
# Settings so these are never used in production paths.
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


async def _build_initial_snapshot(
    printer_id: uuid.UUID,
    session: AsyncSession | None,
) -> list[BusEvent]:
    """Query DB/cache for current printer state and return synthetic BusEvents.

    Emitted once on connect so the client immediately sees the current
    status without waiting for the next state-change event (Finding F1).

    Returns an empty list when ``session`` is ``None`` (test/compat path) or
    when no cached data is available yet.

    Event IDs use the sentinel value 0 to distinguish snapshot events from
    live events (id: 0 means "initial snapshot, not a live transition").
    """
    if session is None:
        return []

    snapshot: list[BusEvent] = []
    now = datetime.now(UTC)
    pid = str(printer_id)

    # --- printer.status from PrinterStatusCache ---
    try:
        cache = await status_cache_repo.get(session, printer_id)
        if cache is not None and cache.parsed:
            parsed = cache.parsed
            ts = cache.captured_at or now
            snapshot.append(
                BusEvent(
                    channel=f"printer:{pid}:state",
                    event_id=0,
                    event_type="printer.status",
                    timestamp=ts,
                    data={
                        "hr_printer_status": parsed.get("hr_printer_status", "unknown"),
                        "error_flags": parsed.get("error_flags", []),
                        "online": parsed.get("online", False),
                    },
                )
            )
            # --- printer.tape_changed from same cache row ---
            # F4: only emit when loaded_tape_mm is present — a None value would
            # render "No tape loaded" and overwrite the correct client DOM state.
            loaded_tape_mm = parsed.get("loaded_tape_mm")
            if loaded_tape_mm is not None:
                snapshot.append(
                    BusEvent(
                        channel=f"printer:{pid}:tape",
                        event_id=0,
                        event_type="printer.tape_changed",
                        timestamp=ts,
                        data={
                            "from_mm": None,
                            "to_mm": loaded_tape_mm,
                            "tape_label": f"{loaded_tape_mm}mm",
                        },
                    )
                )
    except Exception:
        _log.debug("_build_initial_snapshot: status cache read failed for %s", pid)

    # --- job.state_changed for each active (QUEUED|PRINTING) job ---
    try:
        # F5: Use a COUNT query over all non-terminal states so queue_depth is
        # accurate even when the result set exceeds any list-query limit.
        _non_terminal = (JobState.QUEUED.value, JobState.PRINTING.value)
        count_stmt = (
            select(func.count())
            .select_from(Job)
            .where(col(Job.printer_id) == printer_id)
            .where(col(Job.state).in_(_non_terminal))
        )
        queue_depth_result = await session.execute(count_stmt)
        queue_depth: int = queue_depth_result.scalar_one()

        # Fetch up to 5 representative jobs for the snapshot frames
        active_jobs = await jobs_repo.list_by_filter(
            session,
            printer_id=printer_id,
            state=JobState.QUEUED.value,
            limit=5,
        )
        active_jobs += await jobs_repo.list_by_filter(
            session,
            printer_id=printer_id,
            state=JobState.PRINTING.value,
            limit=5,
        )
        for job in active_jobs[:5]:  # cap snapshot at 5 jobs
            snapshot.append(
                BusEvent(
                    channel=f"printer:{pid}:queue",
                    event_id=0,
                    event_type="job.state_changed",
                    timestamp=job.created_at,
                    data={
                        "job_id": str(job.id),
                        "from_state": job.state,
                        "to_state": job.state,
                        "queue_depth": queue_depth,
                        "error_code": None,
                    },
                )
            )
    except Exception:
        _log.debug("_build_initial_snapshot: job query failed for %s", pid)

    return snapshot


async def _sse_stream(
    printer_id: uuid.UUID,
    bus: EventBus,
    request: Request,
    subscriber_id: str,
    channels: list[str],
    *,
    heartbeat_interval_s: float = _HEARTBEAT_INTERVAL_S,
    idle_timeout_s: float = _IDLE_TIMEOUT_S,
    session: AsyncSession | None = None,
) -> AsyncGenerator[str, None]:
    """Core SSE generator. Yields SSE-formatted strings.

    Subscribes to all three channels for ``printer_id``, multiplexes them
    with ``asyncio.wait``, and emits SSE frames. A keepalive comment is sent
    every ``heartbeat_interval_s`` seconds. The connection is closed after
    ``idle_timeout_s`` seconds of inactivity. Subscribers are unsubscribed
    in a ``finally`` block so no queue leaks occur on client disconnect.

    The subscriber-cap check is performed in ``sse_events`` before this
    generator is created so the 429 response can be returned before the
    ``StreamingResponse`` is constructed (raising inside a started stream
    is not catchable by normal exception handlers).

    ``session`` is used for the initial state snapshot (Finding F1): on
    connect, current DB/cache state is queried and emitted as synthetic
    SSE frames so the client immediately sees the current status without
    waiting for the next real event.
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
    sse_connections_total.labels(printer_id=str(printer_id)).inc()
    sse_active_subscribers.inc()
    _log.info(
        "SSE connect: printer=%s subscriber=%s remote=%s",
        printer_id,
        subscriber_id,
        request.client,
    )

    # Connection-confirmation comment frame so the client knows the stream is live
    yield ": connected\n\n"

    # Initial state snapshot — emit current state so clients don't see empty
    # widgets until the next real event (Finding F1).
    snapshot_events = await _build_initial_snapshot(printer_id, session)
    for snap_event in snapshot_events:
        html_fragment = await _render_fragment(snap_event)
        if not html_fragment.strip():
            continue
        clean_html = html_fragment.replace("\r", "")
        data_lines = "\n".join(f"data: {line}" for line in clean_html.split("\n"))
        yield f"id: {snap_event.event_id}\nevent: {snap_event.event_type}\n{data_lines}\n\n"

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
                    timeout=heartbeat_interval_s,
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
                if now - last_activity > idle_timeout_s:
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
                if dropped:
                    sse_events_dropped_total.labels(
                        channel=event.channel, subscriber_id=subscriber_id
                    ).inc(dropped)
                # Skip the frame entirely when the fragment is empty (unknown
                # event type, missing template, or render error).  Emitting an
                # SSE frame with an empty data: payload causes HTMX sse-swap to
                # overwrite the target element with empty content, wiping the
                # live status widget (bot-review Finding F2).
                if not html_fragment.strip():
                    _log.debug(
                        "_sse_stream: skipping empty fragment for event_type=%s",
                        event.event_type,
                    )
                    continue
                sse_events_published_total.labels(channel=event.channel).inc()
                # Emit raw HTML as the SSE data payload so HTMX sse-swap can
                # inject it directly into the DOM.  The SSE spec forbids bare
                # newline characters inside a single data: field; multi-line
                # HTML is split across multiple "data: " lines (each line is
                # concatenated with a newline by the browser before injection).
                # CR characters are stripped to avoid CR+LF ambiguity.
                clean_html = html_fragment.replace("\r", "")
                data_lines = "\n".join(f"data: {line}" for line in clean_html.split("\n"))
                yield (f"id: {event.event_id}\nevent: {event.event_type}\n{data_lines}\n\n")
    finally:
        sse_active_subscribers.dec()
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
        "A keepalive comment is sent every PRINTER_HUB_SSE_HEARTBEAT_S seconds "
        "(default 30 s) when no events flow. "
        "Closes automatically after PRINTER_HUB_SSE_IDLE_TIMEOUT_S seconds of "
        "inactivity (default 300 s). "
        "On reconnect the stream starts fresh — ``Last-Event-ID`` is "
        "observed but replay is deferred to Phase 7. "
        "Returns 404 if ``printer_id`` does not exist in the database. "
        "Returns 429 if the per-printer subscriber limit "
        "(PRINTER_HUB_SSE_MAX_SUBSCRIBERS, default 100) is reached."
    ),
    response_class=StreamingResponse,
    response_model=None,
    tags=["events"],
)
async def sse_events(
    printer_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
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
    # Each SSE connection subscribes to exactly 3 channels with the same
    # subscriber_id.  distinct_subscriber_count(channels=...) counts unique
    # subscriber_ids only on those channels, giving the true per-printer
    # connection count without touching EventBus private state (bot-review
    # Finding F4/F6).
    channels = [
        f"printer:{printer_id}:queue",
        f"printer:{printer_id}:state",
        f"printer:{printer_id}:tape",
    ]
    max_subs = settings.sse_max_subscribers
    if bus.distinct_subscriber_count(channels=channels) >= max_subs:
        problem = ProblemDetail(
            type="sse-subscriber-limit",
            title="Too many SSE subscribers for this printer",
            status=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(f"Limit of {max_subs} concurrent subscribers per printer reached."),
        )
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content=problem.model_dump(exclude_none=True),
        )

    subscriber_id = str(uuid.uuid4())
    return StreamingResponse(
        _sse_stream(
            printer_id,
            bus,
            request,
            subscriber_id,
            channels,
            heartbeat_interval_s=settings.sse_heartbeat_s,
            idle_timeout_s=settings.sse_idle_timeout_s,
            session=session,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
