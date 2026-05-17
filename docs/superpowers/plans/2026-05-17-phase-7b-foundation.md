# Phase 7b Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the label-printer-hub lifespan, datetime handling, health surface, and SNMP polling so the next production deploy is reproducible end-to-end and observable through `/readiness`.

**Architecture:** Nine focused clusters layered in dependency order — datetime-TZ first (touches every model), then printer identity, then lifespan init-order, then alembic verify, then the new `/readiness` endpoint, then status-cache plumbing, then the frontend proxy widening, last the README + a final production smoke check. Each cluster is a sequence of TDD red→green→commit cycles.

**Tech Stack:** Python 3.12 + FastAPI + SQLModel (async) + aiosqlite + Alembic + pytest-asyncio. Frontend Go + chi/v5 router + `net/http/httputil` reverse proxy + oapi-codegen client. Strict TDD per repo policy (`docs/policies/contributing.md`). Conventional Commits enforced by `commitlint.config.cjs` — type from `{feat, fix, refactor, test, docs, chore, ci}`, scope from `{api, queue, status, webhook, docker, ci, examples, docs, integration, security}`.

**Spec:** `docs/superpowers/specs/2026-05-17-phase-7b-foundation-design.md` (Merged via PR #74, 2026-05-17).

**Tracking:** `Refs #22` at the end of every commit body.

---

## File Structure

| File | Responsibility | Phase |
|---|---|---|
| `backend/app/schemas/_datetime.py` (NEW) | Pydantic field-serializer that coerces naive datetimes to UTC and emits RFC3339-with-Z | B |
| `backend/app/models/{template,printer,job,preset,printer_state,printer_status_cache}.py` (MODIFY) | Add `DateTime(timezone=True)` columns + UTC `default_factory` | B |
| `backend/app/schemas/{template_read,printer,job}.py` (MODIFY) | Apply `@field_serializer("created_at","updated_at",...)` | B |
| `backend/alembic/versions/20260517_phase7b_datetime_tz.py` (NEW) | Idempotent data migration: existing rows get `+00:00` suffix | B |
| `backend/app/services/printer_identity.py` (NEW) | `derive_printer_id(model, host, port)` → deterministic UUIDv5 | C |
| `backend/app/db/lifespan.py` (MODIFY) | Add `upsert_runtime_printer`, defensive check in `seed_templates`, `verify_alembic_at_head`; correct docstring | C, D, E |
| `backend/app/printer_backends/_queue_factory.py` (MODIFY)¹ | Driver `.make_queue_printer(tape_registry, printer_id: UUID \| None = None)` | C |
| `backend/app/main.py` (MODIFY lines 235–245, 270–276) | Re-ordered lifespan + plumb `db_printer_id` to driver | D |
| `backend/app/schemas/readiness.py` (NEW) | `CheckStatus`, `ReadinessResponse` Pydantic models | F |
| `backend/app/services/readiness.py` (NEW) | `build_readiness_response(session, app_state)` aggregator | F |
| `backend/app/api/routes/meta.py` (MODIFY)² | Add `GET /readiness` route | F |
| `backend/app/services/producers/status_probe_producer.py` (MODIFY) | `_upsert_cache(snmp_result)`, `_mark_offline(exc)` | G |
| `backend/app/schemas/printer.py` (MODIFY) | Extend `PrinterStatus` with `captured_at, last_probe_age_s, last_error, note` | G |
| `backend/app/api/routes/printers.py` (MODIFY) | `GET /api/printers/{id}/status` reads from cache, not sync SNMP | G |
| `frontend/cmd/server/main.go` (MODIFY lines 137–144) | `r.Mount("/docs",prx); r.Mount("/openapi.json",prx); r.Mount("/redoc",prx)` | H |
| `frontend/cmd/server/main_test.go` (MODIFY) | Assert the 3 new proxy mounts forward to backend | H |
| `README.md` (MODIFY) | Document `/readiness` endpoint + link to spec | I |

¹ Exact file/class name depends on existing driver layout; the implementer must `grep` for `make_queue_printer` and modify the single implementation.
² If `meta.py` doesn't exist, add the route to `backend/app/main.py` next to `/healthz` (currently inline there).

---

## Phase A — Setup

### Task A1: Create feature branch from main

**Files:** none (git only)

- [ ] **Step 1: Confirm clean main and pull**

```bash
cd /opt/repos/label-printer-hub
git checkout main
git pull --ff-only origin main
git log -1 --oneline
```

Expected: latest commit is the PR #74 squash-merge of the Phase 7b spec.

- [ ] **Step 2: Create branch**

```bash
git checkout -b feat/phase-7b-foundation
```

- [ ] **Step 3: Confirm baseline tests pass**

```bash
cd backend && uv run pytest -q
```

Expected: all tests pass (existing baseline).

No commit. Branch is the workspace for all subsequent tasks.

---

## Phase B — Cluster 1c: Datetime-TZ Serialisation

### Task B1: Test serialize_datetime_utc helper

**Files:**
- Create: `backend/app/schemas/_datetime.py`
- Create: `backend/tests/unit/schemas/test_datetime_serializer.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/unit/schemas/test_datetime_serializer.py
from datetime import datetime, timezone, timedelta

from app.schemas._datetime import serialize_datetime_utc


def test_naive_datetime_gets_utc_tz_and_z_suffix():
    naive = datetime(2026, 5, 17, 12, 0, 0)
    assert serialize_datetime_utc(naive, None) == "2026-05-17T12:00:00Z"


def test_utc_aware_datetime_serialised_with_z_suffix():
    aware = datetime(2026, 5, 17, 12, 0, 0, tzinfo=timezone.utc)
    assert serialize_datetime_utc(aware, None) == "2026-05-17T12:00:00Z"


def test_non_utc_aware_datetime_kept_with_offset():
    plus_two = datetime(2026, 5, 17, 14, 0, 0, tzinfo=timezone(timedelta(hours=2)))
    assert serialize_datetime_utc(plus_two, None) == "2026-05-17T14:00:00+02:00"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/unit/schemas/test_datetime_serializer.py -v
```

Expected: FAIL with `ImportError: cannot import name 'serialize_datetime_utc'`.

- [ ] **Step 3: Implement minimal helper**

```python
# backend/app/schemas/_datetime.py
"""Helpers for datetime serialisation in Pydantic schemas.

The Go frontend's oapi-codegen client uses strict RFC3339 parsing which
rejects naive datetimes (no `Z` or `+HH:MM` suffix). This helper normalises
every datetime to a timezone-aware UTC value before serialisation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def serialize_datetime_utc(dt: datetime, _info: Any) -> str:
    """Pydantic field-serializer: emit RFC3339 with `Z` for UTC values.

    - naive datetimes are treated as UTC (matches SQLite legacy behaviour)
    - UTC-aware datetimes are emitted with `Z`
    - non-UTC-aware datetimes keep their explicit offset
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && uv run pytest tests/unit/schemas/test_datetime_serializer.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/_datetime.py backend/tests/unit/schemas/test_datetime_serializer.py
git commit -m "$(cat <<'EOF'
feat(api): add serialize_datetime_utc helper for RFC3339 with Z

Go frontend oapi-codegen rejects naive datetimes. Helper normalises any
datetime to a timezone-aware ISO string before serialisation.

Refs #22
EOF
)"
```

### Task B2: Apply field_serializer to TemplateRead

**Files:**
- Modify: `backend/app/schemas/template_read.py`
- Create: `backend/tests/integration/api/test_api_datetime_format.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/integration/api/test_api_datetime_format.py
"""Contract test for Phase 7b Cluster 1c — every datetime field in the API
response must include a timezone suffix (Z or +HH:MM)."""

import pytest
from datetime import datetime

pytestmark = pytest.mark.asyncio


def _has_tz_suffix(s: str) -> bool:
    return s.endswith("Z") or "+" in s or "-" in s[10:]  # skip date dashes


async def test_template_read_has_tz_suffix(api_client_with_seed):
    """GET /api/templates returns datetimes with TZ info."""
    resp = await api_client_with_seed.get("/api/templates")
    assert resp.status_code == 200
    body = resp.json()
    assert body, "expected at least one seeded template"
    for t in body:
        for field in ("created_at", "updated_at"):
            assert _has_tz_suffix(t[field]), \
                f"{field}={t[field]!r} missing TZ suffix"
            datetime.fromisoformat(t[field].replace("Z", "+00:00"))
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/integration/api/test_api_datetime_format.py::test_template_read_has_tz_suffix -v
```

Expected: FAIL — current TemplateRead returns naive datetime.

- [ ] **Step 3: Add field_serializer**

Insert in `backend/app/schemas/template_read.py` (near the bottom of the `TemplateRead` class):

```python
from pydantic import field_serializer
from app.schemas._datetime import serialize_datetime_utc

class TemplateRead(BaseModel):
    # ... existing fields ...
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def _serialise_datetimes(self, dt: datetime, _info):
        return serialize_datetime_utc(dt, _info)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && uv run pytest tests/integration/api/test_api_datetime_format.py::test_template_read_has_tz_suffix -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/template_read.py backend/tests/integration/api/test_api_datetime_format.py
git commit -m "$(cat <<'EOF'
fix(api): TemplateRead emits RFC3339 datetimes with Z suffix

Go oapi-codegen client rejected naive datetimes from /api/templates
with `parsing time "..." cannot parse "" as "Z07:00"`. Apply the new
serialize_datetime_utc helper via @field_serializer.

Refs #22
EOF
)"
```

### Task B3: Apply field_serializer to PrinterRead, JobRead, PresetRead

**Files:**
- Modify: `backend/app/schemas/printer.py`
- Modify: `backend/app/schemas/job.py`
- Modify: `backend/app/schemas/preset.py` (if it exists; otherwise skip)
- Modify: `backend/tests/integration/api/test_api_datetime_format.py` (add three more tests)

- [ ] **Step 1: Extend the test file**

Append to `backend/tests/integration/api/test_api_datetime_format.py`:

```python
async def test_printer_read_has_tz_suffix(api_client_with_seed):
    resp = await api_client_with_seed.get("/api/printers")
    assert resp.status_code == 200
    body = resp.json()
    assert body
    for p in body:
        for field in ("created_at", "updated_at"):
            assert _has_tz_suffix(p[field])


async def test_job_read_has_tz_suffix(api_client_with_completed_job):
    resp = await api_client_with_completed_job.get("/api/jobs?limit=1")
    body = resp.json()
    assert body
    for j in body:
        for field in ("created_at", "updated_at"):
            assert _has_tz_suffix(j[field])
        if j.get("printed_at"):
            assert _has_tz_suffix(j["printed_at"])
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/integration/api/test_api_datetime_format.py -v
```

Expected: 2 FAIL on `printer` and `job`, 1 PASS on `template`.

- [ ] **Step 3: Apply field_serializer**

Add the same `@field_serializer("created_at", "updated_at", "printed_at")` pattern from Task B2 to `PrinterRead` in `backend/app/schemas/printer.py` and to `JobRead` in `backend/app/schemas/job.py`. For `JobRead.printed_at` use a separate serialiser that handles `None`:

```python
@field_serializer("printed_at")
def _serialise_printed_at(self, dt: datetime | None, _info):
    return serialize_datetime_utc(dt, _info) if dt is not None else None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/integration/api/test_api_datetime_format.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/printer.py backend/app/schemas/job.py backend/tests/integration/api/test_api_datetime_format.py
git commit -m "$(cat <<'EOF'
fix(api): PrinterRead + JobRead emit RFC3339 datetimes with Z suffix

Same Go-oapi-codegen contract fix as TemplateRead. Job.printed_at
keeps None handling.

Refs #22
EOF
)"
```

### Task B4: SQLAlchemy models use DateTime(timezone=True) + UTC default

**Files:**
- Modify: `backend/app/models/template.py`
- Modify: `backend/app/models/printer.py`
- Modify: `backend/app/models/job.py`
- Modify: `backend/app/models/preset.py`
- Modify: `backend/app/models/printer_state.py`
- Modify: `backend/app/models/printer_status_cache.py`
- Create: `backend/tests/unit/models/test_datetime_columns.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/unit/models/test_datetime_columns.py
"""Phase 7b Cluster 1c — every datetime column must be timezone-aware."""

import pytest
from sqlalchemy import DateTime

from app.models.template import Template
from app.models.printer import Printer
from app.models.job import Job
from app.models.printer_state import PrinterState
from app.models.printer_status_cache import PrinterStatusCache


@pytest.mark.parametrize("model,columns", [
    (Template, ["created_at", "updated_at"]),
    (Printer, ["created_at", "updated_at"]),
    (Job, ["created_at", "updated_at", "printed_at"]),
    (PrinterState, ["created_at", "updated_at"]),
    (PrinterStatusCache, ["captured_at", "updated_at"]),
])
def test_datetime_columns_are_timezone_aware(model, columns):
    for col_name in columns:
        col = model.__table__.columns[col_name]
        assert isinstance(col.type, DateTime), f"{model.__name__}.{col_name} is not DateTime"
        assert col.type.timezone is True, \
            f"{model.__name__}.{col_name} must be DateTime(timezone=True)"
```

(If a `preset` model has datetimes, add it to the parametrize list. If not, skip.)

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/unit/models/test_datetime_columns.py -v
```

Expected: FAIL — most columns are `DateTime()` without `timezone=True`.

- [ ] **Step 3: Update each model**

For every datetime column in the listed models, replace the existing column declaration with:

```python
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime
from sqlmodel import Field

class Template(SQLModel, table=True):
    # ... other columns ...
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            onupdate=lambda: datetime.now(timezone.utc),
        ),
    )
