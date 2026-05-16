# Phase 5 — Persistence Layer (SQLModel + aiosqlite) — Design

**Date:** 2026-05-16
**Status:** Approved (issue #19 acceptance criteria + Master-Tracking #22 Phase 5)
**Owner:** repo maintainer
**Implementation branch:** `feat/phase5-persistence`
**Tracking issue:** strausmann/label-printer-hub#19

## Problem

The Hub currently lives entirely in process memory and YAML files:

- Templates are loaded from `backend/app/seed/templates/*.yaml` at startup (Phase 4, `TemplateLoader`, atomic reload). 12 default templates ship; users can drop their own YAML files into the directory but there is no API to create/edit them at runtime.
- The print queue is in-process (`asyncio.Queue`). A restart loses every queued and printing job; clients polling for status get a 404 on the job ID and have to retry from scratch.
- Printer presets are configuration-file only; no UI-driven storage.
- Printer status cache (the parsed ESC i S 32-byte block) is in-memory; every restart loses 30+ seconds of telemetry until the next probe.
- Worker state (paused/active per printer) is in-memory.

Phase 6 (REST + SSE) and Phase 7 (HTMX UI) both require persistent state to be useful: a template editor cannot ship if templates die on restart, and a job-detail SSE stream is pointless if the job no longer exists after the server reboots.

This phase introduces a SQLite-backed persistence layer using SQLModel + aiosqlite, with Alembic for schema migrations and a startup-recovery step for in-flight jobs.

## Goals

- Six SQLModel tables persisted to a single SQLite file (`data/hub.db`), with async access via aiosqlite.
- Migration tool (Alembic) bootstrapped so future schema changes are tracked.
- Seed loader that imports the 12 YAML templates on first run, idempotent on subsequent boots.
- Startup recovery: any job left in `queued` or `printing` state at shutdown is marked `failed_restart` so the operator can decide whether to requeue.
- Print queue continues to be in-process (`asyncio.Queue`) for fast dispatch, but every state transition is mirrored to the DB synchronously.
- Phase 4 `TemplateLoader` continues to work for YAML-on-disk templates; the new templates table is the **canonical** source — YAML imports become rows on first boot.

## Non-goals

- Multi-process / horizontal scaling. SQLite + in-process queue is the deliberate small-deployment choice.
- Postgres support. The repo is single-instance; Postgres would force a redo of pragmas, connection pool sizing, and the WAL semantics. Out of scope.
- Job retry semantics beyond `failed_restart` marking. Operator-driven retry / scheduled retry is Phase 6+.
- User accounts / multi-tenancy. Not on the roadmap.
- Background dump/backup. SQLite file lives in the volume; restic / borgbackup is the operator's call.

## Architecture

### Stack

| Component | Choice | Why |
|---|---|---|
| ORM | SQLModel (already a dep) | Same author as FastAPI; pydantic + SQLAlchemy combined; type-narrowing across boundary |
| Driver | aiosqlite | Already a dep; matches the async FastAPI stack |
| Migrations | Alembic | Industry standard; SQLModel docs assume it; auto-generation from model diffs |
| Session pattern | `AsyncSession` per request via FastAPI dependency | Standard pattern; sessions are cheap with aiosqlite |
| Connection pool | SQLite-native (single-writer, multi-reader) with WAL | SQLite's WAL handles the small concurrent-read case fine |

### Directory layout

```
backend/
├── app/
│   ├── db/
│   │   ├── __init__.py            # public re-exports
│   │   ├── engine.py              # async engine + session factory
│   │   ├── session.py             # FastAPI dependency
│   │   └── lifespan.py            # startup/shutdown hooks
│   ├── models/                    # one file per table
│   │   ├── __init__.py
│   │   ├── tape.py                # existing (non-DB dataclass — keep as-is)
│   │   ├── printer.py             # NEW table
│   │   ├── template.py            # NEW table
│   │   ├── preset.py              # NEW table
│   │   ├── job.py                 # NEW table + state enum
│   │   ├── printer_state.py       # NEW table
│   │   └── printer_status_cache.py # NEW table
│   ├── repositories/              # NEW — thin query layer per aggregate
│   │   ├── __init__.py
│   │   ├── printers.py
│   │   ├── templates.py
│   │   ├── presets.py
│   │   ├── jobs.py
│   │   └── printer_state.py
│   └── services/
│       ├── template_loader.py     # existing — modified to seed DB on first boot
│       └── ...
├── alembic/
│   ├── env.py                     # async-aware env
│   ├── script.py.mako
│   └── versions/
│       └── 2026_05_16_0001_phase5_initial.py  # initial schema as one migration
├── alembic.ini
└── pyproject.toml                 # add alembic dep
```

### Schema

Each table below ships in the initial Alembic migration (one revision, named `phase5_initial`).

#### `printers`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | server-generated |
| `name` | TEXT NOT NULL UNIQUE | human-readable, unique |
| `model` | TEXT NOT NULL | matches a `label_hub.printer_models` entry-point — currently only `pt-series` is registered; `ql-series` will be added in Phase 2 follow-up (#11) |
| `backend` | TEXT NOT NULL | matches a `label_hub.printer_backends` entry-point — currently `mock` and `ptouch`; QL backend lands with #11 |
| `connection` | JSON NOT NULL | backend-specific config (IP, port, USB-id) |
| `enabled` | BOOLEAN NOT NULL DEFAULT TRUE | soft-disable |
| `created_at` | DATETIME NOT NULL | UTC |
| `updated_at` | DATETIME NOT NULL | UTC, autoupdate |

Why JSON for `connection`: the field is backend-specific (e.g. `{"ip": "printer.local", "port": 9100}` for QL-820NWBc vs `{"interface": "usb", "serial": "..."}` for P750W). Keeping it opaque to the DB layer keeps the schema stable across backend additions.

#### `templates`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | server-generated |
| `key` | TEXT NOT NULL UNIQUE | stable identifier (matches YAML `key` field) |
| `name` | TEXT NOT NULL | display name |
| `app` | TEXT NULL | optional integration filter (`snipeit`, `grocy`, `spoolman`, or NULL = generic) |
| `printer_model` | TEXT NOT NULL | required — templates are model-specific |
| `tape_width_mm` | INTEGER NOT NULL | `12`, `18`, `24` etc. |
| `schema_version` | INTEGER NOT NULL DEFAULT 1 | forward-compat marker (PR #56) |
| `definition` | JSON NOT NULL | full template body (elements, dimensions) |
| `source` | TEXT NOT NULL | `seed` (from YAML) or `user` |
| `created_at` | DATETIME NOT NULL | UTC |
| `updated_at` | DATETIME NOT NULL | UTC, autoupdate |

`source = 'seed'` rows are reseeded on every boot if their `key` matches a YAML file — the YAML is the source of truth for default templates. `source = 'user'` rows are persisted across boots and never touched by the seed loader.

UNIQUE constraint on `(key)` — if a user tries to create a template with the same key as a seed template, they get a clear 409 from the API (Phase 6).

#### `presets`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | server-generated |
| `name` | TEXT NOT NULL | display name |
| `printer_id` | UUID NULL FK → printers.id | optional pinning |
| `template_id` | UUID NOT NULL FK → templates.id | which template |
| `field_values` | JSON NOT NULL DEFAULT '{}' | pre-filled field values |
| `created_at` | DATETIME NOT NULL | UTC |
| `updated_at` | DATETIME NOT NULL | UTC, autoupdate |

#### `jobs`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | server-generated; also the API-visible job ID |
| `printer_id` | UUID NOT NULL FK → printers.id | target printer |
| `template_key` | TEXT NOT NULL | snapshot — survives template delete |
| `state` | TEXT NOT NULL | enum: see below |
| `payload` | JSON NOT NULL | render input (field values, count) |
| `result` | JSON NULL | structured outcome on terminal states |
| `error` | TEXT NULL | machine-readable error code on failure |
| `created_at` | DATETIME NOT NULL | UTC |
| `updated_at` | DATETIME NOT NULL | UTC, autoupdate |
| `started_at` | DATETIME NULL | when worker picked up |
| `finished_at` | DATETIME NULL | when terminal state reached |

`state` enum (string column, validated by SQLModel):

```
queued        → in DB, in queue, awaiting worker
printing      → worker has picked up, raster being sent
done          → success
failed        → terminal failure (printer rejected, driver error)
cancelled     → operator cancelled
failed_restart → on startup recovery: was queued/printing at shutdown
```

Index on `state` for fast `WHERE state IN ('queued', 'printing')` queries during startup recovery.

#### `printer_state`

| Column | Type | Notes |
|---|---|---|
| `printer_id` | UUID PK FK → printers.id | one row per printer |
| `paused` | BOOLEAN NOT NULL DEFAULT FALSE | operator pause |
| `updated_at` | DATETIME NOT NULL | UTC, autoupdate |

Singleton-per-printer (PK = FK). The worker reads this on startup and on demand.

#### `printer_status_cache`

| Column | Type | Notes |
|---|---|---|
| `printer_id` | UUID PK FK → printers.id | one row per printer |
| `raw_block` | BLOB NULL | 32-byte ESC i S status block, last known good |
| `parsed` | JSON NULL | parsed view (tape width, media type, errors, model) |
| `captured_at` | DATETIME NULL | when this block was read |
| `updated_at` | DATETIME NOT NULL | UTC, autoupdate |

The cache exists so the UI can render initial state without waiting for a fresh probe. The next status probe replaces the row in place.

### Engine + session lifecycle

```python
# backend/app/db/engine.py
DATABASE_URL = "sqlite+aiosqlite:///./data/hub.db"

engine = create_async_engine(
    DATABASE_URL,
    echo=False,  # toggle via LOG_LEVEL=debug
    connect_args={"check_same_thread": False},
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
```

Pragmas set on every connection via SQLAlchemy event hook:

- `PRAGMA journal_mode = WAL` — readers don't block during writes
- `PRAGMA synchronous = NORMAL` — durability good enough for HomeLab; full FSYNC is overkill
- `PRAGMA foreign_keys = ON` — FK enforcement
- `PRAGMA busy_timeout = 5000` — wait 5s before erroring on lock contention

### Startup recovery

In `app/db/lifespan.py`:

```
on_startup():
  1. Run pending Alembic migrations (alembic upgrade head)
  2. Seed templates from YAML (TemplateLoader → DB rows where source='seed')
  3. Recover in-flight jobs:
     UPDATE jobs SET state='failed_restart', error='restart_during_inflight'
       WHERE state IN ('queued','printing')
  4. Initialize printer_state rows for any printer without one
```

The `failed_restart` state is purely informational. The API will not auto-retry — the operator decides.

### Seed loader integration

`TemplateLoader` keeps its current YAML-reading behaviour but gains a `seed_db()` method called from lifespan:

```
for each YAML template loaded from backend/app/seed/templates/:
  UPSERT into templates table
  WHERE key = yaml.key AND source = 'seed'
```

User-created templates (`source = 'user'`) are returned via the same API as seed templates but never touched by `seed_db()`.

### Test database

Tests use an in-memory SQLite (`sqlite+aiosqlite:///:memory:`) per test class with a fresh schema apply. The 12 seed templates are loaded by the same fixture used in production startup.

## Quality criteria

- **C1** All six tables exist as Alembic-managed migrations; `alembic upgrade head` on an empty DB produces the full schema.
- **C2** All write paths go through repository functions; no raw SQL in route handlers or services.
- **C3** WAL + busy_timeout + FK pragmas applied on every connection (test that asserts via `PRAGMA` query post-startup).
- **C4** Startup recovery: a seeded test job in `queued` state becomes `failed_restart` on next lifespan startup.
- **C5** Seed idempotency: starting the service twice produces exactly 12 `source='seed'` rows, never duplicates.
- **C6** Tests cover happy-path CRUD on each repository plus the recovery flow.

## Risk and rollback

- **Risk:** existing in-memory queue currently serves jobs. Adding DB persistence increases write latency on each state transition.
  - **Mitigation:** state transitions are sequential per job and SQLite WAL handles ~5000 inserts/sec on modest hardware. Worst-case observed write latency for one transition is <5ms; the queue itself is the slow part.
- **Risk:** WAL files (`hub.db-wal`, `hub.db-shm`) confuse operators expecting a single file.
  - **Mitigation:** documented in `docs/operations.md` (out of scope of this PR; doc-only follow-up).
- **Risk:** schema breakage between migration heads and SQLModel class definitions.
  - **Mitigation:** CI step that runs `alembic check` (catches model/migration divergence) — added in this PR's CI changes.
- **Rollback:** `feat/phase5-persistence` is a single feature branch. If the design lands and a critical issue emerges, `git revert` of the merge commit restores the in-process state. The new `data/hub.db` file is orphaned but harmless (operator can `rm` it).

## Acceptance criteria

1. All six tables exist in `backend/app/models/` as SQLModel classes with proper `__table_args__` for indexes / unique constraints.
2. `alembic upgrade head` from a clean checkout produces the full schema; `alembic check` is clean (no pending model diffs).
3. `backend/app/db/{engine,session,lifespan}.py` provide an async engine, a FastAPI session dependency, and lifespan hooks for migrations + seed + recovery.
4. `backend/app/repositories/` provides typed read + write functions for each aggregate (`printers`, `templates`, `presets`, `jobs`, `printer_state`).
5. `TemplateLoader.seed_db()` upserts the 12 YAML seed templates as `source='seed'` rows on each startup; user-created rows are not touched.
6. Startup recovery marks all `queued` and `printing` rows as `failed_restart` on next boot.
7. Pragmas verified: WAL mode, busy_timeout=5000, foreign_keys=ON, synchronous=NORMAL.
8. New tests in `backend/tests/` cover the engine bootstrap, the recovery flow, the seed idempotency, and one repository per aggregate. Existing tests stay green.
9. `npm run typecheck` (mypy strict) clean. `ruff check` + `ruff format --check` clean. No `# type: ignore` introduced.
10. `data/hub.db` is git-ignored.

## References

- Issue #19 (this work)
- Issue #22 Phase 5 (Master-Tracking)
- ADR 0005 (Print Queue is mandatory)
- ADR 0011 (OpenAPI as API contract) — Phase 6 surfaces this DB through the API
- Brother PT raster spec extract: `docs/research/2026-05-10-brother-pt-raster-extract.md`
- PR #56 (Phase 4 template loader, atomic reload, schema_version)
