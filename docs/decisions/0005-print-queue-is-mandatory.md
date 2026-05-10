# 0005 — Print queue is mandatory (printers have none)

- **Status:** Accepted
- **Date:** 2026-05-10
- **Deciders:** maintainer

## Context

Brother PT-Series and QL-Series label printers expose **TCP port 9100** for raw raster bytes. The Brother Raster Command Reference v1.02 confirms (sections 1 and 5):

- The TCP/9100 connection is a **single stream** — the printer accepts one job at a time
- A second simultaneous TCP connection is rejected
- Once a print starts, **no further commands are accepted until printing completes** — even the status-information-request command (`ESC i S`) is forbidden
- Mid-print cancellation is not possible

The hub may receive concurrent print requests (multiple webhook deliveries from Spoolman + Grocy + manual UI submissions). It must serialise these without losing any.

## Decision

The hub maintains a **per-printer asyncio queue** plus a **per-printer worker coroutine** that owns the single TCP/9100 connection. Jobs are submitted to the queue by API handlers, picked up by the worker, and processed serially.

Jobs are persisted in **SQLite** before being placed on the in-memory queue. After a hub restart, jobs in `queued` or `printing` state are marked `failed_restart` so the user can decide whether to retry.

**Job state machine:**

```
queued ──► printing ──► completed
   │                ╲──► failed
   │
   ├──► paused ──► queued | cancelled
   │
   └──► cancelled
```

- `printing` is **terminal-bound** — only `completed` or `failed` are reachable from it (no mid-print cancel, no mid-print pause)
- Pause/resume operate on the queue, not on the printer

**Operations exposed to the user:**

| Action | Allowed for | Effect |
|---|---|---|
| Pause job | `queued` | → `paused` |
| Resume job | `paused` | → `queued` (re-enqueued at the back) |
| Cancel job | `queued`, `paused` | → `cancelled` |
| Retry job | `failed` | new job with same payload, `parent_job_id` linked |
| Priority | `queued`, `paused` | move to front of the queue |
| Pause printer (worker) | active worker | running job finishes; no new jobs picked |
| Resume printer | paused worker | resume picking from queue |
| Clear queue | any time | all `queued` + `paused` → `cancelled` |

## Options considered

### Option A — Hub-side asyncio queue + SQLite persistence (chosen)
- Pros: matches Brother's "single stream" reality; surviving restarts via SQLite; clean state machine
- Cons: more code to maintain than naive direct-print

### Option B — Naive direct print (no queue)
- Pros: simplest code
- Cons: concurrent submissions race; second TCP connect rejected; lost jobs on busy hub

### Option C — External queue (Redis Streams, RabbitMQ, etc.)
- Pros: scales to multi-container hub deployments
- Cons: massive overkill; adds a service to deploy; not warranted for ~5 printers and < 100 jobs/day

## Consequences

- `PrintQueue` class with one `asyncio.Queue` and one worker per printer (see `backend/app/services/print_queue.py`)
- `Job` model in SQLite with state, priority, queue_order, parent_job_id, retry_count, error_msg, error_flags
- Worker recovers from crashes: open jobs at startup → flagged for user decision
- API endpoints: `POST /api/print/{printer}` returns 202 + `job_id` immediately (non-blocking); GET `/api/jobs/{id}` for polling; SSE pushes state transitions
- Mid-print cancel returns 409 Conflict with explanation
- Pause/resume printer is a separate concept from pause/resume job — both can exist independently

## References

- Brother Raster Command Reference v1.02, sections 1 ("Printing using raster commands") and 5 ("Flow charts")
- Issue [#13](https://github.com/strausmann/label-printer-hub/issues/13) — print queue with full lifecycle
- Related: ADR 0001 (two-container), ADR 0002 (Python backend), ADR 0006 (status sources during print)