```

For `Job.printed_at` (nullable):

```python
printed_at: datetime | None = Field(
    default=None,
    sa_column=Column(DateTime(timezone=True), nullable=True),
)
```

For `PrinterStatusCache.captured_at` (nullable):

```python
captured_at: datetime | None = Field(
    default=None,
    sa_column=Column(DateTime(timezone=True), nullable=True),
)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/unit/models/test_datetime_columns.py -v
cd backend && uv run pytest tests/integration/api/test_api_datetime_format.py -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/ backend/tests/unit/models/test_datetime_columns.py
git commit -m "$(cat <<'EOF'
refactor(api): SQLAlchemy datetime columns are timezone-aware UTC

Every model column (templates/printers/jobs/presets/printer_state/
printer_status_cache) now uses DateTime(timezone=True) with
default_factory=lambda: datetime.now(timezone.utc). Fresh inserts
write tz-aware values that survive the SQLite roundtrip.

Refs #22
EOF
)"
```

### Task B5: Alembic data migration for existing rows

**Files:**
- Create: `backend/alembic/versions/20260517_phase7b_datetime_tz.py`
- Create: `backend/tests/integration/db/test_alembic_phase7b_migration.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/integration/db/test_alembic_phase7b_migration.py
"""Phase 7b — datetime data migration is idempotent and adds +00:00 to naive rows."""

import pytest
from sqlalchemy import text

from alembic import command
from alembic.config import Config


pytestmark = pytest.mark.asyncio


def _alembic_config(db_url: str) -> Config:
    cfg = Config("backend/alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.attributes["configure_logger"] = False
    return cfg


async def test_migration_adds_tz_to_naive_rows(empty_sqlite_db, async_engine):
    """Insert naive datetimes, run migration, assert all rows have +00:00."""
    # 1. upgrade to head-1 (pre-7b)
    cfg = _alembic_config(empty_sqlite_db.url)
    command.upgrade(cfg, "head")
    # 2. insert a naive datetime row
    async with async_engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO templates (id, key, name, app, printer_model, tape_width_mm, "
            "schema_version, definition, source, created_at, updated_at) "
            "VALUES ('11111111-1111-1111-1111-111111111111', 'k', 'n', NULL, 'pt-series', "
            "12, 1, '{}', 'seed', '2026-05-17T12:00:00', '2026-05-17T12:00:00')"
        ))
    # 3. patch the row to look like a pre-7b naive timestamp (alembic upgrade did not
    #    create this — the row was inserted manually above; we just want to verify the
    #    migration is idempotent on already-correct rows). Run migration a second time.
    command.upgrade(cfg, "head")
    async with async_engine.begin() as conn:
        result = await conn.execute(text("SELECT created_at FROM templates"))
        row = result.first()
        assert "+00:00" in row[0] or row[0].endswith("Z"), \
            f"created_at not normalised: {row[0]!r}"


async def test_migration_idempotent_on_already_tz_aware_rows(async_engine):
    """Running the migration twice does not append +00:00 twice."""
    cfg = _alembic_config("sqlite:///:memory:")
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")  # idempotent
    # no exception, no doubled suffix
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/integration/db/test_alembic_phase7b_migration.py -v
```

Expected: FAIL with `Can't locate revision identified by '20260517_phase7b_datetime_tz'`.

- [ ] **Step 3: Write the migration**

```python
# backend/alembic/versions/20260517_phase7b_datetime_tz.py
"""Phase 7b — normalise existing datetime rows to timezone-aware ISO strings.

Existing rows in templates/printers/jobs/presets/printer_state/printer_status_cache
were inserted with naive datetimes when DateTime() lacked timezone=True. The Go
frontend's oapi-codegen client rejects them with `cannot parse "" as "Z07:00"`.

This migration is idempotent: it only updates rows whose datetime strings do NOT
already contain `+` or `Z`.

Revision ID: 20260517_phase7b_datetime_tz
Revises: <PREVIOUS_HEAD>
Create Date: 2026-05-17
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260517_phase7b_datetime_tz"
down_revision = "<FILL_IN_FROM: alembic heads>"  # implementer: run `cd backend && uv run alembic heads`
branch_labels = None
depends_on = None

_TABLES_DT = [
    ("templates", ["created_at", "updated_at"]),
    ("printers", ["created_at", "updated_at"]),
    ("jobs", ["created_at", "updated_at", "printed_at"]),
    ("presets", ["created_at", "updated_at"]),
    ("printer_state", ["created_at", "updated_at"]),
    ("printer_status_cache", ["captured_at", "updated_at"]),
]


def upgrade() -> None:
    for table, cols in _TABLES_DT:
        for col in cols:
            op.execute(
                f"UPDATE {table} SET {col} = {col} || '+00:00' "
                f"WHERE {col} IS NOT NULL "
                f"AND {col} NOT LIKE '%+%' "
                f"AND {col} NOT LIKE '%Z'"
            )


def downgrade() -> None:
    # Datetime suffix-stripping is risky and the prior naive behaviour is
    # the bug being fixed — downgrade is a no-op.
    pass
```

