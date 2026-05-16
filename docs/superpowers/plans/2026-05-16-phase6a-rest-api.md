# Phase 6a — REST API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax. Each task = one commit.

**Goal:** Implement the 21 REST endpoints (printers: 7, templates: 1, jobs: 6, lookup: 1, webhooks: 2, qr-landing: 4) from `docs/superpowers/specs/2026-05-16-phase6a-rest-api-design.md` (commit `2e038d3`), wired to the Phase 5 DB layer (PR #63, commit `806076f` on `main`).

**Architecture:** Six new files under `backend/app/api/routes/` (one per aggregate), Pydantic schemas under `backend/app/schemas/`, FastAPI exception handlers in `backend/app/api/error_handlers.py`, webhook API-key dependency in `backend/app/api/dependencies/webhook_auth.py`. Per-router tests in `backend/tests/unit/api/` plus an OpenAPI completeness gate.

**Tech Stack:** FastAPI + Pydantic v2 + SQLModel + aiosqlite (all already deps).

**Tracking:** Issue #18 (per `Refs #18` in every commit body).

---

## Conventions

- Conventional Commits scope from the commitlint enum. Most commits use `api`. The error-handler commit uses `api`. Test-only commits use `tests` (e.g. the OpenAPI completeness gate).
- header-max-length 120 per the relaxed config (PR #60).
- Every commit body ends with `Refs #18`.
- **No** `Co-Authored-By: Claude` anywhere.
- TDD-strict per task: failing test → impl → green → commit.
- Subagents do NOT push. Orchestrator handles push + PR creation.
- `git commit` runs under the repo's normal git config — the orchestrator handles the override author when needed (subagents inherit the orchestrator's git config). Contributors should NOT hardcode any specific name/email in commit example snippets; use `<your-name>` / `<your-email>` placeholders if a literal example is needed.

---

## File structure (target state)

```
backend/
├── app/
│   ├── api/
│   │   ├── dependencies/
│   │   │   ├── __init__.py
│   │   │   └── webhook_auth.py            # NEW
│   │   ├── error_handlers.py              # NEW
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── print.py                   # MODIFIED (additive only)
│   │       ├── printers.py                # NEW (7 endpoints)
│   │       ├── templates.py               # NEW (1 endpoint)
│   │       ├── jobs.py                    # NEW (6 endpoints)
│   │       ├── lookup.py                  # NEW (1 endpoint)
│   │       ├── webhooks.py                # NEW (2 endpoints)
│   │       └── qr.py                      # NEW (4 endpoints + Jinja templates)
│   ├── schemas/
│   │   ├── __init__.py                    # MODIFIED (re-export new)
│   │   ├── printer.py                     # NEW
│   │   ├── job.py                         # NEW (or extend existing)
│   │   ├── lookup.py                      # NEW
│   │   ├── webhook.py                     # NEW
│   │   ├── problem.py                     # NEW (RFC 7807)
│   │   └── ...existing...
│   └── main.py                            # MODIFIED (mount new routers, exception handlers)
└── tests/
    ├── unit/api/
    │   ├── test_printers_routes.py        # NEW
    │   ├── test_templates_routes.py       # NEW
    │   ├── test_jobs_routes.py            # NEW
    │   ├── test_lookup_routes.py          # NEW
    │   ├── test_webhooks_routes.py        # NEW
    │   └── test_qr_routes.py              # NEW
    └── api/
        └── test_openapi_completeness.py   # NEW
```

---

## Task 0: Shared scaffolding (schemas + error handler + auth dep)

**Files:**
- Create: `backend/app/schemas/problem.py` — RFC 7807 ProblemDetail
- Create: `backend/app/api/error_handlers.py` — exception handlers + registration helper
- Create: `backend/app/api/dependencies/__init__.py` + `webhook_auth.py`
- Modify: `backend/app/main.py` — register exception handlers (lifespan stays from Phase 5)
- Create: `backend/tests/unit/api/test_error_handlers.py`
- Create: `backend/tests/unit/api/test_webhook_auth.py`

- [ ] **Step 1: ProblemDetail schema**

```python
# backend/app/schemas/problem.py
from pydantic import BaseModel, Field


class ProblemDetail(BaseModel):
    """RFC 7807 Problem Details object."""
    type: str = Field(default="about:blank", description="URI reference identifying the problem type")
    title: str = Field(description="Short human-readable summary of the problem")
    status: int = Field(description="HTTP status code")
    detail: str | None = Field(default=None, description="Human-readable explanation specific to this occurrence")
    instance: str | None = Field(default=None, description="URI reference identifying this specific occurrence")
    extensions: dict[str, object] = Field(default_factory=dict, description="Additional problem-type-specific fields")
```

- [ ] **Step 2: Error handlers**

```python
# backend/app/api/error_handlers.py
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.services.errors import (
    PrinterOfflineError, TapeMismatchError, TapeEmptyError,
    PrinterCoverOpenError, TemplateNotFoundError, AppLookupNotFoundError,
)
from app.schemas.problem import ProblemDetail


_MAPPING = {
    PrinterOfflineError: (503, "printer-offline"),
    TapeMismatchError: (409, "tape-mismatch"),
    TapeEmptyError: (409, "tape-empty"),
    PrinterCoverOpenError: (409, "printer-cover-open"),
    TemplateNotFoundError: (404, "template-not-found"),
    AppLookupNotFoundError: (404, "app-lookup-not-found"),
}

# Note: invalid job state transitions raise plain ValueError from the Phase 5
# jobs repository. ValueError is too broad to catch globally — handle it at
# the route level in jobs.py with a try/except → HTTPException(409, ...).


def register_error_handlers(app: FastAPI) -> None:
    for exc_class, (status, problem_type) in _MAPPING.items():
        app.add_exception_handler(exc_class, _make_handler(status, problem_type))


def _make_handler(status: int, problem_type: str):
    async def handler(_request: Request, exc: Exception) -> JSONResponse:
        problem = ProblemDetail(
            type=problem_type,
            title=problem_type.replace("-", " ").title(),
            status=status,
            detail=str(exc),
        )
        return JSONResponse(status_code=status, content=problem.model_dump(exclude_none=True))
    return handler
```

- [ ] **Step 3: Webhook auth dep**

```python
# backend/app/api/dependencies/webhook_auth.py
import hmac
from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings


async def require_webhook_key(
    x_api_key: str = Header(..., alias="X-API-Key"),
    settings: Settings = Depends(get_settings),
) -> None:
    expected = settings.webhook_api_key
    if not expected:
        # config.py already validates length >=32 when the field is set;
        # this branch only fires when the env var is genuinely unset.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook auth not configured (PRINTER_HUB_WEBHOOK_API_KEY missing)",
        )
    if not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
```

`Settings` is a cached pydantic-settings object (see `backend/app/config.py`) — `get_settings()` is `@lru_cache`-decorated so the env var is read once at startup, not on every request.

- [ ] **Step 4: Wire `register_error_handlers(app)` in `main.py`** after the lifespan call

- [ ] **Step 5: Tests for both**

```python
# test_error_handlers.py
@pytest.mark.asyncio
async def test_printer_offline_becomes_503_problem_detail():
    # Build a tiny app with one route that raises, register handlers, hit it
    ...

# test_webhook_auth.py
async def test_missing_key_returns_503_when_unconfigured(monkeypatch):
    monkeypatch.delenv("PRINTER_HUB_WEBHOOK_API_KEY", raising=False)
    ...

async def test_wrong_key_returns_401(monkeypatch):
    monkeypatch.setenv("PRINTER_HUB_WEBHOOK_API_KEY", "correct-key")
    ...
```

- [ ] **Step 6: Run + commit**

```
cd backend && pytest tests/unit/api/ -v
ruff check && ruff format --check && mypy app
```

Commit:

```
feat(api): shared REST scaffolding — ProblemDetail, error handlers, webhook-key dep

RFC 7807 ProblemDetail schema for consistent error responses across
the new Phase 6a routes. Exception handlers map service-layer errors
(PrinterOfflineError, TapeMismatchError, etc.) to appropriate HTTP
status codes with ProblemDetail bodies. Webhook routes will guard
on the X-API-Key header via require_webhook_key dependency.

Refs #18
```

---

## Task 1: Printer routes (7 endpoints)

**Files:**
- Create: `backend/app/schemas/printer.py` (`PrinterRead`, `PrinterStatus`)
- Create: `backend/app/api/routes/printers.py` (6 routes)
- Modify: `backend/app/main.py` (mount the router)
- Create: `backend/tests/unit/api/test_printers_routes.py`

Endpoints:

| Method | Path | Handler |
|---|---|---|
| GET | `/api/printers` | `list_printers(session: Depends(get_session))` |
| GET | `/api/printers/{id}/status` | `get_printer_status(...)` — force fresh probe |
| GET | `/api/printers/{id}/tape` | `get_printer_tape(...)` |
| GET | `/api/printers/{id}/queue` | `get_printer_queue(...)` — jobs WHERE printer_id AND state IN (queued, printing) |
| POST | `/api/printers/{id}/pause` | `pause_printer(...)` — printer_state.paused=true |
| POST | `/api/printers/{id}/resume` | `resume_printer(...)` |
| POST | `/api/printers/{id}/queue/clear` | `clear_printer_queue(...)` — bulk mark_cancelled |

7 routes counting the queue/clear. Spec listed 6; the queue/clear is the 7th.

- [ ] **Step 1: Schemas**

```python
# backend/app/schemas/printer.py
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class PrinterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    model: str
    backend: str
    connection: dict[str, object]
    enabled: bool
    paused: bool = False  # joined from printer_state
    created_at: datetime
    updated_at: datetime


class PrinterStatus(BaseModel):
    printer_id: UUID
    online: bool
    tape_loaded: str | None  # e.g. "12mm laminated black/clear"
    error_state: str | None
    captured_at: datetime
```

- [ ] **Step 2: Routes (router + handlers)**

Implement each handler using:
- `app.repositories.printers` for the DB layer
- `app.repositories.printer_state` for the paused flag
- `app.repositories.printer_status_cache` for the status read
- `app.repositories.jobs` for the queue read

For the `force fresh probe` endpoint, the actual SNMP probe is in `app.services.status_block` — it parses the Brother PT-series 32-byte status block per the spec in `docs/research/2026-05-10-brother-pt-raster-extract.md` (ESC i S command; see the PT raster reference under §"Status Information"). The current `status_block` helpers are synchronous (network I/O over UDP/SNMP); wrap any call from the async route handler in `asyncio.to_thread(...)` so the FastAPI event loop is not blocked. After parsing, upsert the result into `printer_status_cache` via the Phase 5 repo.

- [ ] **Step 3: Mount router in main.py**

```python
from app.api.routes import printers as printers_routes
app.include_router(printers_routes.router)
```

- [ ] **Step 4: Tests**

7 unit tests, one per endpoint. Use `TestClient` + an override of `get_session` to inject the in-memory engine from the existing test conftest pattern.

- [ ] **Step 5: Run + commit**

```
feat(api): printer routes — list, status, tape, queue, pause/resume

Six DB-backed printer endpoints. /api/printers joins printer_state
for the paused flag. /api/printers/{id}/status forces a fresh ESC i S
probe and writes back to printer_status_cache. queue/clear bulk-
cancels every queued job for the printer.

Refs #18
```

---

## Task 2: Templates routes (1 endpoint)

**Files:**
- Create: `backend/app/api/routes/templates.py`
- Create: `backend/tests/unit/api/test_templates_routes.py`
- Modify: `backend/app/schemas/template.py` (if needed — likely exists from Phase 4)

Endpoint:

```
GET /api/templates?app=<optional> → list[TemplateRead]
```

- [ ] **Step 1: Confirm TemplateRead schema exists** — if not, create
- [ ] **Step 2: Router + handler** — `templates_repo.list_all`, filtered by `app` query
- [ ] **Step 3: Mount + 2 tests** (filtered + unfiltered)
- [ ] **Step 4: Commit**

```
feat(api): GET /api/templates with optional app filter

Refs #18
```

---

## Task 3: Jobs routes (6 endpoints)

**Files:**
- Create: `backend/app/schemas/job.py`
- Create: `backend/app/api/routes/jobs.py`
- Create: `backend/tests/unit/api/test_jobs_routes.py`

Endpoints:

| Method | Path | Notes |
|---|---|---|
| GET | `/api/jobs?state=&printer_id=&since=&limit=50` | filter + paginate |
| GET | `/api/jobs/{id}` | single |
| POST | `/api/jobs/{id}/cancel` | **only QUEUED jobs** — handler pre-checks state and returns 409 ProblemDetail for PRINTING (mid-print abort is unsafe over TCP/9100). Calls `mark_cancelled` after the check. |
| POST | `/api/jobs/{id}/pause` | 501 placeholder (returns ProblemDetail, status 501) |
| POST | `/api/jobs/{id}/resume` | 501 placeholder |
| POST | `/api/jobs/{id}/retry` | clone the failed job → new queued |

- [ ] **Step 1: JobRead + JobFilter schemas**
- [ ] **Step 2: Handlers**
- [ ] **Step 3: 8 tests** (read filtered/unfiltered + each mutation incl. the 501 placeholders)
- [ ] **Step 4: Commit**

```
feat(api): jobs routes — list/get + cancel/retry, pause/resume placeholders

GET /api/jobs supports state, printer_id, since, limit query filters.
POST /api/jobs/{id}/cancel uses Phase 5 mark_cancelled. POST .../retry
clones the failed job spec into a new queued job (UUID, fresh state).
pause/resume return 501 with ProblemDetail — placeholders so the
OpenAPI shape is stable for the Phase 7 UI to wire to.

Refs #18
```

---

## Task 4: Lookup route (1 endpoint)

**Files:**
- Create: `backend/app/schemas/lookup.py`
- Create: `backend/app/api/routes/lookup.py`
- Create: `backend/tests/unit/api/test_lookup_routes.py`

Wraps existing `app.services.lookup_service.AppLookupService`.

- [ ] Schema, route, 3 tests (success + not-found + invalid app), commit

```
feat(api): GET /api/lookup/{app}/{id} wraps AppLookupService

Refs #18
```

---

## Task 5: Webhook routes (2 endpoints)

**Files:**
- Create: `backend/app/schemas/webhook.py`
- Create: `backend/app/api/routes/webhooks.py`
- Create: `backend/tests/unit/api/test_webhooks_routes.py`

Both routes use `Depends(require_webhook_key)`.

- [ ] **Step 1: Webhook payload schemas** — `SpoolmanWebhookPayload`, `GrocyWebhookPayload`, `WebhookAcceptedResponse`
- [ ] **Step 2: Handlers** — payload validation; call `PrintQueue.enqueue` (existing service); return `{"job_id": ...}`
- [ ] **Step 3: 6 tests**: each route × {missing key, wrong key, valid call, malformed payload}
- [ ] **Step 4: Commit**

```
feat(api): webhook routes for Spoolman + Grocy with API-key auth

Refs #18
```

---

## Task 6: QR landing pages (4 endpoints, Jinja templates)

**Files:**
- Create: `backend/app/api/routes/qr.py`
- Create: `backend/app/templates/qr/{loc,asset,spool,product}.html` (Jinja2)
- Create: `backend/tests/unit/api/test_qr_routes.py`

Each endpoint:
- Calls `AppLookupService` (already there)
- Renders a Jinja2 template (minimal: title, name, integration link)
- Returns `HTMLResponse`

- [ ] **Step 1: 4 templates** — bare bones, no HTMX yet
- [ ] **Step 2: Router with 4 GET handlers**
- [ ] **Step 3: 8 tests** — happy path + 404 per route
- [ ] **Step 4: Commit**

```
feat(api): QR landing pages — /loc /asset /spool /product

Plain Jinja2 HTML — Phase 7 layers HTMX on top.

Refs #18
```

---

## Task 7: OpenAPI completeness test

**Files:**
- Create: `backend/tests/api/test_openapi_completeness.py`

Asserts every route in `/openapi.json`:

- has a tag
- has a summary
- has a response_model (or explicit content schema)
- every parameter has a description

This is the API-quality gate analogous to the mcp-dockhand description audit.

- [ ] **Step 1: Test**

```python
import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.mark.parametrize("path,methods", _routes_from_openapi())
def test_every_route_has_tag_and_summary(path, methods):
    ...
```

- [ ] **Step 2: Run — expect every new route passes** (existing print.py routes may need a sweep)

- [ ] **Step 3: Commit**

```
test(api): OpenAPI completeness gate — tag/summary/response_model on every route

Refs #18
```

---

## Task 8: Final verification + PR

Orchestrator-run.

- [ ] `pytest` full suite — expect 410+ passes (Phase 5's 384 + ~25 new)
- [ ] `mypy --strict app` clean
- [ ] `ruff check` + `ruff format --check` clean
- [ ] `alembic check` still clean (no new tables this phase)
- [ ] `git log main..HEAD --oneline` — expect 9 commits (Task 0 + 7 feature commits + test gate)
- [ ] Push + open PR with body summarising endpoints per aggregate

---

## Self-review

**Spec coverage:** every section of `2026-05-16-phase6a-rest-api-design.md` has a task. The non-goals (SSE, HTMX, template CRUD, user auth) are explicitly left for later phases.

**Placeholder scan:** no "TBD" / "Similar to Task N" — each task names files, schemas, and handler logic.

**Type consistency:** `PrinterRead`, `JobRead`, etc. are referenced consistently across tasks.

---

## Execution

Subagent-driven (recommended): one implementer per task (9 total), spec-compliance + code-quality reviewer between tasks. Wall-clock ~2.5h based on Phase 5 pace.
