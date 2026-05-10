# 0009 — Server-Sent Events over WebSockets for live updates

- **Status:** Accepted
- **Date:** 2026-05-10
- **Deciders:** maintainer

## Context

The hub needs to push live status updates to open browser tabs without page reloads — print job state changes, tape changes, queue updates, errors, completion events. Three real-time delivery mechanisms exist for browsers: HTMX-style polling, WebSockets, and Server-Sent Events (SSE).

The data flow is **purely server-to-client**: the browser submits jobs via regular HTTP `POST`, but live updates come from the backend (worker, status probe, tape detector). The browser never needs to push asynchronous messages to the server.

## Decision

The hub uses **Server-Sent Events** for live updates.

- One SSE endpoint per consumer scope: `/api/events?printer_id=<id>` (per-printer) or `/api/events` (all printers)
- An in-memory `EventBus` (Pub/Sub) inside the backend distributes events from producers (PrintQueue worker, StatusProbe loop, TapeChangeDetector) to active SSE subscribers
- Frontend (Go) proxies the SSE stream from backend to browser without payload transformation
- Browser uses HTMX's `hx-ext="sse"` extension; sub-sections of the page declare `sse-swap="<event-type>"` to receive updates
- Heartbeat comment frame every 30 s keeps connections alive through reverse-proxy idle timeouts

## Options considered

### Option A — SSE (chosen)
- Pros: server-to-client only — exactly our need; native HTMX support; auto-reconnect built into the EventSource API; works over plain HTTP/1.1 chunked; easy reverse-proxy configuration; lightweight (text/event-stream, one-direction)
- Cons: server-to-client only (a feature here, not a bug); Internet Explorer doesn't support EventSource (irrelevant in 2026)

### Option B — WebSockets
- Pros: bidirectional; mature ecosystem
- Cons: bidirectional capability is unused; protocol upgrade adds complexity to reverse proxies; harder to debug than text/event-stream; needs ping/pong frame handling we'd just be reinventing

### Option C — HTMX polling (`hx-trigger="every 1s"`)
- Pros: simplest possible — just HTTP GET on a timer
- Cons: latency 1 s minimum; load grows linearly with open tabs; no true "event"-style flow; misses fast state transitions (printing → completed in <1 s); wastes API calls when nothing changed

### Option D — Long polling
- Pros: fallback for environments hostile to SSE (rare)
- Cons: more complex; SSE handles the same use case better with EventSource auto-reconnect

## Consequences

- `EventBus` class in `backend/app/services/event_bus.py` with publish/subscribe API
- SSE endpoint in FastAPI returns `StreamingResponse(media_type="text/event-stream")`
- Reverse proxies must disable response buffering (Traefik `flushinterval=100ms`, Caddy `flush_interval -1`, nginx `X-Accel-Buffering: no`) — sample compose files already handle this
- Pangolin Newt-tunnel works out of the box (HTTP/1.1 chunked is supported)
- Frontend (Go) proxies the stream end-to-end (no buffering on the Go side either)
- Auto-reconnect from the browser is free via EventSource; we send a `Last-Event-ID` header on reconnect to pick up where we left off
- In-memory EventBus is per-container — fine for a single-instance hub. If scaled to multiple containers later, swap to Redis Pub/Sub (tracked separately as a follow-up)

## References

- Issue [#14](https://github.com/strausmann/label-printer-hub/issues/14) — SSE EventBus
- Issue [#5](https://github.com/strausmann/label-printer-hub/issues/5) — browser notifications consume SSE events
- [MDN: Server-sent events](https://developer.mozilla.org/docs/Web/API/Server-sent_events)
- [HTMX SSE extension](https://htmx.org/extensions/sse/)
- Related: ADR 0001 (frontend proxies SSE), ADR 0003 (HTMX is part of the frontend stack)