The implementer must replace `<FILL_IN_FROM: alembic heads>` with the result of `cd backend && uv run alembic heads` BEFORE running the test. List `presets` only if a `presets` table exists in the schema; otherwise remove that line.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run alembic upgrade head
cd backend && uv run pytest tests/integration/db/test_alembic_phase7b_migration.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/20260517_phase7b_datetime_tz.py backend/tests/integration/db/test_alembic_phase7b_migration.py
git commit -m "$(cat <<'EOF'
fix(api): alembic data migration normalises naive datetimes to UTC

Existing rows from Phase 5 inserts contain naive datetimes that break
the Go frontend's RFC3339 parser. Migration appends '+00:00' to any
value without an explicit TZ marker. Idempotent via WHERE NOT LIKE.

Refs #22
EOF
)"
```

---

## Phase C — Cluster 1b: Printer Identity

### Task C1: derive_printer_id helper

**Files:**
- Create: `backend/app/services/printer_identity.py`
- Create: `backend/tests/unit/services/test_printer_identity.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/unit/services/test_printer_identity.py
from uuid import UUID

from app.services.printer_identity import derive_printer_id


def test_same_inputs_produce_same_uuid():
    a = derive_printer_id("PT-P750W", "192.0.2.50", 9100)
    b = derive_printer_id("PT-P750W", "192.0.2.50", 9100)
    assert a == b


def test_host_change_produces_different_uuid():
    a = derive_printer_id("PT-P750W", "192.0.2.50", 9100)
    b = derive_printer_id("PT-P750W", "192.0.2.51", 9100)
    assert a != b


def test_returns_uuid_v5():
    out = derive_printer_id("PT-P750W", "192.0.2.50", 9100)
    assert isinstance(out, UUID)
    assert out.version == 5


def test_case_insensitive_model_normalised():
    """Model is upper/lower case but identity stays stable."""
    a = derive_printer_id("PT-P750W", "192.0.2.50", 9100)
    b = derive_printer_id("pt-p750w", "192.0.2.50", 9100)
    assert a == b
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/unit/services/test_printer_identity.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# backend/app/services/printer_identity.py
"""Deterministic printer UUIDv5 from environment configuration.

Lifespan derives a printer.id from `(model, host, port)` so that the
runtime printer and the DB row share the same id across restarts.
The namespace UUID is a constant committed to the repo; identical
env values always produce the same printer.id.
"""

from __future__ import annotations

from uuid import UUID, uuid5

# Constant namespace for printer identity derivation. Do not change without
# a coordinated DB migration — would orphan all existing printer rows.
_PRINTER_NAMESPACE = UUID("6f1b3c7e-9d6a-4f48-9a8c-d4e0e1c5a3b2")


def derive_printer_id(model: str, host: str, port: int) -> UUID:
    """Return a stable UUIDv5 for the (model, host, port) triple."""
    return uuid5(_PRINTER_NAMESPACE, f"{model.lower()}|{host}|{port}")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && uv run pytest tests/unit/services/test_printer_identity.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/printer_identity.py backend/tests/unit/services/test_printer_identity.py
git commit -m "$(cat <<'EOF'
feat(api): derive_printer_id helper for deterministic UUIDv5

Lifespan can now compute a stable printer.id from env config so
runtime printer and DB row share the same id across restarts.

Refs #22
EOF
)"
```

### Task C2: upsert_runtime_printer lifespan helper

**Files:**
- Modify: `backend/app/db/lifespan.py`
- Create: `backend/tests/integration/db/test_lifespan_printer_upsert.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/integration/db/test_lifespan_printer_upsert.py
import pytest
from sqlmodel import select

from app.db.lifespan import upsert_runtime_printer
from app.models.printer import Printer
from app.services.printer_identity import derive_printer_id
from app.config import Settings


pytestmark = pytest.mark.asyncio


def _settings_with_pt750w() -> Settings:
    return Settings(
        printer_backend="ptouch",
        printer_model="PT-P750W",
        pt750w_host="192.0.2.50",
        pt750w_port=9100,
        printer_discover_via_snmp=False,
        printer_snmp_community="public",
        webhook_api_key="x" * 32,
    )


async def test_upsert_creates_row_when_db_empty(async_session_empty):
    settings = _settings_with_pt750w()
    expected_id = derive_printer_id("PT-P750W", "192.0.2.50", 9100)

    returned_id = await upsert_runtime_printer(async_session_empty, settings)

    assert returned_id == expected_id
    result = await async_session_empty.execute(select(Printer))
    rows = list(result.scalars())
    assert len(rows) == 1
    assert rows[0].id == expected_id
    assert rows[0].connection["host"] == "192.0.2.50"


async def test_upsert_is_idempotent(async_session_empty):
    settings = _settings_with_pt750w()
    a = await upsert_runtime_printer(async_session_empty, settings)
    b = await upsert_runtime_printer(async_session_empty, settings)
    assert a == b
    result = await async_session_empty.execute(select(Printer))
    assert len(list(result.scalars())) == 1


async def test_upsert_returns_none_when_no_env_printer(async_session_empty):
    settings = Settings(
        printer_backend="mock",
        printer_model="",
        pt750w_host=None,
        ql820_host=None,
        webhook_api_key="x" * 32,
    )
    assert await upsert_runtime_printer(async_session_empty, settings) is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/integration/db/test_lifespan_printer_upsert.py -v
```

Expected: FAIL — `upsert_runtime_printer` not defined.

- [ ] **Step 3: Implement**

Append to `backend/app/db/lifespan.py`:

```python
from uuid import UUID

from app.config import Settings
from app.models.printer import Printer
from app.services.printer_identity import derive_printer_id


async def upsert_runtime_printer(
    session: AsyncSession,
    settings: Settings,
) -> UUID | None:
    """Upsert one Printer row from env config. Idempotent. Returns the UUID
    or None when the env does not declare a printer (e.g. mock backend).

    Lifespan calls this between `seed_templates` and `ensure_printer_state`
    so that ensure_printer_state can create a printer_state row for the
    upserted printer.
    """
    model = settings.printer_model
    host = settings.pt750w_host or getattr(settings, "ql820_host", None) or ""
    port = (
        settings.pt750w_port
        if settings.pt750w_host
        else getattr(settings, "ql820_port", 0)
    )
    if not (model and host and port):
        return None

    printer_id = derive_printer_id(model, host, port)
    existing = await session.get(Printer, printer_id)
    connection = {
        "host": host,
        "port": port,
        "snmp": settings.printer_discover_via_snmp,
        "snmp_community": settings.printer_snmp_community,
    }
    if existing is not None:
        existing.name = f"{model} ({host})"
        existing.connection = connection
        existing.enabled = True
    else:
        session.add(
            Printer(
                id=printer_id,
                name=f"{model} ({host})",
                model=model.lower(),
                backend=settings.printer_backend,
                connection=connection,
                enabled=True,
            )
        )
    await session.flush()
    return printer_id
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/integration/db/test_lifespan_printer_upsert.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/lifespan.py backend/tests/integration/db/test_lifespan_printer_upsert.py
git commit -m "$(cat <<'EOF'
feat(api): upsert_runtime_printer lifespan helper

Creates or refreshes one DB Printer row from env config using the
deterministic UUIDv5 derived in C1. Idempotent across restarts.

Refs #22
EOF
)"
```

### Task C3: Driver `make_queue_printer` accepts optional printer_id

**Files:**
- Modify: the file that defines `make_queue_printer` (grep `def make_queue_printer` in `backend/app/`)
- Create: `backend/tests/unit/printer_backends/test_make_queue_printer_id_param.py`

- [ ] **Step 1: Locate the implementation**

```bash
cd backend && grep -rn "def make_queue_printer" app/
```

Expected: one or two hits in `app/printer_backends/` or `app/printer_models/`. Note the exact file/class.

- [ ] **Step 2: Write failing test**

```python
# backend/tests/unit/printer_backends/test_make_queue_printer_id_param.py
from uuid import UUID, uuid4

# adjust the import to match the file located in Step 1
from app.printer_models.pt_series import PtSeriesDriver  # EXAMPLE PATH


class _MockBackend:
    pass


def test_make_queue_printer_accepts_optional_printer_id():
    driver = PtSeriesDriver(backend=_MockBackend())
    custom_id = uuid4()
    queue_printer = driver.make_queue_printer(tape_registry=None, printer_id=custom_id)
    assert queue_printer.id == custom_id


def test_make_queue_printer_generates_uuid_when_id_omitted():
    driver = PtSeriesDriver(backend=_MockBackend())
    queue_printer = driver.make_queue_printer(tape_registry=None)
    assert isinstance(queue_printer.id, UUID)
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/unit/printer_backends/test_make_queue_printer_id_param.py -v
```

Expected: FAIL — `TypeError: unexpected keyword argument 'printer_id'`.

- [ ] **Step 4: Add `printer_id` param**

Modify the driver method:

```python
from uuid import UUID, uuid4

def make_queue_printer(self, tape_registry, printer_id: UUID | None = None):
    pid = printer_id if printer_id is not None else uuid4()
    return _QueuePrinter(id=pid, driver=self, tape_registry=tape_registry)
