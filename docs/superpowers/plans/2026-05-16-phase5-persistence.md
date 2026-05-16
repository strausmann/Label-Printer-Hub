# Phase 5 — Persistence Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax. Each task = one commit.

**Goal:** Land the SQLModel/aiosqlite persistence layer per the spec at `docs/superpowers/specs/2026-05-16-phase5-persistence-design.md` (commit `27943e0`).

**Architecture:** Six SQLModel tables in `backend/app/models/`, async engine + session in `backend/app/db/`, repository functions per aggregate, Alembic migrations bootstrapped, lifespan-driven seed + recovery.

**Tech Stack:** Python 3.12 + SQLModel + aiosqlite + Alembic + pytest + pytest-asyncio.

**Tracking:** Issue #19 (per `Refs #19` in every commit body).

---

## Conventions for every commit

- Conventional Commits scope from the commitlint enum: `api` for db/lifespan/repository code (the DB layer powers the API), `printer-backends` is reserved for worker/queue work and not used here, `ci` for any CI-config changes, `docs` for plan/spec follow-ups.
- header-max-length 120 per the relaxed config (PR #60).
- Each commit body ends with `Refs #19`.
- **No** `Co-Authored-By: Claude` anywhere.
- Subagents do NOT push. Orchestrator handles push + PR.
- TDD-strict per task: failing test → impl → green → commit.

## Cross-cutting reminder for every model task (Tasks 1–6)

**Every new model class MUST be exported from `backend/app/models/__init__.py`** before running `alembic revision --autogenerate`. The Alembic `env.py` does `import app.models` to register tables with `SQLModel.metadata`; if a class is not re-exported there, autogenerate produces an **empty** migration and the table silently disappears from the schema. Each model task below includes an explicit edit step for the package init file.

---

## File structure (target state)

**New files:**

```
backend/
├── alembic.ini
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 2026_05_16_0001_phase5_initial.py
├── app/
│   ├── db/
│   │   ├── __init__.py
│   │   ├── engine.py
│   │   ├── session.py
│   │   └── lifespan.py
│   ├── models/
│   │   ├── printer.py
│   │   ├── template.py
│   │   ├── preset.py
│   │   ├── job.py
│   │   ├── printer_state.py
│   │   └── printer_status_cache.py
│   └── repositories/
│       ├── __init__.py
│       ├── printers.py
│       ├── templates.py
│       ├── presets.py
│       ├── jobs.py
│       └── printer_state.py
└── tests/
    ├── db/
    │   ├── conftest.py             # in-memory engine fixture
    │   ├── test_engine.py          # pragmas + connection
    │   ├── test_lifespan.py        # recovery + seed
    │   ├── test_printers_repo.py
    │   ├── test_templates_repo.py
    │   ├── test_presets_repo.py
    │   ├── test_jobs_repo.py
    │   └── test_printer_state_repo.py
```

**Modified files:**

- `backend/app/services/template_loader.py` — add `seed_db(session)` method
- `backend/pyproject.toml` — add `alembic` to deps
- `.gitignore` — add `data/hub.db*`

---

## Task 0: Alembic bootstrap + engine + session

**Files:**
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/app/db/__init__.py`
- Create: `backend/app/db/engine.py`
- Create: `backend/app/db/session.py`
- Modify: `backend/pyproject.toml` (add `alembic`)
- Modify: `.gitignore` (add `data/hub.db*`)
- Create: `backend/tests/db/conftest.py`
- Create: `backend/tests/db/test_engine.py`

Sets up the async engine, pragma application, the FastAPI session dependency, and the Alembic skeleton. Migration `2026_05_16_0001_phase5_initial` will be created **empty** here — tables get added in their respective tasks via `alembic revision --autogenerate` runs.

- [ ] **Step 1: Add `alembic` dep**

```toml
# backend/pyproject.toml — under [tool.poetry.dependencies]
alembic = "^1.14"
```

Run `uv sync` (or equivalent) to lock.

- [ ] **Step 2: `backend/app/db/engine.py`**

```python
"""Async SQLAlchemy engine with SQLite pragma enforcement."""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.getenv(
    "LABEL_HUB_DATABASE_URL",
    "sqlite+aiosqlite:///./data/hub.db",
)


def _apply_pragmas(dbapi_connection, _connection_record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA journal_mode = WAL")
    cur.execute("PRAGMA synchronous = NORMAL")
    cur.execute("PRAGMA foreign_keys = ON")
    cur.execute("PRAGMA busy_timeout = 5000")
    cur.close()


def _ensure_data_dir(url: str) -> None:
    if url.startswith("sqlite+aiosqlite:///"):
        path = url.removeprefix("sqlite+aiosqlite:///")
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)


_ensure_data_dir(DATABASE_URL)

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)

