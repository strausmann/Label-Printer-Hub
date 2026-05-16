# Phase 6a — REST API (DB-backed CRUD + read endpoints) — Design

**Date:** 2026-05-16
**Status:** Approved (issue #18 scope minus SSE — SSE is Phase 6b)
**Owner:** repo maintainer
**Implementation branch:** `feat/phase6a-rest-api`
**Tracking issues:** strausmann/label-printer-hub#18 (REST), partial — SSE part deferred to Phase 6b (#14)

## Problem

Phase 5 (PR #63, commit `806076f`) landed the persistence layer: six SQLModel tables + repositories + Alembic migrations + lifespan-driven seed/recovery. The DB tables are populated on every boot but nothing reads or writes them from the network — the current `backend/app/api/routes/print.py` has only four endpoints (POST /print, GET /jobs, two more) and they operate on in-memory state.

Issue #18 enumerates ~20 REST endpoints across six aggregates: printers, templates, jobs, lookup (Snipe-IT/Grocy/Spoolman), webhooks (Spoolman/Grocy), QR-scan landing pages. This phase wires those endpoints to the DB-backed repositories from Phase 5 and the existing services (`PrintQueue`, `AppLookupService`, `LabelRenderer`, etc.).

## Goals

- 20 REST endpoints implemented with Pydantic request/response schemas
- Routes organised by aggregate under `backend/app/api/routes/{printers,templates,jobs,lookup,webhooks,qr}.py`
- Dependency injection via FastAPI's `Depends(get_session)` (from Phase 5) plus existing service singletons
- OpenAPI tags + descriptions on every route — generated docs ship at `/docs` and `/redoc`
- Webhook API-key auth middleware (single-key shared secret, env-configured)
- Brother-error → HTTP-status mapping (already partially in `print.py` — extend for the new routes)
- Existing `print.py` routes adapted (not replaced) — preserve current `/api/print/...` URL scheme

## Non-goals

- **SSE** — split into Phase 6b (issue #14), separate PR
- **HTMX templates** — Phase 7 (issue #14 + #15)
- **Browser UI** for the new routes — same as above
- **Authentication beyond webhook API-key** — Phase 4 deferred user/role/auth work; SSO via Pangolin is the production gate
- **Job retry / priority queues** — Phase 6+ stretch; this phase only exposes the read endpoints for jobs + the four existing transitions (pause/resume/cancel/restart)

## Architecture

### Stack

| Component | Choice | Notes |
|---|---|---|
| Framework | FastAPI | Already in use; routes use `APIRouter` per aggregate |
| Schema validation | Pydantic v2 | Already in use; new schemas in `backend/app/schemas/` |
| Session | `Depends(get_session)` from Phase 5 | Yields `AsyncSession` per request |
| OpenAPI tags | One tag per router | `printers`, `templates`, `jobs`, `lookup`, `webhooks`, `qr-landing` |
| Auth | Webhook-only API-key middleware | Env: `LABEL_HUB_WEBHOOK_API_KEY` |
| Errors | Existing `errors.py` extended | `PrinterOfflineError → 503`, `TemplateNotFoundError → 404`, etc. |

### Endpoint inventory (full Phase 6a scope — 20 routes)

#### Printers (6 endpoints)

| Method | Path | Returns | Notes |
|---|---|---|---|
| GET | `/api/printers` | `list[PrinterRead]` | includes `status_summary` from `printer_status_cache` |
| GET | `/api/printers/{id}/status` | `PrinterStatus` | force-fresh ESC i S read; updates the cache |
| GET | `/api/printers/{id}/tape` | `TapeSpec` | current loaded tape |
| GET | `/api/printers/{id}/queue` | `list[JobRead]` | filter state IN ('queued', 'printing') for this printer |
| POST | `/api/printers/{id}/pause` | 204 | toggles `printer_state.paused = true` |
| POST | `/api/printers/{id}/resume` | 204 | toggles `printer_state.paused = false` |
| POST | `/api/printers/{id}/queue/clear` | 204 | bulk `mark_cancelled` for queued jobs |

#### Templates (1 endpoint, read-only this phase)

| Method | Path | Returns | Notes |
|---|---|---|---|
| GET | `/api/templates` | `list[TemplateRead]` | both seed + user templates; query param `?app=<name>` filter |

Create / update / delete are deliberately out of scope until the template-editor UI lands (Phase 7).

#### Jobs (6 endpoints)

| Method | Path | Returns | Notes |
|---|---|---|---|
| GET | `/api/jobs` | `list[JobRead]` | query filters: state, printer_id, since, limit |
| GET | `/api/jobs/{id}` | `JobRead` | single |
| POST | `/api/jobs/{id}/cancel` | `JobRead` | uses `jobs_repo.mark_cancelled` |
| POST | `/api/jobs/{id}/pause` | 202 | not implemented yet; returns 501 with explanatory body (placeholder so OpenAPI shape is complete and Phase 7 UI can wire to the route) |
| POST | `/api/jobs/{id}/resume` | 202 | same — 501 placeholder |
| POST | `/api/jobs/{id}/retry` | `JobRead` | clones a failed job into a new queued job, returns new |

#### Lookup (1 endpoint)

| Method | Path | Returns | Notes |
|---|---|---|---|
| GET | `/api/lookup/{app}/{id}` | `LookupResult` | wraps existing `AppLookupService` for snipeit/grocy/spoolman |

#### Webhooks (2 endpoints)

| Method | Path | Returns | Notes |
|---|---|---|---|
| POST | `/api/webhook/spoolman` | 202 + JobId | API-key auth; payload validation; enqueue print job |
| POST | `/api/webhook/grocy` | 202 + JobId | same |

#### QR-scan landing pages (4 endpoints, plain HTML)

These render minimal HTML detail pages (no HTMX yet — Phase 7) and are intentionally route-style URLs without `/api/` prefix so scanned QR codes land on a clean URL.

| Method | Path | Returns | Notes |
|---|---|---|---|
| GET | `/loc/{id}` | text/html | location detail (mirrors Hangar's `/loc/` for cross-link UX) |
| GET | `/asset/{id}` | text/html | redirects to integration's asset page or shows local detail |
| GET | `/spool/{id}` | text/html | redirects to Spoolman or shows local |
| GET | `/product/{id}` | text/html | Grocy product detail or local |

The landing pages render server-side with Jinja2 templates (already in use for `/healthz`-like pages) — no HTMX/JS this phase. Just enough to confirm "scan worked".

## Pydantic schemas

New files in `backend/app/schemas/`:

- `printer.py` — `PrinterRead`, `PrinterStatus`, `PrinterCreate` (deferred to Phase 7)
- `template.py` — `TemplateRead` (already used; extend if needed)
- `preset.py` — `PresetRead` (Phase 7 mostly, but `JobRead.preset_id` references it)
- `job.py` — `JobRead`, `JobCreate` (for `POST /print` extension)
- `lookup.py` — `LookupResult` (existing service already returns a typed dict; wrap it)
- `webhook.py` — `SpoolmanWebhookPayload`, `GrocyWebhookPayload`, `WebhookAcceptedResponse`
- `errors.py` — `ProblemDetail` (RFC 7807 — adopt for consistent error shape)

All `*Read` schemas use `model_config = ConfigDict(from_attributes=True)` so they hydrate from SQLModel rows.

## OpenAPI tags + metadata

Each `APIRouter` is created with:

```python
router = APIRouter(prefix="/api/printers", tags=["printers"])
```

The FastAPI app declares the tags up front in `main.py` with descriptions and external doc links. Tag names: `printers`, `templates`, `jobs`, `lookup`, `webhooks`, `qr-landing`, `system` (healthz keeps the system tag from Phase 4).

## Webhook API-key middleware

New file `backend/app/api/dependencies/webhook_auth.py`:

```python
async def require_webhook_key(
    x_api_key: str = Header(...),
) -> None:
    expected = os.environ.get("LABEL_HUB_WEBHOOK_API_KEY")
    if not expected:
        raise HTTPException(503, "Webhook auth not configured")
    if not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(401, "Invalid API key")
```

Mounted via `Depends(require_webhook_key)` on the webhook routes only. The webhook endpoints are the only ones with auth this phase; everything else is open behind Pangolin SSO at the proxy layer.

## Error mapping

`backend/app/api/error_handlers.py` registers FastAPI exception handlers:

```python
@app.exception_handler(PrinterOfflineError)
async def printer_offline_handler(request, exc):
    return JSONResponse(status_code=503, content=ProblemDetail(...))
```

Mappings:

| Service exception | HTTP | ProblemDetail.type |
|---|---|---|
| `PrinterOfflineError` | 503 | `printer-offline` |
| `TapeMismatchError` | 409 | `tape-mismatch` |
| `TapeEmptyError` | 409 | `tape-empty` |
| `PrinterCoverOpenError` | 409 | `printer-cover-open` |
| `TemplateNotFoundError` | 404 | `template-not-found` |
| `AppLookupNotFoundError` | 404 | `app-lookup-not-found` |
| `InvalidJobStateError` (from Phase 5 jobs repo `ValueError`) | 409 | `invalid-job-state` |

Existing `print.py` handlers already do most of this. The exception-handler approach centralises it so new routes don't have to repeat the mapping.

## Test strategy

Three test layers:

1. **Unit per router** (`backend/tests/unit/api/test_<router>_routes.py`) — calls the route function directly via `TestClient`, asserts response shape + status code. One file per router (already the pattern for `print.py`).
2. **Integration** (`backend/tests/integration/test_phase6a_endpoints.py`) — spins up the full FastAPI app + lifespan + in-memory DB; runs through a representative scenario for each aggregate (list, get, mutate, list again).
3. **OpenAPI schema test** (`backend/tests/api/test_openapi_completeness.py`) — asserts every route has a tag, every response model has a `title`, every parameter has a `description`. Acts as the API-quality gate analogous to the mcp-dockhand description audit.

Coverage target: 80% across the new files (matches the existing `--cov-fail-under=80` from the pytest config).

## Quality criteria

- **C1** All 20 endpoints implemented and wired to the DB layer from Phase 5.
- **C2** Pydantic schemas in `backend/app/schemas/` for every request/response shape (no inline `dict` returns).
- **C3** Every endpoint has an OpenAPI tag, summary, and Pydantic response_model.
- **C4** Webhook routes require valid `X-API-Key` header; missing or wrong → 401.
- **C5** Brother-error exceptions map to RFC 7807 ProblemDetail responses with appropriate HTTP status.
- **C6** Coverage ≥80% on new files.

## Risk and rollback

- **Risk:** breaking the existing `/api/print/...` route contract. Mitigation: the existing route stays at the same URL; Pydantic schema for its response stays compatible (additive only).
- **Risk:** webhook routes accept requests without the key in development. Mitigation: `LABEL_HUB_WEBHOOK_API_KEY` env-required; missing key returns 503 (not 401) so the operator gets a clear error.
- **Rollback:** single feature branch; revert merge commit restores Phase 5 state.

## Acceptance criteria

1. All 20 endpoints implemented + accessible via the FastAPI app.
2. `GET /openapi.json` returns a valid OpenAPI 3.1 document with all routes tagged.
3. Webhook routes return 401 without `X-API-Key`, 401 with wrong key, 202 with right key.
4. `pytest` passes; `mypy --strict app` clean; `ruff check` + `ruff format --check` clean.
5. Coverage ≥80% on new files (CI gate already in place).
6. `alembic check` still clean (no new tables this phase).
7. PR body summarises endpoints per aggregate and references issue #18.

## References

- Issue #18 (this work — REST + OpenAPI subset)
- Issue #14 (SSE — split out as Phase 6b, separate PR)
- Master-Tracking #22 (Phase 6)
- ADR 0011 (OpenAPI as API contract)
- Phase 5 PR #63 / commit `806076f` (DB layer this phase consumes)
- Existing routes: `backend/app/api/routes/print.py`