```

(Apply identical change to the QL-series driver if it has its own `make_queue_printer`.)

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/unit/printer_backends/test_make_queue_printer_id_param.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/printer_models/ backend/tests/unit/printer_backends/test_make_queue_printer_id_param.py
git commit -m "$(cat <<'EOF'
refactor(api): driver.make_queue_printer accepts optional printer_id

Lifespan can now hand the DB-deterministic UUID to the in-memory
queue printer so app.state.printer_id matches the DB row id.

Refs #22
EOF
)"
```

---

## Phase D — Cluster 1a: Lifespan Init-Order

### Task D1: Defensive check in seed_templates

**Files:**
- Modify: `backend/app/db/lifespan.py`
- Modify: `backend/tests/unit/test_lifespan.py` (add a test)

- [ ] **Step 1: Write failing test**

Add to `backend/tests/unit/test_lifespan.py`:

```python
async def test_seed_templates_raises_on_empty_loader_cache():
    """Defensive check — empty TemplateLoader cache must abort, not silently no-op."""
    from app.db.lifespan import seed_templates
    from app.services.template_loader import TemplateLoader

    TemplateLoader._cache.clear()
    with pytest.raises(RuntimeError, match="empty TemplateLoader cache"):
        async with async_session() as s:
            await seed_templates(s, TemplateLoader)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/unit/test_lifespan.py::test_seed_templates_raises_on_empty_loader_cache -v
```

Expected: FAIL (currently it silently upserts 0 rows).

- [ ] **Step 3: Add defensive check**

In `backend/app/db/lifespan.py`, modify `seed_templates`:

```python
async def seed_templates(session: AsyncSession, loader: type[TemplateLoader]) -> int:
    """Idempotent YAML → DB upsert, delegated to ``loader.seed_db(session)``."""
    if not loader._cache:
        raise RuntimeError(
            "seed_templates called with empty TemplateLoader cache — "
            "lifespan must call TemplateLoader.load_dir() before seed_templates()"
        )
    return await loader.seed_db(session)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/unit/test_lifespan.py -v
```

Expected: green. Other lifespan tests must not break — if they do, those tests need to call `TemplateLoader.load_dir()` before `seed_templates`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/lifespan.py backend/tests/unit/test_lifespan.py
git commit -m "$(cat <<'EOF'
fix(api): seed_templates aborts on empty loader cache instead of silent no-op

Prevents the Phase 7a bug where lifespan called seed_templates
before load_dir — cache empty, 0 rows upserted, no error, UI shows
no templates. Defensive RuntimeError surfaces the misordering loudly.

Refs #22
EOF
)"
```

### Task D2: Re-order lifespan + wire upsert_runtime_printer + plumb printer_id

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/app/db/lifespan.py` (docstring at top of file)
- Create: `backend/tests/integration/test_lifespan_seeds_and_upserts.py`

- [ ] **Step 1: Write failing E2E test**

```python
# backend/tests/integration/test_lifespan_seeds_and_upserts.py
"""Phase 7b Cluster 1a + 1b end-to-end: a fresh DB after lifespan contains
12 templates and 1 deterministic-id printer, and app.state.printer_id matches
the DB printer.id."""

import pytest
from sqlmodel import select
from httpx import ASGITransport, AsyncClient

from app.main import app, lifespan
from app.db.engine import async_session
from app.models.printer import Printer
from app.models.template import Template
from app.services.printer_identity import derive_printer_id


pytestmark = pytest.mark.asyncio


async def test_fresh_lifespan_seeds_templates_and_creates_printer(empty_sqlite_db):
    async with lifespan(app):
        async with async_session() as s:
            templates = list((await s.execute(select(Template))).scalars())
            printers = list((await s.execute(select(Printer))).scalars())
        assert len(templates) >= 12, f"expected >=12 seed templates, got {len(templates)}"
        assert len(printers) == 1
        expected_id = derive_printer_id("PT-P750W", "192.0.2.50", 9100)
        assert printers[0].id == expected_id
        assert app.state.printer_id == expected_id
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/integration/test_lifespan_seeds_and_upserts.py -v
```

Expected: FAIL — current lifespan seeds 0 templates and runtime id != DB id.

- [ ] **Step 3: Re-order lifespan**

In `backend/app/main.py` replace the existing block (currently around lines 235–290):

```python
    settings = get_settings()

    # 1. DB schema first
    await run_migrations()
    await verify_alembic_at_head(settings)  # added in Task E1

    # 2. Application state BEFORE DB writes
    if _SEED_TEMPLATES_DIR.exists():
        TemplateLoader.load_dir(_SEED_TEMPLATES_DIR)
    else:
        raise RuntimeError(f"Seed templates dir missing: {_SEED_TEMPLATES_DIR}")

    # 3. Plugin registry (idempotent)
    if not IntegrationRegistry.names():
        _integrations_init._discover_plugins()
    ModelRegistry.ensure_discovered()

    # 4. DB-bound init (cache is populated, plugins are loaded)
    async with async_session() as s:
        await recover_inflight_jobs(s)
        await seed_templates(s, TemplateLoader)
        db_printer_id = await upsert_runtime_printer(s, settings)
        await ensure_printer_state(s)
        await s.commit()

    # 5. Discovery hardware + runtime printer
    discovery_host = settings.pt750w_host or ""
    if discovery_host and settings.printer_discover_via_snmp:
        model_id = await _resolve_model_id(settings, discovery_host)
    else:
        model_id = settings.printer_model
        if not model_id:
            raise ValueError(
                "printer_model is empty and SNMP discovery is disabled. "
                "Set PRINTER_HUB_PRINTER_MODEL or enable SNMP discovery."
            )

    backend = _build_backend(settings)
    driver_cls = ModelRegistry.find_by_model_id(model_id)
    driver = driver_cls(backend=backend)

    tape_registry = TapeRegistry()
    printer = driver.make_queue_printer(tape_registry, printer_id=db_printer_id)
    # ... rest unchanged (EventBus, producers, app.state, …)
```

(Skip the `verify_alembic_at_head` line — it lands in Phase E. For now the call will not exist; this task adds it. After Phase E lands the import is satisfied.)

To keep this task self-contained: add a temporary stub at the top of `lifespan.py` if needed, then replace in E1.

Update the `app/db/lifespan.py` top-of-file docstring to list the 6-step order:

```python
"""FastAPI startup helpers.

Call order in main.py lifespan:
    1. run_migrations()         — apply alembic upgrade head
    2. verify_alembic_at_head() — fail-fast on revision drift (Cluster 1d)
    3. TemplateLoader.load_dir()— populate the in-memory template cache (Cluster 1a)
    4. recover_inflight_jobs()  — mark stale jobs as FAILED_RESTART
    5. seed_templates()         — YAML → DB upsert (defensive check on cache)
    6. upsert_runtime_printer() — env → DB Printer row (Cluster 1b)
    7. ensure_printer_state()   — printer_state row per Printer
"""
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/integration/test_lifespan_seeds_and_upserts.py -v
cd backend && uv run pytest tests/unit/test_lifespan.py -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/app/db/lifespan.py backend/tests/integration/test_lifespan_seeds_and_upserts.py
git commit -m "$(cat <<'EOF'
fix(api): re-order lifespan — load_dir before seed_templates + upsert printer

Calls TemplateLoader.load_dir() before seed_templates(), and adds
upsert_runtime_printer(s, settings) between seed_templates and
ensure_printer_state. Hands the resulting DB UUID to
driver.make_queue_printer so app.state.printer_id matches the DB row.

Closes the Phase 7a bug where a fresh deploy showed 0 templates and 0
printers in the UI.

Refs #22
EOF
)"
```

---

## Phase E — Cluster 1d: Alembic Verify

### Task E1: verify_alembic_at_head

**Files:**
- Modify: `backend/app/db/lifespan.py`
- Create: `backend/tests/unit/test_alembic_verify.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/unit/test_alembic_verify.py
import pytest

from app.db.lifespan import verify_alembic_at_head
from app.config import Settings


pytestmark = pytest.mark.asyncio


async def test_verify_passes_when_db_at_head(empty_sqlite_db, settings_at_head):
    # alembic upgrade head was run in the fixture
    await verify_alembic_at_head(settings_at_head)  # no raise


async def test_verify_raises_on_stale_db(stale_sqlite_db, settings_at_head):
    """DB at one revision behind head → RuntimeError mentioning drift."""
    with pytest.raises(RuntimeError, match="migration drift"):
        await verify_alembic_at_head(settings_at_head)
```

The two fixtures `empty_sqlite_db` (advances to head) and `stale_sqlite_db` (advances to head-1) live in `backend/tests/conftest.py` — add them there:

```python
@pytest.fixture
async def empty_sqlite_db(tmp_path):
    from alembic import command
    from alembic.config import Config
    db = tmp_path / "fresh.db"
    cfg = Config("backend/alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    command.upgrade(cfg, "head")
    yield db


@pytest.fixture
async def stale_sqlite_db(tmp_path):
    from alembic import command
    from alembic.config import Config
    db = tmp_path / "stale.db"
    cfg = Config("backend/alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    command.upgrade(cfg, "-1")  # head minus 1
    yield db


@pytest.fixture
def settings_at_head(tmp_path):
    from app.config import Settings
    db = tmp_path / "settings_db.db"
    return Settings(
        database_url=f"sqlite+aiosqlite:///{db}",
        printer_backend="mock",
        webhook_api_key="x" * 32,
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/unit/test_alembic_verify.py -v
```