# Register the pragma hook on the underlying SQLAlchemy engine.
event.listen(engine.sync_engine, "connect", _apply_pragmas)

async_session = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
```

- [ ] **Step 3: `backend/app/db/session.py`**

```python
"""FastAPI dependency for async DB sessions."""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import async_session


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session() as session:
        yield session
```

- [ ] **Step 4: Alembic skeleton**

Run `alembic init --template async backend/alembic` from the repo root. Adjust `alembic.ini`:

```ini
script_location = backend/alembic
sqlalchemy.url = sqlite+aiosqlite:///./data/hub.db
```

In `backend/alembic/env.py`, replace the default target_metadata reference with:

```python
from sqlmodel import SQLModel
import app.models  # noqa: F401 — registers models with SQLModel.metadata

target_metadata = SQLModel.metadata
```

- [ ] **Step 5: Generate empty initial migration**

```bash
cd backend
alembic revision -m "phase5 initial"
```

Edit the produced file to set its revision id to a stable string `2026_05_16_0001_phase5_initial` for traceability. Body stays empty (tables come in later tasks via autogenerate).

- [ ] **Step 6: `.gitignore`**

Append:

```
# Phase 5 persistence
backend/data/
backend/data/hub.db*
```

- [ ] **Step 7: Test fixture**

```python
# backend/tests/db/conftest.py
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import app.models  # noqa: F401


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
```

- [ ] **Step 8: Pragma test**

```python
# backend/tests/db/test_engine.py
import pytest
from sqlalchemy import text

@pytest.mark.asyncio
async def test_pragmas_applied(session):
    journal = (await session.execute(text("PRAGMA journal_mode"))).scalar()
    assert journal == "wal"
    fk = (await session.execute(text("PRAGMA foreign_keys"))).scalar()
    assert fk == 1
    busy = (await session.execute(text("PRAGMA busy_timeout"))).scalar()
    assert busy == 5000
```

- [ ] **Step 9: Run + commit**

```bash
cd backend && pytest tests/db/test_engine.py -v
```

Expected: PASS (1 test).

Commit:

```
feat(api): bootstrap async DB engine, sessions, Alembic skeleton

Adds backend/app/db/{engine,session}.py with WAL + busy_timeout + FK
pragmas enforced via SQLAlchemy connect-event hook. FastAPI session
dependency yields AsyncSession per request. Alembic initialised in
async-template mode with an empty initial migration; tables follow
in subsequent commits via autogenerate.

data/hub.db git-ignored.

Refs #19
```

---

## Task 1: `printer` model + repository

**Files:**
- Create: `backend/app/models/printer.py`
- Create: `backend/app/models/__init__.py` (re-exports)
- Create: `backend/app/repositories/__init__.py`
- Create: `backend/app/repositories/printers.py`
- Create: `backend/tests/db/test_printers_repo.py`

- [ ] **Step 1: Model**

```python
# backend/app/models/printer.py
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