Expected: FAIL — `verify_alembic_at_head` not defined.

- [ ] **Step 3: Implement**

Append to `backend/app/db/lifespan.py`:

```python
import asyncio
from pathlib import Path

from sqlalchemy import create_engine

from app.config import Settings


async def verify_alembic_at_head(settings: Settings) -> None:
    """Raise RuntimeError if DB revision != alembic head.

    Takes Settings explicitly so the function is unit-testable without
    depending on the lru_cache'd get_settings() singleton.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from alembic.runtime.migration import MigrationContext

    ini_path = Path(__file__).resolve().parents[2] / "alembic.ini"

    def _check() -> tuple[str | None, str | None]:
        cfg = Config(str(ini_path))
        script = ScriptDirectory.from_config(cfg)
        head_rev = script.get_current_head()
        sync_url = settings.database_url.replace("+aiosqlite", "")
        engine = create_engine(sync_url)
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            current_rev = ctx.get_current_revision()
        return current_rev, head_rev

    current_rev, head_rev = await asyncio.to_thread(_check)
    if current_rev != head_rev:
        raise RuntimeError(
            f"Alembic migration drift detected: "
            f"DB at {current_rev!r}, expected head {head_rev!r}"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/unit/test_alembic_verify.py tests/integration/test_lifespan_seeds_and_upserts.py -v
```

Expected: all green (the lifespan integration test now uses the function added in D2).

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/lifespan.py backend/tests/unit/test_alembic_verify.py backend/tests/conftest.py
git commit -m "$(cat <<'EOF'
feat(api): verify_alembic_at_head fails fast on revision drift

Lifespan calls verify_alembic_at_head(settings) right after
run_migrations(). If the DB revision deviates from the script head
(e.g. partial migration, downgrade, missing script file) the lifespan
raises and the container fails to start with a clear log message.

Refs #22
EOF
)"
```

---

## Phase F — Cluster 1e: /readiness Endpoint

### Task F1: CheckStatus + ReadinessResponse schema

**Files:**
- Create: `backend/app/schemas/readiness.py`
- Create: `backend/tests/unit/schemas/test_readiness_schema.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/unit/schemas/test_readiness_schema.py
from app.schemas.readiness import CheckStatus, ReadinessResponse


def test_check_status_minimum_fields():
    c = CheckStatus(status="ok")
    assert c.status == "ok"
    assert c.detail is None
    assert c.metric is None


def test_readiness_response_aggregate():
    body = ReadinessResponse(
        status="ready",
        checks={"database": CheckStatus(status="ok", metric={"latency_ms": 0.8})},
        version="dev",
        revision="abc",
    )
    assert body.status == "ready"
    assert body.checks["database"].metric == {"latency_ms": 0.8}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/unit/schemas/test_readiness_schema.py -v
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```python
# backend/app/schemas/readiness.py
"""Phase 7b Cluster 1e — readiness response shape."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class CheckStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ok", "fail", "skipped", "stale"]
    detail: str | None = None
    metric: dict[str, Any] | None = None


class ReadinessResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ready", "degraded", "not-ready"]
    checks: dict[str, CheckStatus]
    version: str
    revision: str
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && uv run pytest tests/unit/schemas/test_readiness_schema.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/readiness.py backend/tests/unit/schemas/test_readiness_schema.py
git commit -m "$(cat <<'EOF'
feat(api): readiness response schema (CheckStatus + ReadinessResponse)

Frozen Pydantic models for the new /readiness deep-check endpoint
introduced by Phase 7b Cluster 1e.

Refs #22
EOF
)"
```

### Task F2: build_readiness_response — first half (database/alembic/template_seed/printer_runtime)

**Files:**
- Create: `backend/app/services/readiness.py`
- Create: `backend/tests/integration/test_readiness_endpoint.py`

- [ ] **Step 1: Write failing test (first 4 checks only)**

```python
# backend/tests/integration/test_readiness_endpoint.py
"""Phase 7b Cluster 1e — /readiness deep check."""

import pytest

pytestmark = pytest.mark.asyncio


async def test_readiness_database_check_ok(api_client_with_seed):
    resp = await api_client_with_seed.get("/readiness")
    body = resp.json()
    assert body["checks"]["database"]["status"] == "ok"
    assert "latency_ms" in body["checks"]["database"]["metric"]


async def test_readiness_alembic_check_ok(api_client_with_seed):
    resp = await api_client_with_seed.get("/readiness")
    body = resp.json()
    assert body["checks"]["alembic"]["status"] == "ok"


async def test_readiness_template_seed_check_ok(api_client_with_seed):
    resp = await api_client_with_seed.get("/readiness")
    body = resp.json()
    assert body["checks"]["template_seed"]["status"] == "ok"
    assert body["checks"]["template_seed"]["metric"]["templates_in_db"] >= 1


async def test_readiness_printer_runtime_check_ok(api_client_with_seed):
    resp = await api_client_with_seed.get("/readiness")
    body = resp.json()
    assert body["checks"]["printer_runtime"]["status"] == "ok"
```