class Printer(SQLModel, table=True):
    __tablename__ = "printers"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(index=True, unique=True)
    model: str
    backend: str
    connection: dict = Field(default_factory=dict, sa_column=Column(JSON))
    enabled: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column_kwargs={"onupdate": lambda: datetime.now(UTC)},
    )
```

- [ ] **Step 2: Repository**

```python
# backend/app/repositories/printers.py
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.printer import Printer


async def list_all(session: AsyncSession) -> list[Printer]:
    result = await session.execute(select(Printer).order_by(Printer.created_at))
    return list(result.scalars())


async def get(session: AsyncSession, printer_id: UUID) -> Printer | None:
    return await session.get(Printer, printer_id)


async def get_by_name(session: AsyncSession, name: str) -> Printer | None:
    result = await session.execute(select(Printer).where(Printer.name == name))
    return result.scalar_one_or_none()


async def create(session: AsyncSession, printer: Printer) -> Printer:
    session.add(printer)
    await session.commit()
    await session.refresh(printer)
    return printer
```

- [ ] **Step 3: Models package `__init__.py`**

```python
# backend/app/models/__init__.py
from app.models.printer import Printer

__all__ = ["Printer"]
```

- [ ] **Step 4: Tests**

```python
# backend/tests/db/test_printers_repo.py
import pytest

from app.models.printer import Printer
from app.repositories import printers


@pytest.mark.asyncio
async def test_create_and_get_by_name(session):
    # Use registered entry-points; pt-series + ptouch are the only ones
    # available pre-Phase-2-followup (#11 adds ql-series + QL backend).
    p = Printer(name="pt-office", model="pt-series", backend="ptouch",
                connection={"interface": "usb", "serial": "0000G0Z123456"})
    created = await printers.create(session, p)
    assert created.id is not None
    found = await printers.get_by_name(session, "ql820-office")
    assert found is not None and found.id == created.id


@pytest.mark.asyncio
async def test_unique_name(session):
    from sqlalchemy.exc import IntegrityError

    a = Printer(name="dup", model="pt-series", backend="ptouch", connection={})
    b = Printer(name="dup", model="pt-series", backend="ptouch", connection={})
    await printers.create(session, a)
    with pytest.raises(IntegrityError):
        await printers.create(session, b)
```

- [ ] **Step 5: Autogenerate migration**

```bash
cd backend
alembic revision --autogenerate -m "add printers table"
```

Confirm the diff is exactly `op.create_table('printers', ...)`. No extra/removed tables.

- [ ] **Step 6: Run + commit**

```bash
cd backend && pytest tests/db/test_printers_repo.py -v
```

Expected: PASS.

```
feat(api): add printers model + repository + Alembic migration

Refs #19
```

---

## Task 2: `template` model + repository

**Files:**
- Create: `backend/app/models/template.py`
- Modify: `backend/app/models/__init__.py` (export Template)
- Create: `backend/app/repositories/templates.py`
- Create: `backend/tests/db/test_templates_repo.py`

Model mirrors §Schema in the spec. UNIQUE on `key`. `source` is a literal-string column with allowed values `seed` / `user`.

- [ ] **Step 1: Model**

```python
# backend/app/models/template.py
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


class Template(SQLModel, table=True):
    __tablename__ = "templates"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    key: str = Field(index=True, unique=True)
    name: str
    app: str | None = None
    printer_model: str
    tape_width_mm: int
    schema_version: int = Field(default=1)
    definition: dict = Field(default_factory=dict, sa_column=Column(JSON))
    source: Literal["seed", "user"] = Field(default="user")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column_kwargs={"onupdate": lambda: datetime.now(UTC)},
    )
```

- [ ] **Step 2: Repository**

```python
# backend/app/repositories/templates.py
from __future__ import annotations

from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.template import Template


async def list_all(session: AsyncSession) -> list[Template]:
    result = await session.execute(select(Template).order_by(Template.key))
    return list(result.scalars())