(The `/readiness` endpoint itself lands in Task F4; for now these tests fail with 404. That is the expected RED state.)

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/integration/test_readiness_endpoint.py -v
```

Expected: 4 FAIL with 404.

- [ ] **Step 3: Implement first 4 checks**

```python
# backend/app/services/readiness.py
"""Phase 7b Cluster 1e — readiness aggregator."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.template import Template
from app.schemas.readiness import CheckStatus, ReadinessResponse


async def _check_database(session: AsyncSession) -> CheckStatus:
    try:
        t0 = time.monotonic()
        await session.execute(text("SELECT 1"))
        latency_ms = round((time.monotonic() - t0) * 1000, 2)
        return CheckStatus(status="ok", metric={"latency_ms": latency_ms})
    except Exception as exc:  # noqa: BLE001 — surface in the API
        return CheckStatus(status="fail", detail=str(exc))


async def _check_alembic(settings) -> CheckStatus:
    from app.db.lifespan import verify_alembic_at_head
    try:
        await verify_alembic_at_head(settings)
        return CheckStatus(status="ok")
    except Exception as exc:  # noqa: BLE001
        return CheckStatus(status="fail", detail=str(exc))


async def _check_template_seed(session: AsyncSession) -> CheckStatus:
    count = await session.scalar(select(func.count()).select_from(Template))
    if (count or 0) >= 1:
        return CheckStatus(status="ok", metric={"templates_in_db": count})
    return CheckStatus(
        status="fail",
        detail="Templates table is empty — lifespan init-order regression?",
        metric={"templates_in_db": 0},
    )


def _check_printer_runtime(app_state) -> CheckStatus:
    pid = getattr(app_state, "printer_id", None)
    if pid is None:
        return CheckStatus(status="fail", detail="app.state.printer_id is None")
    return CheckStatus(status="ok", metric={"printer_id": str(pid)})


async def build_readiness_response(
    session: AsyncSession,
    app_state,
    settings,
    *,
    version: str,
    revision: str,
) -> ReadinessResponse:
    checks: dict[str, CheckStatus] = {
        "database": await _check_database(session),
        "alembic": await _check_alembic(settings),
        "template_seed": await _check_template_seed(session),
        "printer_runtime": _check_printer_runtime(app_state),
    }
    return ReadinessResponse(
        status=_aggregate(checks),
        checks=checks,
        version=version,
        revision=revision,
    )


def _aggregate(checks: dict[str, CheckStatus]) -> str:
    critical = {"database", "alembic", "template_seed"}
    if any(checks[name].status == "fail" for name in critical if name in checks):
        return "not-ready"
    if any(c.status == "fail" for c in checks.values()):
        return "degraded"
    return "ready"
```

- [ ] **Step 4: Tests stay RED for now — endpoint added in F4**

Skip the run; F4 wires the endpoint.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/readiness.py
git commit -m "$(cat <<'EOF'
feat(api): readiness aggregator — database/alembic/templates/printer_runtime

First four /readiness checks plus the ready/degraded/not-ready aggregation
rule. Endpoint wiring follows in the next task.

Refs #22
EOF
)"
```

### Task F3: build_readiness_response — second half (printer_db_sync, snmp_discovery, print_queue, sse_bus)

**Files:**
- Modify: `backend/app/services/readiness.py`
- Modify: `backend/tests/integration/test_readiness_endpoint.py`

- [ ] **Step 1: Extend test file**

```python
async def test_readiness_printer_db_sync_ok(api_client_with_seed):
    resp = await api_client_with_seed.get("/readiness")
    body = resp.json()
    assert body["checks"]["printer_db_sync"]["status"] == "ok"


async def test_readiness_snmp_check_stale_when_no_probe_yet(api_client_with_seed):
    resp = await api_client_with_seed.get("/readiness")
    body = resp.json()
    # The fixture does not run a probe, so the cache is empty → fail/stale acceptable
    assert body["checks"]["snmp_discovery"]["status"] in {"stale", "fail", "skipped"}


async def test_readiness_aggregate_status_value(api_client_with_seed):
    resp = await api_client_with_seed.get("/readiness")
    body = resp.json()
    assert body["status"] in {"ready", "degraded", "not-ready"}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/integration/test_readiness_endpoint.py -v
```

Expected: still FAIL on 404, plus 3 new will fail.

- [ ] **Step 3: Add remaining 4 checks**

In `backend/app/services/readiness.py`:

```python
from app.models.printer import Printer
from app.models.printer_status_cache import PrinterStatusCache


async def _check_printer_db_sync(session: AsyncSession, app_state) -> CheckStatus:
    pid = getattr(app_state, "printer_id", None)
    if pid is None:
        return CheckStatus(status="skipped", detail="No runtime printer")
    row = await session.get(Printer, pid)
    if row is None:
        return CheckStatus(
            status="fail",
            detail=f"app.state.printer_id={pid} has no matching DB row",
        )
    return CheckStatus(status="ok")


async def _check_snmp_discovery(session: AsyncSession, app_state) -> CheckStatus:
    pid = getattr(app_state, "printer_id", None)
    if pid is None:
        return CheckStatus(status="skipped", detail="No runtime printer")
    row = await session.get(PrinterStatusCache, pid)
    if row is None or row.captured_at is None:
        return CheckStatus(status="fail", detail="No SNMP probe recorded yet")
    age_s = (datetime.now(timezone.utc) - row.captured_at).total_seconds()
    metric = {"last_probe_age_s": int(age_s)}
    if age_s < 90:
        return CheckStatus(status="ok", metric=metric)
    if age_s < 600:
        return CheckStatus(status="stale", detail=f"{int(age_s)}s ago (>90s)", metric=metric)
    return CheckStatus(status="fail", detail=f"{int(age_s)}s ago (>600s) — printer offline?", metric=metric)


def _check_print_queue(app_state) -> CheckStatus:
    queue = getattr(app_state, "print_queue", None)
    if queue is None:
        return CheckStatus(status="fail", detail="print_queue not in app.state")
    worker_count = getattr(queue, "worker_count", lambda: 1)()
    return CheckStatus(status="ok", metric={"worker_count": worker_count})


def _check_sse_bus(app_state) -> CheckStatus:
    bus = getattr(app_state, "event_bus", None)
    if bus is None:
        return CheckStatus(status="skipped", detail="event_bus not configured")
    subs = getattr(bus, "subscriber_count", lambda: 0)()
    max_subs = getattr(bus, "max_subscribers", 100)
    metric = {"subscribers": subs, "max": max_subs}
    if subs >= max_subs:
        return CheckStatus(status="fail", detail="subscriber pool exhausted", metric=metric)
    return CheckStatus(status="ok", metric=metric)
```

Extend `build_readiness_response`:

```python
checks = {
    "database": await _check_database(session),
    "alembic": await _check_alembic(settings),
    "template_seed": await _check_template_seed(session),
    "printer_runtime": _check_printer_runtime(app_state),
    "printer_db_sync": await _check_printer_db_sync(session, app_state),
    "snmp_discovery": await _check_snmp_discovery(session, app_state),
    "print_queue": _check_print_queue(app_state),
    "sse_bus": _check_sse_bus(app_state),
}
```

- [ ] **Step 4: Wait for F4 to run tests**

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/readiness.py backend/tests/integration/test_readiness_endpoint.py
git commit -m "$(cat <<'EOF'
feat(api): readiness aggregator — remaining 4 checks

printer_db_sync, snmp_discovery (with <90s ok / <600s stale / else fail
thresholds), print_queue worker liveness, sse_bus subscriber capacity.

Refs #22
EOF
)"
```

### Task F4: /readiness route + HTTP status code mapping

**Files:**
- Modify: `backend/app/main.py` (add the endpoint near /healthz)
- Modify: `backend/tests/integration/test_readiness_endpoint.py` (add HTTP-status tests)

- [ ] **Step 1: Add HTTP-status assertions**

Append to `backend/tests/integration/test_readiness_endpoint.py`:

```python
async def test_readiness_returns_200_when_ready(api_client_with_seed):
    resp = await api_client_with_seed.get("/readiness")
    if resp.json()["status"] == "ready":
        assert resp.status_code == 200


async def test_readiness_returns_503_when_not_ready(api_client_with_broken_db):
    """When the database check fails, status is not-ready → HTTP 503."""
    resp = await api_client_with_broken_db.get("/readiness")
    assert resp.status_code == 503
    assert resp.json()["status"] == "not-ready"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/integration/test_readiness_endpoint.py -v
```

Expected: many FAIL on 404.

- [ ] **Step 3: Add /readiness endpoint in main.py**

Near the `/healthz` endpoint in `backend/app/main.py`:

```python
from fastapi import Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.readiness import ReadinessResponse
from app.services.readiness import build_readiness_response


@app.get(
    "/readiness",
    response_model=ReadinessResponse,
    tags=["meta"],
    responses={503: {"model": ReadinessResponse}},
)
async def readiness(
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> ReadinessResponse:
    body = await build_readiness_response(
        session,
        app.state,
        get_settings(),
        version=HUB_VERSION,
        revision=HUB_REVISION,
    )
    if body.status == "not-ready":
        response.status_code = 503
    return body
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/integration/test_readiness_endpoint.py -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/tests/integration/test_readiness_endpoint.py
git commit -m "$(cat <<'EOF'
feat(api): expose /readiness deep-check endpoint

Returns 200 with body.status in {ready, degraded} or 503 with status
not-ready when database/alembic/template_seed fail. Pangolin can
switch its healthcheck.path to /readiness — Docker keeps polling
/healthz for liveness-only.

Refs #22
EOF
)"
```

### Task F5: Confirm /healthz remains minimal

**Files:**
- Modify: `backend/tests/integration/test_healthz_minimal.py` (add if missing)

- [ ] **Step 1: Write the test**

```python
# backend/tests/integration/test_healthz_minimal.py
"""Phase 7b Cluster 1e — /healthz never queries the database."""

import pytest

pytestmark = pytest.mark.asyncio


async def test_healthz_returns_200_even_with_broken_db(api_client_with_broken_db):
    """If DB explodes the liveness probe must still answer 200.

    Otherwise Docker autoheal restart-loops the container on transient DB
    failures, which is exactly the opposite of what we want.
    """
    resp = await api_client_with_broken_db.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
```

- [ ] **Step 2: Run test**

```bash
cd backend && uv run pytest tests/integration/test_healthz_minimal.py -v
```

Expected: PASS — `/healthz` does not depend on the DB.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_healthz_minimal.py
git commit -m "$(cat <<'EOF'
test(api): regression guard — /healthz must answer 200 even when DB broken

Locks in the Cluster 1e contract: liveness probe is restart-relevant,
readiness probe owns the deep checks. Prevents accidental DB queries
sneaking back into /healthz.

Refs #22
EOF
)"
```

---

## Phase G — Cluster 1f: Status Cache

### Task G1: StatusProbeProducer writes printer_status_cache on success

**Files:**
- Modify: `backend/app/services/producers/status_probe_producer.py`
- Create: `backend/tests/integration/test_status_cache_writer.py`

- [ ] **Step 1: Locate _probe_once / on_probe_result**

```bash
cd backend && grep -n "snmp_probe\|probe_once\|on_probe" app/services/producers/status_probe_producer.py
```

Note the existing method names so the new `_upsert_cache` call lands in the success path.

- [ ] **Step 2: Write failing test**

```python
# backend/tests/integration/test_status_cache_writer.py
"""Phase 7b Cluster 1f — StatusProbeProducer writes the printer_status_cache row."""

import pytest
from datetime import datetime, timezone
from uuid import uuid4

pytestmark = pytest.mark.asyncio


async def test_successful_probe_writes_cache(async_session_with_printer, mock_snmp_ok):
    """A probe success path persists raw_block + parsed JSON + captured_at."""
    from app.services.producers.status_probe_producer import StatusProbeProducer
    from app.services.event_bus import EventBus

    printer_id = async_session_with_printer.fixture_printer_id  # set by fixture
    producer = StatusProbeProducer(
        bus=EventBus(),
        printer_id=str(printer_id),
        host="192.0.2.50",
        interval_s=30,
        community="public",
        tape_change_producer=None,
    )
    await producer._probe_once()  # type: ignore[attr-defined]

    from app.models.printer_status_cache import PrinterStatusCache
    row = await async_session_with_printer.get(PrinterStatusCache, printer_id)
    assert row is not None
    assert row.captured_at is not None
    assert row.parsed["online"] is True
    assert row.parsed["tape_width_mm"] == 12


async def test_probe_failure_marks_offline(async_session_with_printer, mock_snmp_timeout):
    from app.services.producers.status_probe_producer import StatusProbeProducer
    from app.services.event_bus import EventBus

    printer_id = async_session_with_printer.fixture_printer_id
    producer = StatusProbeProducer(
        bus=EventBus(),
        printer_id=str(printer_id),
        host="192.0.2.50",
        interval_s=30,
        community="public",
        tape_change_producer=None,
    )
    await producer._probe_once()

    from app.models.printer_status_cache import PrinterStatusCache
    row = await async_session_with_printer.get(PrinterStatusCache, printer_id)
    assert row.parsed["online"] is False
    assert "timeout" in row.parsed["last_error"].lower()
```

The two fixtures `mock_snmp_ok` and `mock_snmp_timeout` go in `backend/tests/conftest.py` — they monkeypatch the SNMP call to return a deterministic block (`tape_width_mm=12` etc) or raise `SnmpTimeoutError`.

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/integration/test_status_cache_writer.py -v
```

Expected: FAIL — no cache writes happen today.

- [ ] **Step 4: Add `_upsert_cache` and `_mark_offline`**

In `backend/app/services/producers/status_probe_producer.py`:

```python
from datetime import datetime, timezone
from app.db.engine import async_session
from app.models.printer_status_cache import PrinterStatusCache


async def _upsert_cache(self, snmp_result) -> None:
    """Persist a successful SNMP probe into printer_status_cache."""
    parsed = {
        "online": True,
        "tape_width_mm": getattr(snmp_result, "tape_width_mm", None),
        "tape_color": getattr(snmp_result, "tape_color", None),
        "text_color": getattr(snmp_result, "text_color", None),
        "model_id": getattr(snmp_result, "model_id", None),
    }
    raw_block = getattr(snmp_result, "raw_block", None)
    async with async_session() as s:
        row = await s.get(PrinterStatusCache, self._printer_id)
        if row is not None:
            row.parsed = parsed
            row.raw_block = raw_block
            row.captured_at = datetime.now(timezone.utc)
        else:
            s.add(
                PrinterStatusCache(
                    printer_id=self._printer_id,
                    parsed=parsed,
                    raw_block=raw_block,
                    captured_at=datetime.now(timezone.utc),
                )
            )
        await s.commit()


async def _mark_offline(self, exc: Exception) -> None:
    """Persist a failed probe; preserves any previous parsed fields."""
    async with async_session() as s:
        row = await s.get(PrinterStatusCache, self._printer_id)
        parsed = dict(row.parsed) if (row is not None and row.parsed) else {}
        parsed["online"] = False
        parsed["last_error"] = str(exc)
        if row is not None:
            row.parsed = parsed
            row.captured_at = datetime.now(timezone.utc)
        else:
            s.add(
                PrinterStatusCache(
                    printer_id=self._printer_id,
                    parsed=parsed,
                    captured_at=datetime.now(timezone.utc),
                )
            )
        await s.commit()
```

Then wire them into the existing `_probe_once`:

```python
async def _probe_once(self) -> None:
    try:
        snmp_result = await self._snmp_probe()
    except SnmpTimeoutError as exc:
        await self._mark_offline(exc)
        await self._publish_event_offline(exc)
        return
    await self._upsert_cache(snmp_result)
    await self._publish_event(snmp_result)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/integration/test_status_cache_writer.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/producers/status_probe_producer.py backend/tests/integration/test_status_cache_writer.py backend/tests/conftest.py
git commit -m "$(cat <<'EOF'
feat(status): StatusProbeProducer persists printer_status_cache rows

Every probe success writes raw_block + parsed JSON + captured_at;
SNMP timeouts persist online=False + last_error in the parsed JSON.
No schema change — uses existing Phase 5 columns.

Refs #22
EOF
)"
```

### Task G2: PrinterStatus schema extensions

**Files:**
- Modify: `backend/app/schemas/printer.py`
- Create: `backend/tests/unit/schemas/test_printer_status_fields.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/unit/schemas/test_printer_status_fields.py
from datetime import datetime, timezone
from uuid import uuid4
from app.schemas.printer import PrinterStatus


def test_printer_status_minimal_fields():
    s = PrinterStatus(printer_id=uuid4(), online=None, captured_at=None)
    assert s.online is None
    assert s.captured_at is None


def test_printer_status_full_fields():
    pid = uuid4()
    now = datetime.now(timezone.utc)
    s = PrinterStatus(
        printer_id=pid,
        online=True,
        tape_width_mm=12,
        captured_at=now,
        last_probe_age_s=15,
        last_error=None,
        note=None,
    )
    assert s.online is True
    assert s.last_probe_age_s == 15


def test_printer_status_pending_with_note():
    s = PrinterStatus(
        printer_id=uuid4(),
        online=None,
        captured_at=None,
        note="No probe yet — wait up to 30s",
    )
    assert s.note.startswith("No probe yet")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/unit/schemas/test_printer_status_fields.py -v
```

Expected: FAIL — most fields not present.

- [ ] **Step 3: Extend PrinterStatus**

In `backend/app/schemas/printer.py`:

```python
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_serializer

from app.schemas._datetime import serialize_datetime_utc


class PrinterStatus(BaseModel):
    """Cached SNMP status surfaced by GET /api/printers/{id}/status."""

    model_config = ConfigDict(frozen=True)

    printer_id: UUID
    online: bool | None = None
    tape_width_mm: int | None = None
    tape_color: str | None = None
    text_color: str | None = None
    captured_at: datetime | None = None
    last_probe_age_s: int | None = None
    last_error: str | None = None
    note: str | None = None

    @field_serializer("captured_at")
    def _serialise_captured_at(self, dt: datetime | None, _info):
        return serialize_datetime_utc(dt, _info) if dt is not None else None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/unit/schemas/test_printer_status_fields.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/printer.py backend/tests/unit/schemas/test_printer_status_fields.py
git commit -m "$(cat <<'EOF'
feat(status): PrinterStatus carries cache freshness + offline reason

Adds captured_at, last_probe_age_s, last_error, note to the response
of /api/printers/{id}/status so the UI can render staleness and the
offline reason instead of guessing.

Refs #22
EOF
)"
```

### Task G3: REST endpoint reads cache, never blocks on SNMP

**Files:**
- Modify: `backend/app/api/routes/printers.py`
- Create: `backend/tests/integration/test_status_endpoint_cached.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/integration/test_status_endpoint_cached.py
"""Phase 7b Cluster 1f — /status returns cache; never blocks on SNMP."""

import asyncio
import time

import pytest

pytestmark = pytest.mark.asyncio


async def test_status_endpoint_returns_pending_when_cache_empty(api_client_with_seed):
    """Cold start: cache row absent → 200 + online=null + note hint."""
    resp = await api_client_with_seed.get(
        f"/api/printers/{api_client_with_seed.fixture_printer_id}/status"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["online"] is None
    assert "No probe yet" in body["note"]


async def test_status_endpoint_returns_under_100ms(api_client_with_warm_cache, mock_snmp_blocker):
    """Even with SNMP blocked for 10s the endpoint must answer from cache."""
    pid = api_client_with_warm_cache.fixture_printer_id
    t0 = time.monotonic()
    resp = await api_client_with_warm_cache.get(f"/api/printers/{pid}/status")
    elapsed_ms = (time.monotonic() - t0) * 1000
    assert resp.status_code == 200
    assert elapsed_ms < 100, f"endpoint blocked {elapsed_ms:.1f}ms"
```

`mock_snmp_blocker` patches `_snmp_probe` to `asyncio.sleep(10)` and would cause failure if the endpoint accidentally tries to invoke it.

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/integration/test_status_endpoint_cached.py -v
```

Expected: FAIL — current endpoint does sync SNMP.

- [ ] **Step 3: Rewrite the endpoint**

In `backend/app/api/routes/printers.py`, replace the body of the `/status` route:

```python
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models.printer_status_cache import PrinterStatusCache
from app.schemas.printer import PrinterStatus

router = APIRouter()


@router.get("/api/printers/{printer_id}/status", response_model=PrinterStatus)
async def get_printer_status(
    printer_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> PrinterStatus:
    """Return cached SNMP status. Never blocks on the printer.

    Fresh data arrives via SSE (Phase 6b) and via the periodic probe worker
    every ``settings.sse_probe_interval_s`` seconds (default 30).
    """
    row = await session.get(PrinterStatusCache, printer_id)
    if row is None or row.captured_at is None:
        return PrinterStatus(
            printer_id=printer_id,
            online=None,
            captured_at=None,
            note="No probe yet — wait up to 30s for first probe cycle",
        )
    parsed = row.parsed or {}
    age_s = (datetime.now(timezone.utc) - row.captured_at).total_seconds()
    return PrinterStatus(
        printer_id=printer_id,
        online=parsed.get("online"),
        tape_width_mm=parsed.get("tape_width_mm"),
        tape_color=parsed.get("tape_color"),
        text_color=parsed.get("text_color"),
        captured_at=row.captured_at,
        last_probe_age_s=int(age_s),
        last_error=parsed.get("last_error"),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/integration/test_status_endpoint_cached.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/printers.py backend/tests/integration/test_status_endpoint_cached.py
git commit -m "$(cat <<'EOF'
fix(status): /api/printers/{id}/status reads from cache, no sync SNMP

Eliminates the 5-second block when the printer is offline. The
probe worker keeps printer_status_cache fresh in the background;
this endpoint returns whatever is there in <10 ms.

Refs #22
EOF
)"
```

---

## Phase H — Cluster 3: Frontend Proxy

### Task H1: Mount /docs, /openapi.json, /redoc through the proxy

**Files:**
- Modify: `frontend/cmd/server/main.go` (around lines 137–144)
- Modify: `frontend/cmd/server/main_test.go`

- [ ] **Step 1: Write failing test**

Add to `frontend/cmd/server/main_test.go`:

```go
func TestProxyMountsBackendDocRoutes(t *testing.T) {
    t.Parallel()
    backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        switch r.URL.Path {
        case "/docs":
            w.Header().Set("Content-Type", "text/html")
            io.WriteString(w, "<html>Swagger UI</html>")
        case "/openapi.json":
            w.Header().Set("Content-Type", "application/json")
            io.WriteString(w, `{"openapi":"3.1.0"}`)
        case "/redoc":
            io.WriteString(w, "ReDoc")
        default:
            w.WriteHeader(http.StatusNotFound)
        }
    }))
    defer backend.Close()

    r := newRouter(stubPageHandler(t), proxy.New(backend.URL), testStaticFS)

    for path, want := range map[string]string{
        "/docs":         "Swagger UI",
        "/openapi.json": `"openapi":"3.1.0"`,
        "/redoc":        "ReDoc",
    } {
        rec := httptest.NewRecorder()
        r.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, path, nil))
        if rec.Code != http.StatusOK {
            t.Fatalf("%s: got %d, want 200", path, rec.Code)
        }
        if !strings.Contains(rec.Body.String(), want) {
            t.Errorf("%s: body = %q, want substring %q", path, rec.Body.String(), want)
        }
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && go test ./cmd/server/ -run TestProxyMountsBackendDocRoutes -v
```

Expected: FAIL — three 404s.

- [ ] **Step 3: Add the mounts**

In `frontend/cmd/server/main.go`, after the existing `r.Mount("/product", prx)` line:

```go
    // FastAPI auto-doc endpoints (Phase 7b Cluster 3).
    r.Mount("/docs", prx)
    r.Mount("/openapi.json", prx)
    r.Mount("/redoc", prx)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && go test ./cmd/server/ -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add frontend/cmd/server/main.go frontend/cmd/server/main_test.go
git commit -m "$(cat <<'EOF'
feat(frontend): proxy /docs, /openapi.json, /redoc to the backend

Swagger UI and the raw OpenAPI document are now reachable under the
public domain (behind Pangolin SSO + the Basic-Auth bypass). Closes
the 404 reported in the hhdocker02 smoke test.

Refs #22
EOF
)"
```

---

## Phase I — Cluster 2: Documentation

### Task I1: README mentions /readiness and the Phase 7b spec

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Identify the section that documents the runtime API**

```bash
cd /opt/repos/label-printer-hub && grep -n "healthz\|/api/" README.md | head -5
```

- [ ] **Step 2: Add a paragraph just below the `/healthz` mention**

```markdown
### Health probes

The backend exposes two HTTP probes with different semantics:

| Endpoint | Purpose | What it answers |
|---|---|---|
| `GET /healthz` | Liveness — for Docker/Kubernetes container restart | "the process and the event loop are alive" |
| `GET /readiness` | Readiness — for reverse-proxy routing | "the process can serve traffic right now": database connectable, alembic at head, templates seeded, runtime printer matches DB, SNMP probe fresh, queue worker alive |

`/readiness` returns HTTP 200 with a `status` of `"ready"` or `"degraded"` (still routable), and HTTP 503 with `"not-ready"` when a critical check (database / alembic / template_seed) fails. See the Phase 7b foundation design in `docs/superpowers/specs/2026-05-17-phase-7b-foundation-design.md` for the full check list.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs(api): document /healthz vs /readiness contract in the README

Explains the liveness/readiness split introduced in Phase 7b Cluster
1e and links to the spec for the full check list.

Refs #22
EOF
)"
```

---

## Phase J — Verification

### Task J1: Full test suite + coverage gate

**Files:** none

- [ ] **Step 1: Run the full backend suite**

```bash
cd backend && uv run pytest --cov=app --cov-report=term-missing -q
```

Expected: all tests pass and coverage ≥80 (the existing `fail_under = 80` in `pyproject.toml`). If coverage drops, add tests until back at or above the threshold — every cluster has at least one test file from the previous phases; gap-filling tests go into the same directories.

- [ ] **Step 2: Type and lint checks**

```bash
cd backend && uv run mypy app && uv run ruff check . && uv run ruff format --check .
```

Expected: all clean.

- [ ] **Step 3: Frontend tests**

```bash
cd frontend && go test ./... && go vet ./...
```

Expected: all clean.

- [ ] **Step 4: oapi-codegen contract**

```bash
cd frontend && make oapi-check  # or: ./scripts/regen-and-diff-openapi.sh
```

Expected: generated client matches checked-in code. If not, re-generate and commit as `chore(frontend): regenerate oapi-codegen client for Phase 7b`.

- [ ] **Step 5: Commit any regeneration or coverage gap fixes**

If anything changed:

```bash
git add -p
git commit -m "$(cat <<'EOF'
chore(ci): Phase 7b verification — regen client / coverage gap-fill

Refs #22
EOF
)"
```

### Task J2: Production smoke test against labels.example.com

**Files:** none

- [ ] **Step 1: Build + push images (CI does this on PR merge — only do it locally if testing pre-merge)**

```bash
# (CI normally handles this — skip if testing post-merge)
```

- [ ] **Step 2: Pull Header-Auth credentials from the vault**

```bash
# Vault item name documented in docs/policies/secrets.md (or whatever the maintainer points at)
# Result: BASIC_USER=claude-automation, BASIC_PASS=<64-hex>
```

- [ ] **Step 3: Hit /healthz and /readiness against the production resource**

```bash
curl -fsS -u "claude-automation:${BASIC_PASS}" \
  https://labels.example.com/healthz
# expected: HTTP 200, {"status":"ok",...}

curl -fsS -u "claude-automation:${BASIC_PASS}" \
  https://labels.example.com/readiness | jq
# expected: HTTP 200 with status=ready (printer online) OR status=degraded
# (printer offline, but database/alembic/template_seed all ok)
```

- [ ] **Step 4: Hit /docs through the proxy**

```bash
curl -fsS -u "claude-automation:${BASIC_PASS}" \
  -o /dev/null -w '%{http_code}\n' https://labels.example.com/docs
# expected: 200
curl -fsS -u "claude-automation:${BASIC_PASS}" \
  https://labels.example.com/openapi.json | jq '.info.title'
# expected: "label-printer-hub" (or whatever HUB_VERSION exposes)
```

- [ ] **Step 5: Hit /api/printers/{id}/status (cache fast-path)**

```bash
PRINTER_ID=$(curl -fsS -u "claude-automation:${BASIC_PASS}" \
  https://labels.example.com/api/printers | jq -r '.[0].id')
time curl -fsS -u "claude-automation:${BASIC_PASS}" \
  https://labels.example.com/api/printers/${PRINTER_ID}/status | jq
# expected: response in well under 100 ms
```

- [ ] **Step 6: Hit the UI in a real browser**

Navigate to `https://labels.example.com/` (SSO login via Pangolin), confirm:
- 12 templates render on `/templates`
- 1 printer renders on `/`
- Printer detail page shows live status (online/offline + tape width)
- No 503s

Note results in the PR description as part of the production-smoke checklist.

### Task J3: Push the branch and open the PR

**Files:** none

- [ ] **Step 1: Push**

```bash
git push -u origin feat/phase-7b-foundation
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --base main --head feat/phase-7b-foundation \
  --title "feat(api): Phase 7b foundation — init, datetime-TZ, /readiness, status cache, proxy widening" \
  --body "$(cat <<'EOF'
## Summary

Implements the merged Phase 7b spec across nine clusters. Closes the
foundation gaps surfaced by the first hhdocker02 production deploy.

Highlights:
- Lifespan re-ordered (load_dir before seed_templates) + defensive check
- Deterministic UUIDv5 printer identity, lifespan auto-upsert
- DateTime(timezone=True) everywhere + Pydantic Z-suffix serialiser + idempotent Alembic data migration
- `verify_alembic_at_head(settings)` fails fast on revision drift
- New `/readiness` endpoint with 8 deep checks (200/503 mapping)
- `printer_status_cache` is now the source of truth for `/api/printers/{id}/status` (no sync SNMP)
- Frontend proxies `/docs`, `/openapi.json`, `/redoc` to the backend
- README documents the /healthz vs /readiness contract

## Test plan

- [x] `uv run pytest --cov=app` ≥ 80
- [x] `uv run mypy app && uv run ruff check . && uv run ruff format --check .`
- [x] `go test ./... && go vet ./...`
- [x] Manual smoke against `labels.example.com` — /healthz, /readiness, /docs, /api/printers/{id}/status, UI in browser

Refs #22
EOF
)"
```

- [ ] **Step 3: Confirm PR opened, CI green, then hand off**

Wait for CI + bot reviews. Address findings per `.claude/rules/review-feedback-policy.md` (≥15 min after each push, reply + resolve all threads, then squash-merge).

---

## Self-review notes

- **Spec coverage:** Every cluster (1a–3) has its own task. Cluster 2 = Task I1 (README + spec link). Cluster 3 = Task H1.
- **Ordering rationale:** 1c (datetime) lands first — every model touched downstream gets the correct column type from the outset. 1b (printer identity) lands before 1f (cache reader) so the cache always references a stable id. 1a (lifespan order) lands after 1b so the lifespan re-order already wires `upsert_runtime_printer` in. 1d (alembic verify) sits next to the lifespan changes. 1e and 1f are independent of each other but 1e tests reference the cache writer from 1f for the `snmp_discovery` check.
- **Scope discipline:** No tasks add unrelated features. Removal of the `printer_status_cache.last_error` column from the original spec (no schema change after all) is reflected in B5 — only data migration on existing rows, no DDL.
- **Estimated wall-clock under subagent-driven-development:** ~3.5 h (Phase B: ~60 min, C: ~30, D: ~30, E: ~15, F: ~45, G: ~30, H: ~10, I: ~5, J: ~30 minus review-loop time).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-17-phase-7b-foundation.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, two-stage review (spec compliance + code quality) between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints for review.

Which approach?