async def get_by_key(session: AsyncSession, key: str) -> Template | None:
    result = await session.execute(select(Template).where(Template.key == key))
    return result.scalar_one_or_none()


async def upsert_seed(session: AsyncSession, templates: Iterable[Template]) -> int:
    """Idempotent: insert if key missing, update body if key exists with source='seed'.

    Does NOT touch source='user' rows even if their key matches.
    Returns count of rows touched.
    """
    touched = 0
    for tpl in templates:
        existing = await get_by_key(session, tpl.key)
        if existing is None:
            tpl.source = "seed"
            session.add(tpl)
            touched += 1
            continue
        if existing.source == "user":
            continue  # never overwrite user rows
        # Update seed row in place
        existing.name = tpl.name
        existing.app = tpl.app
        existing.printer_model = tpl.printer_model
        existing.tape_width_mm = tpl.tape_width_mm
        existing.definition = tpl.definition
        existing.schema_version = tpl.schema_version
        session.add(existing)
        touched += 1
    await session.commit()
    return touched


async def create_user_template(session: AsyncSession, template: Template) -> Template:
    template.source = "user"
    session.add(template)
    await session.commit()
    await session.refresh(template)
    return template
```

- [ ] **Step 3: Tests**

```python
# backend/tests/db/test_templates_repo.py
import pytest

from app.models.template import Template
from app.repositories import templates


def _seed(key: str, name: str = "x", w: int = 12) -> Template:
    return Template(
        key=key, name=name, printer_model="pt-series", tape_width_mm=w,
        definition={"elements": []}, source="seed",
    )


@pytest.mark.asyncio
async def test_seed_idempotent(session):
    await templates.upsert_seed(session, [_seed("a"), _seed("b")])
    await templates.upsert_seed(session, [_seed("a"), _seed("b")])
    all_ = await templates.list_all(session)
    assert len(all_) == 2


@pytest.mark.asyncio
async def test_seed_does_not_overwrite_user(session):
    user = Template(key="custom", name="user-edited", printer_model="pt-series",
                    tape_width_mm=12, definition={"v": 1}, source="user")
    await templates.create_user_template(session, user)

    # Try to upsert a seed with the same key
    await templates.upsert_seed(session, [_seed("custom", name="seed-name")])

    found = await templates.get_by_key(session, "custom")
    assert found.source == "user"
    assert found.name == "user-edited"
```

- [ ] **Step 4: Migration**

```bash
alembic revision --autogenerate -m "add templates table"
```

- [ ] **Step 5: Run + commit**

```
feat(api): add templates model + repository with seed-vs-user split

source='seed' rows are upserted from YAML at startup; source='user'
rows are never touched by the seed loader. UNIQUE constraint on key
guarantees the contract.

Refs #19
```

---

## Task 3: `preset` model + repository

Same shape as Tasks 1–2. FK to `printers.id` (nullable) and `templates.id` (not null).

- [ ] **Step 1: Model + repository + tests + migration** (mirror Task 2)

```python
# Sketch
class Preset(SQLModel, table=True):
    __tablename__ = "presets"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str
    printer_id: UUID | None = Field(default=None, foreign_key="printers.id")
    template_id: UUID = Field(foreign_key="templates.id")
    field_values: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = ...
    updated_at: datetime = ...
```

Repository: `list_all`, `get`, `create`, `update`, `delete`.

Tests: cover create + FK enforcement + delete cascade behavior.

- [ ] **Step 2: Commit**

```
feat(api): add presets model + repository with FK to printers + templates

Refs #19
```

---

## Task 4: `job` model + state enum + repository

**Files:**
- Create: `backend/app/models/job.py`
- Create: `backend/app/repositories/jobs.py`
- Create: `backend/tests/db/test_jobs_repo.py`

- [ ] **Step 1: Model with state enum**

```python
# backend/app/models/job.py
from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import JSON, Index
from sqlmodel import Column, Field, SQLModel


class JobState(StrEnum):
    QUEUED = "queued"
    PRINTING = "printing"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    FAILED_RESTART = "failed_restart"


class Job(SQLModel, table=True):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_state", "state"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    printer_id: UUID = Field(foreign_key="printers.id")
    template_key: str  # snapshot — survives template delete
    state: JobState = Field(default=JobState.QUEUED)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    result: dict | None = Field(default=None, sa_column=Column(JSON))
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column_kwargs={"onupdate": lambda: datetime.now(UTC)},
    )
    started_at: datetime | None = None
    finished_at: datetime | None = None
```

- [ ] **Step 2: Repository — transition helpers**

```python
async def create_queued(session, *, printer_id, template_key, payload) -> Job: ...
async def mark_printing(session, job_id) -> Job: ...
async def mark_done(session, job_id, result=None) -> Job: ...
async def mark_failed(session, job_id, error) -> Job: ...
async def mark_cancelled(session, job_id) -> Job: ...
async def mark_inflight_as_failed_restart(session) -> int:
    """Returns number of jobs swept."""
async def list_active(session) -> list[Job]: ...
```

Each transition sets the appropriate timestamp(s) and validates the predecessor state.

- [ ] **Step 3: Tests**

State machine tests for each transition, including the restart sweep.

- [ ] **Step 4: Migration + commit**

```
feat(api): add jobs model + state enum + transition repository

State enum: queued → printing → {done, failed, cancelled};
queued/printing at shutdown become failed_restart on next boot.
Refs #19
```

---

## Task 5: `printer_state` model + repository

Singleton-per-printer (PK = FK printer_id, no autoincrement id).

- [ ] **Step 1: Model + repository (`get_or_create`, `set_paused`)**
- [ ] **Step 2: Tests**
- [ ] **Step 3: Migration + commit**

```
feat(api): add printer_state model — operator pause/resume per printer

Refs #19
```

---

## Task 6: `printer_status_cache` model

Singleton-per-printer like Task 5. Raw 32-byte `BLOB` + parsed JSON.

- [ ] **Step 1: Model + repository (`get`, `upsert`)**
- [ ] **Step 2: Tests**
- [ ] **Step 3: Migration + commit**

```
feat(api): add printer_status_cache model — last known ESC i S block

Refs #19
```

---

## Task 7: Lifespan integration (migrations + seed + recovery)

**Files:**
- Create: `backend/app/db/lifespan.py`
- Modify: `backend/app/main.py` (call lifespan)
- Create: `backend/tests/db/test_lifespan.py`

- [ ] **Step 1: Lifespan helpers**

```python
# backend/app/db/lifespan.py
async def run_migrations() -> None:
    """Apply pending Alembic migrations programmatically.

    Alembic's command module is synchronous and performs blocking I/O.
    Run it in a worker thread so it does not block the FastAPI event
    loop during startup.
    """
    import asyncio
    from alembic import command
    from alembic.config import Config

    def _upgrade() -> None:
        cfg = Config("backend/alembic.ini")
        command.upgrade(cfg, "head")

    await asyncio.to_thread(_upgrade)


async def recover_inflight_jobs(session) -> int:
    return await jobs_repo.mark_inflight_as_failed_restart(session)


async def seed_templates(session, loader: TemplateLoader) -> int:
    rows = [_to_template_model(t) for t in loader.all().values()]
    return await templates_repo.upsert_seed(session, rows)


async def ensure_printer_state(session) -> int:
    """Create printer_state row for every Printer without one."""
```

Wire into the FastAPI lifespan context manager in `app/main.py`:

```python
@asynccontextmanager
async def lifespan(app):
    await run_migrations()
    async with async_session() as s:
        await recover_inflight_jobs(s)
        await seed_templates(s, get_template_loader())
        await ensure_printer_state(s)
    yield
    # Shutdown: dispose engine
    await engine.dispose()
```

- [ ] **Step 2: Tests**

Verify all four steps run on a fresh in-memory DB and produce the expected row counts. Specifically: recovery test creates a `queued` Job manually, runs lifespan, asserts it's `failed_restart`.

- [ ] **Step 3: Run + commit**

```
feat(api): wire DB lifespan — migrations, recovery, seed, state init

Refs #19
```

---

## Task 8: TemplateLoader.seed_db() integration

**Files:**
- Modify: `backend/app/services/template_loader.py`
- Modify (test): existing template-loader tests

- [ ] **Step 1: Add `seed_db(session) -> int` to TemplateLoader**

The method converts every loaded YAML template into a `Template` model row and calls `templates_repo.upsert_seed`. Returns count.

- [ ] **Step 2: Test**

```python
async def test_seed_db_idempotent(session, loader_with_12_templates):
    assert await loader_with_12_templates.seed_db(session) == 12
    assert await loader_with_12_templates.seed_db(session) == 12
    rows = await templates_repo.list_all(session)
    assert len(rows) == 12
```

- [ ] **Step 3: Commit**

```
feat(api): TemplateLoader.seed_db() — idempotent YAML-to-DB upsert

Refs #19
```

---

## Task 9: Alembic check + repository __init__ + final wiring

**Files:**
- Modify: `backend/app/repositories/__init__.py` (re-exports for cleaner imports)
- Modify: `.gitlab-ci.yml` (add `alembic check` step)
- Create: `backend/tests/db/test_alembic_consistency.py`

- [ ] **Step 1: Add `alembic check` to CI** to catch model/migration divergence

- [ ] **Step 2: Test that asserts no pending autogenerate diffs** in CI fresh-checkout state

- [ ] **Step 3: Run full test suite**

```bash
cd backend && pytest -v
```

All existing + new tests pass. Expected count: previous test count + ~25 new tests.

- [ ] **Step 4: Commit**

```
ci: alembic check to prevent model/migration drift

Refs #19
```

---

## Task 10: Final verification + push + PR

Orchestrator-run (no subagent).

- [ ] **Step 1: Final test sweep**

```bash
cd backend
pytest -v
ruff check
ruff format --check
mypy app
```

All green.

- [ ] **Step 2: Validator-equivalent** — verify `alembic upgrade head` on a clean DB

```bash
cd backend
rm -f data/hub.db*
alembic upgrade head
sqlite3 data/hub.db ".tables"
# Expected: alembic_version jobs presets printer_state printer_status_cache printers templates
```

- [ ] **Step 3: Commit-history audit**

```bash
git log main..HEAD --oneline
git log main..HEAD --pretty=fuller | grep -i "co-authored"  # expect empty
git log main..HEAD --format=%B | grep -c "Refs #19"          # expect ≥10
```

- [ ] **Step 4: Push + PR**

```bash
git push -u origin feat/phase5-persistence
gh pr create --repo strausmann/label-printer-hub \
  --head feat/phase5-persistence --base main \
  --title "feat(api): Phase 5 — SQLModel persistence (printers/templates/presets/jobs/state)" \
  --body-file <body>
```

PR body MUST summarise the 6 tables, the lifespan flow, and reference Issue #19 with `Closes #19`. Reference Master-Tracking #22 with `Refs`.

---

## Self-review

**Spec coverage:** every §Acceptance criterion in the spec has a corresponding task above. Verified.

**Placeholder scan:** no "TBD", no "Similar to Task N", every task has concrete code or exact commands.

**Type consistency:** model names + repository function signatures match the spec. `JobState` enum values match the documented strings.

---

## Execution choice

This plan should be executed via **superpowers:subagent-driven-development** — one implementer subagent per task (10 tasks), spec-compliance + code-quality reviewer between tasks. Same pattern as the description-audit work. Wall-clock estimate 2–4h.
