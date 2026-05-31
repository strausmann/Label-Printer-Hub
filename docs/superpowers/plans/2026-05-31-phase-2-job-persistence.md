# Hub Phase 2 — Job Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist all PrintQueue Job-Lifecycle-Transitions in the SQLite `jobs` table so `GET /api/jobs/{id}` und `GET /api/batches/{id}` aktuelle Zustaende liefern, Hub-Restart Recovery sauber arbeitet und Hangar's Result-Page Live-Updates bekommt.

**Architecture:** `JobStore` Protocol mit Dependency-Injection als Boundary zwischen `PrintQueue` (in-memory Lifecycle) und `jobs`-Tabelle (DB). `SQLiteJobStore` delegiert an existierende `jobs_repo` Funktionen. Recovery rerendert Bilder aus `template_key + payload` (kein Blob in DB). Neuer `GET /api/batches/{id}` liefert Snapshot fuer Hangar Result-Page Initial-Render. `CleanupTask` raeumt terminal Jobs aelter als `PRINTER_HUB_JOB_RETENTION_DAYS` (Default 30).

**Tech Stack:** Python 3.12 + FastAPI + SQLModel + SQLAlchemy AsyncSession + Pydantic v2 + pytest + asyncio. Bestehende Codebase: `app/services/print_queue.py`, `app/services/print_service.py`, `app/repositories/jobs.py`, `app/models/job.py`.

**Spec:** [`docs/superpowers/specs/2026-05-31-phase-2-job-persistence-design.md`](../specs/2026-05-31-phase-2-job-persistence-design.md) — inklusive Errata zu Job-Klassen und Repo-Wiederverwendung.

**Branch:** `feat/phase-2-job-persistence` (existiert, mit Spec gepusht).

**Issue:** [strausmann/Label-Printer-Hub#93](https://github.com/strausmann/Label-Printer-Hub/issues/93).

**Constraints:**

- **Conventional Commits** auf Deutsch mit echten Umlauten (ae/oe/ue/ss als Quelltext-Fallback nur wenn ASCII-only Tool noetig)
- **Git Identity:** `Björn Strausmann <strausmannservices@googlemail.com>` via `-c user.name=/-c user.email=`
- **KEIN** `Co-Authored-By: Claude` in Commits
- **TDD-Pflicht:** Jeder Code-Task hat RED-Test zuerst, dann GREEN-Implementation
- **Refs-Konvention:** `Refs #93` in jedem Commit
- Bestehende **831 Tests** muessen weiter gruen bleiben — kein Breaking-Change ausser intern in `PrintQueue.__init__`

---

## File Structure

**New files:**

```
backend/app/services/job_store.py            # Protocol + Memory impl
backend/app/services/job_store_sqlite.py     # SQLite impl
backend/app/services/cleanup_task.py         # Background retention
backend/app/api/routes/batches.py            # GET /api/batches/{id}
backend/app/schemas/batch_read.py            # BatchRead + BatchSummary (separate from existing BatchRequest)
backend/tests/unit/services/test_job_store_protocol.py
backend/tests/unit/services/test_job_store_sqlite.py
backend/tests/unit/services/test_cleanup_task.py
backend/tests/integration/test_print_queue_persistence.py
backend/tests/integration/test_print_queue_recovery.py
backend/tests/integration/test_batch_snapshot_endpoint.py
```

**Modified files:**

```
backend/app/repositories/jobs.py             # +mark_printing_as_failed_restart, +evict_terminal_older_than, list_active accepts printer_id
backend/app/services/print_queue.py          # store param, recovery in start(), save() calls in worker
backend/app/services/print_service.py        # store param, create_queued before queue.submit
backend/app/main.py                          # lifespan: instantiate JobStore + CleanupTask
backend/app/config.py                        # +job_retention_days field
backend/tests/unit/services/test_print_queue_*.py    # adapt to new constructor (existing tests)
backend/tests/integration/test_batch_endpoint_happy.py  # verify DB rows now exist
```

---

## Task 1: Repository Helpers extend

**Files:**
- Modify: `backend/app/repositories/jobs.py`
- Test: `backend/tests/unit/repositories/test_jobs_phase2.py` (neu)

- [ ] **Step 1: Write the failing test**

Datei: `backend/tests/unit/repositories/test_jobs_phase2.py`

```python
"""Phase 2: neue jobs_repo Helper fuer JobStore Adapter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.models.job import Job, JobState
from app.repositories import jobs as jobs_repo


@pytest.mark.asyncio
async def test_mark_printing_as_failed_restart_only_printing(db_session):
    """mark_printing_as_failed_restart darf QUEUED-Jobs NICHT aendern."""
    printer_id = uuid4()
    other_printer_id = uuid4()

    queued = await jobs_repo.create_queued(
        db_session, printer_id=printer_id,
        template_key="t", payload={"k": "v"},
    )
    printing = await jobs_repo.create_queued(
        db_session, printer_id=printer_id,
        template_key="t", payload={"k": "v"},
    )
    await jobs_repo.mark_printing(db_session, printing.id)

    other_printing = await jobs_repo.create_queued(
        db_session, printer_id=other_printer_id,
        template_key="t", payload={"k": "v"},
    )
    await jobs_repo.mark_printing(db_session, other_printing.id)

    affected = await jobs_repo.mark_printing_as_failed_restart(
        db_session, printer_id,
    )
    assert affected == 1  # nur das eine PRINTING auf unserem printer

    await db_session.refresh(queued)
    await db_session.refresh(printing)
    await db_session.refresh(other_printing)

    assert queued.state == JobState.QUEUED.value
    assert printing.state == JobState.FAILED_RESTART.value
    assert printing.error == "printer_interrupted"
    assert printing.finished_at is not None
    assert other_printing.state == JobState.PRINTING.value  # anderer printer unangetastet


@pytest.mark.asyncio
async def test_list_active_filterable_by_printer(db_session):
    """list_active(printer_id=...) liefert nur Jobs des Druckers."""
    p1, p2 = uuid4(), uuid4()
    j1 = await jobs_repo.create_queued(db_session, printer_id=p1, template_key="t", payload={})
    j2 = await jobs_repo.create_queued(db_session, printer_id=p2, template_key="t", payload={})

    all_active = await jobs_repo.list_active(db_session)
    assert {j.id for j in all_active} == {j1.id, j2.id}

    p1_only = await jobs_repo.list_active(db_session, printer_id=p1)
    assert {j.id for j in p1_only} == {j1.id}


@pytest.mark.asyncio
async def test_evict_terminal_older_than(db_session):
    """evict loescht DONE/FAILED/CANCELLED/FAILED_RESTART aelter als age."""
    printer_id = uuid4()
    old_done = await jobs_repo.create_queued(db_session, printer_id=printer_id, template_key="t", payload={})
    await jobs_repo.mark_done(db_session, old_done.id, result={})
    # backdate finished_at by hand for test
    old_done.finished_at = datetime.now(UTC) - timedelta(days=35)
    await db_session.commit()

    young_done = await jobs_repo.create_queued(db_session, printer_id=printer_id, template_key="t", payload={})
    await jobs_repo.mark_done(db_session, young_done.id, result={})  # finished_at is now()

    queued = await jobs_repo.create_queued(db_session, printer_id=printer_id, template_key="t", payload={})  # not terminal

    deleted = await jobs_repo.evict_terminal_older_than(db_session, age=timedelta(days=30))
    assert deleted == 1

    assert await jobs_repo.get(db_session, old_done.id) is None
    assert await jobs_repo.get(db_session, young_done.id) is not None
    assert await jobs_repo.get(db_session, queued.id) is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd backend && pytest tests/unit/repositories/test_jobs_phase2.py -v
```
Expected: FAIL `AttributeError: module 'app.repositories.jobs' has no attribute 'mark_printing_as_failed_restart'`.

- [ ] **Step 3: Add `mark_printing_as_failed_restart` to repo**

Datei: `backend/app/repositories/jobs.py` — am Ende anhaengen, nach `mark_inflight_as_failed_restart`:

```python
async def mark_printing_as_failed_restart(
    session: AsyncSession,
    printer_id: UUID,
) -> int:
    """Phase 2: UPDATE only PRINTING jobs for a specific printer to
    FAILED_RESTART with error='printer_interrupted'.

    Used at PrintQueue.start() — QUEUED jobs are NOT affected because
    they will be re-enqueued cleanly. Only PRINTING jobs are ambiguous
    (printer may have completed before crash but Hub couldn't update DB).

    Returns the count of affected rows.
    """
    stmt = (
        update(Job)
        .where(
            col(Job.printer_id) == printer_id,
            col(Job.state) == JobState.PRINTING.value,
        )
        .values(
            state=JobState.FAILED_RESTART.value,
            error="printer_interrupted",
            finished_at=datetime.now(UTC),
        )
        .execution_options(synchronize_session="fetch")
    )
    result = await session.execute(stmt)
    await session.commit()
    return int(result.rowcount)  # type: ignore[attr-defined]
```

- [ ] **Step 4: Extend `list_active` with optional printer_id**

Replace existing `list_active` in `backend/app/repositories/jobs.py:163`:

```python
async def list_active(
    session: AsyncSession,
    *,
    printer_id: UUID | None = None,
) -> list[Job]:
    """Return all jobs in QUEUED or PRINTING state (covered by ix_jobs_state).

    Phase 2: optional printer_id filter for PrintQueue.start() recovery.
    """
    inflight = (JobState.QUEUED.value, JobState.PRINTING.value)
    stmt = (
        select(Job)
        .where(col(Job.state).in_(inflight))
        .order_by(col(Job.created_at))
    )
    if printer_id is not None:
        stmt = stmt.where(col(Job.printer_id) == printer_id)
    result = await session.execute(stmt)
    return list(result.scalars())
```

- [ ] **Step 5: Add `evict_terminal_older_than` to repo**

Anhaengen nach `list_active`:

```python
async def evict_terminal_older_than(
    session: AsyncSession,
    age: timedelta,
) -> int:
    """Phase 2 cleanup: DELETE terminal jobs older than age.

    Terminal = DONE | FAILED | FAILED_RESTART | CANCELLED.
    Comparison is on finished_at (set whenever a job leaves a non-terminal state).

    Returns the count of deleted rows.
    """
    terminal = (
        JobState.DONE.value,
        JobState.FAILED.value,
        JobState.FAILED_RESTART.value,
        JobState.CANCELLED.value,
    )
    cutoff = datetime.now(UTC) - age
    stmt = (
        delete(Job)
        .where(col(Job.state).in_(terminal))
        .where(col(Job.finished_at) < cutoff)
    )
    result = await session.execute(stmt)
    await session.commit()
    return int(result.rowcount)  # type: ignore[attr-defined]
```

- [ ] **Step 5a: Import-Zeilen in `jobs.py` ergaenzen (R2-m1)**

Oeffne `backend/app/repositories/jobs.py`. Suche den Block mit den bestehenden Imports am Dateianfang.

Bestehendes Statement `from sqlalchemy import select` ersetzen durch:

```python
from sqlalchemy import delete, select, update
```

Bestehendes Statement `from datetime import datetime` (oder `from datetime import UTC, datetime`) ersetzen durch (sofern nicht schon vollstaendig vorhanden):

```python
from datetime import UTC, datetime, timedelta
```

Sicherstellen dass `from sqlmodel import col, select, SQLModel` oder aequivalent `col` exportiert — `col` wird von `sqlmodel` re-exportiert und ist bereits in den bestehenden `list_*`-Funktionen in Gebrauch. Kein neuer Import noetig, nur `delete` + `update` zur `sqlalchemy`-Zeile hinzufuegen.

- [ ] **Step 6: Run tests to verify they pass**

Run:
```bash
cd backend && pytest tests/unit/repositories/test_jobs_phase2.py -v
```
Expected: 3 PASS.

- [ ] **Step 7: Run full unit-test suite — no regressions**

Run:
```bash
cd backend && pytest tests/unit/ -q
```
Expected: alle gruen.

- [ ] **Step 8: Commit**

```bash
git add backend/app/repositories/jobs.py backend/tests/unit/repositories/test_jobs_phase2.py
git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" commit -m "feat(repo): jobs_repo Helper fuer Phase 2 JobStore

- mark_printing_as_failed_restart(printer_id) — nur PRINTING affected
- list_active(printer_id=None) — optionaler Filter
- evict_terminal_older_than(age) — Cleanup-Helper

Refs #93"
```

---

## Task 2: JobStore Protocol + MemoryJobStore

**Files:**
- Create: `backend/app/services/job_store.py`
- Test: `backend/tests/unit/services/test_job_store_memory.py`

- [ ] **Step 1: Write the failing test**

Datei: `backend/tests/unit/services/test_job_store_memory.py`

```python
"""MemoryJobStore Protocol-Conformance Tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.models.job import Job, JobState
from app.services.job_store import JobStore, MemoryJobStore


def _make_job(printer_id, state=JobState.QUEUED, finished_at=None):
    return Job(
        printer_id=printer_id,
        template_key="t",
        payload={},
        state=state.value,
        finished_at=finished_at,
    )


@pytest.mark.asyncio
async def test_memory_store_save_and_get_round_trip():
    store = MemoryJobStore()
    job = _make_job(uuid4())
    await store.save_queued(job)
    fetched = await store.get(job.id)
    assert fetched is job


@pytest.mark.asyncio
async def test_memory_store_implements_protocol():
    store = MemoryJobStore()
    assert isinstance(store, JobStore)


@pytest.mark.asyncio
async def test_memory_store_mark_interrupted_only_printing():
    store = MemoryJobStore()
    p1 = uuid4()
    queued = _make_job(p1, state=JobState.QUEUED)
    printing = _make_job(p1, state=JobState.PRINTING)
    await store.save_queued(queued)
    await store.save_queued(printing)

    affected = await store.mark_interrupted(p1)
    assert affected == 1
    assert (await store.get(queued.id)).state == JobState.QUEUED.value
    interrupted = await store.get(printing.id)
    assert interrupted.state == JobState.FAILED_RESTART.value
    assert interrupted.error == "printer_interrupted"
    assert interrupted.finished_at is not None


@pytest.mark.asyncio
async def test_memory_store_list_pending_returns_queued_and_paused_not_terminal():
    store = MemoryJobStore()
    p1, p2 = uuid4(), uuid4()
    q1 = _make_job(p1, state=JobState.QUEUED)
    pr1 = _make_job(p1, state=JobState.PRINTING)
    d1 = _make_job(p1, state=JobState.DONE)
    q2 = _make_job(p2, state=JobState.QUEUED)
    for j in (q1, pr1, d1, q2):
        await store.save_queued(j)

    p1_pending = await store.list_pending(p1)
    assert {j.id for j in p1_pending} == {q1.id, pr1.id}


@pytest.mark.asyncio
async def test_memory_store_evict_terminal_older_than():
    store = MemoryJobStore()
    old = _make_job(uuid4(), state=JobState.DONE, finished_at=datetime.now(UTC) - timedelta(days=40))
    young = _make_job(uuid4(), state=JobState.DONE, finished_at=datetime.now(UTC) - timedelta(days=5))
    queued = _make_job(uuid4(), state=JobState.QUEUED)
    for j in (old, young, queued):
        await store.save_queued(j)

    deleted = await store.evict_terminal_older_than(timedelta(days=30))
    assert deleted == 1
    assert await store.get(old.id) is None
    assert await store.get(young.id) is not None
    assert await store.get(queued.id) is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd backend && pytest tests/unit/services/test_job_store_memory.py -v
```
Expected: FAIL `ModuleNotFoundError: No module named 'app.services.job_store'`.

- [ ] **Step 3: Create JobStore Protocol + MemoryJobStore**

**Wichtig (R2-C1):** `job_store.py` importiert `from app.models.job import Job, JobState` — das
ist der **SQLModel-DB-Job** aus `app/models/job.py` (UUID-id, `template_key`, `payload: dict`).
**NICHT** `app.services.job_lifecycle.Job` (Dataclass mit `image_payload`, `_done_event`).
Der Worker bridged via `str(job.id)` (Dataclass-id ist str) → `UUID(job.id)` im Store-Call.

Datei: `backend/app/services/job_store.py`

```python
"""Phase 2: JobStore Protocol + MemoryJobStore in-memory Implementation.

JobStore is the persistence boundary that PrintQueue uses to save job
state transitions. SQLiteJobStore (production) implements this Protocol
by delegating to jobs_repo. MemoryJobStore is the test/migration impl.

Klärung (R2-C1): Alle Store-Methoden arbeiten auf app.models.job.Job
(SQLModel, UUID-id). Der Worker-Code in print_queue.py verwendet
app.services.job_lifecycle.Job (Dataclass, str-id). Bridge:
  worker ruft self._store.mark_printing(str(job.id))
  Store konvertiert intern: UUID(job_id_str)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable
from uuid import UUID

from app.models.job import Job, JobState

_NON_TERMINAL = (JobState.QUEUED.value, JobState.PRINTING.value)
_TERMINAL = (
    JobState.DONE.value,
    JobState.FAILED.value,
    JobState.FAILED_RESTART.value,
    JobState.CANCELLED.value,
)


@runtime_checkable
class JobStore(Protocol):
    """Persistente Backing-Store fuer Jobs.

    All methods are async and may perform I/O. Implementations must be
    safe to call from multiple asyncio tasks concurrently.
    """

    async def save_queued(self, job: Job) -> None:
        """Persist a newly-created QUEUED job (insert).

        Called from PrintService.submit_print_job BEFORE handing off
        to the queue. After this returns, the job is durable.
        """

    async def get(self, job_id: UUID) -> Job | None:
        """Load a job by ID. None if not found."""

    async def mark_printing(self, job_id: UUID) -> None:
        """Transition QUEUED -> PRINTING. Called by worker when it picks up the job."""

    async def mark_done(self, job_id: UUID) -> None:
        """Transition PRINTING -> DONE. Called by worker after successful print."""

    async def mark_failed(self, job_id: UUID, error: str) -> None:
        """Transition any non-terminal -> FAILED with given error message."""

    async def mark_interrupted(self, printer_id: UUID) -> int:
        """Recovery: set all PRINTING jobs of this printer to FAILED_RESTART
        with error='printer_interrupted'.

        Called from PrintQueue.start() BEFORE list_pending.

        Returns the count of affected rows.
        """

    async def list_pending(self, printer_id: UUID) -> list[Job]:
        """Return all non-terminal jobs for this printer, sorted by created_at (FIFO).

        Called from PrintQueue.start() AFTER mark_interrupted to find
        QUEUED jobs that need to be re-enqueued.
        """

    async def evict_terminal_older_than(self, age: timedelta) -> int:
        """Delete terminal jobs (DONE/FAILED/FAILED_RESTART/CANCELLED) with
        finished_at older than `age` ago. Used by CleanupTask.

        Returns the count of deleted rows.
        """


class MemoryJobStore(JobStore):
    """In-Memory JobStore for tests and PrintService boot-phase.

    Holds Job objects in a dict keyed by id. Not thread-safe but
    safe for single-event-loop asyncio use.
    """

    def __init__(self) -> None:
        self._jobs: dict[UUID, Job] = {}

    async def save_queued(self, job: Job) -> None:
        self._jobs[job.id] = job

    async def get(self, job_id: UUID) -> Job | None:
        return self._jobs.get(job_id)

    async def mark_printing(self, job_id: UUID) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.state = JobState.PRINTING.value
        job.started_at = datetime.now(UTC)

    async def mark_done(self, job_id: UUID) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.state = JobState.DONE.value
        job.finished_at = datetime.now(UTC)

    async def mark_failed(self, job_id: UUID, error: str) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.state = JobState.FAILED.value
        job.error = error
        job.finished_at = datetime.now(UTC)

    async def mark_interrupted(self, printer_id: UUID) -> int:
        count = 0
        for job in self._jobs.values():
            if job.printer_id == printer_id and job.state == JobState.PRINTING.value:
                job.state = JobState.FAILED_RESTART.value
                job.error = "printer_interrupted"
                job.finished_at = datetime.now(UTC)
                count += 1
        return count

    async def list_pending(self, printer_id: UUID) -> list[Job]:
        items = [
            j for j in self._jobs.values()
            if j.printer_id == printer_id and j.state in _NON_TERMINAL
        ]
        return sorted(items, key=lambda j: j.created_at)

    async def evict_terminal_older_than(self, age: timedelta) -> int:
        cutoff = datetime.now(UTC) - age
        to_delete = [
            jid for jid, j in self._jobs.items()
            if j.state in _TERMINAL and j.finished_at is not None and j.finished_at < cutoff
        ]
        for jid in to_delete:
            del self._jobs[jid]
        return len(to_delete)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd backend && pytest tests/unit/services/test_job_store_memory.py -v
```
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/job_store.py backend/tests/unit/services/test_job_store_memory.py
git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" commit -m "feat(services): JobStore Protocol + MemoryJobStore (Phase 2)

JobStore ist die Persistierungs-Boundary die PrintQueue nutzt um
Lifecycle-Transitionen zu speichern. MemoryJobStore ist die Test-Impl
mit gleicher Semantik wie spaeterer SQLiteJobStore.

Refs #93"
```

---

## Task 3: SQLiteJobStore

**Files:**
- Create: `backend/app/services/job_store_sqlite.py`
- Test: `backend/tests/unit/services/test_job_store_sqlite.py`

- [ ] **Step 1: Write the failing test**

Datei: `backend/tests/unit/services/test_job_store_sqlite.py`

```python
"""SQLiteJobStore Protocol-Conformance Tests gegen echte SQLite-Session."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.models.job import Job, JobState
from app.services.job_store import JobStore
from app.services.job_store_sqlite import SQLiteJobStore


@pytest.mark.asyncio
async def test_sqlite_store_implements_protocol(async_session_factory):
    store = SQLiteJobStore(async_session_factory)
    assert isinstance(store, JobStore)


@pytest.mark.asyncio
async def test_sqlite_store_save_and_get_round_trip(async_session_factory):
    store = SQLiteJobStore(async_session_factory)
    printer_id = uuid4()
    job = Job(printer_id=printer_id, template_key="t", payload={"foo": "bar"})
    await store.save_queued(job)
    fetched = await store.get(job.id)
    assert fetched is not None
    assert fetched.id == job.id
    assert fetched.payload == {"foo": "bar"}
    assert fetched.state == JobState.QUEUED.value


@pytest.mark.asyncio
async def test_sqlite_store_mark_transitions(async_session_factory):
    store = SQLiteJobStore(async_session_factory)
    job = Job(printer_id=uuid4(), template_key="t", payload={})
    await store.save_queued(job)

    await store.mark_printing(job.id)
    fetched = await store.get(job.id)
    assert fetched.state == JobState.PRINTING.value
    assert fetched.started_at is not None

    await store.mark_done(job.id)
    fetched = await store.get(job.id)
    assert fetched.state == JobState.DONE.value
    assert fetched.finished_at is not None


@pytest.mark.asyncio
async def test_sqlite_store_mark_failed(async_session_factory):
    store = SQLiteJobStore(async_session_factory)
    job = Job(printer_id=uuid4(), template_key="t", payload={})
    await store.save_queued(job)
    await store.mark_printing(job.id)

    await store.mark_failed(job.id, "tape_empty")
    fetched = await store.get(job.id)
    assert fetched.state == JobState.FAILED.value
    assert fetched.error == "tape_empty"
    assert fetched.finished_at is not None


@pytest.mark.asyncio
async def test_sqlite_store_mark_interrupted_only_printing(async_session_factory):
    store = SQLiteJobStore(async_session_factory)
    p1 = uuid4()
    queued = Job(printer_id=p1, template_key="t", payload={})
    printing = Job(printer_id=p1, template_key="t", payload={})
    await store.save_queued(queued)
    await store.save_queued(printing)
    await store.mark_printing(printing.id)

    affected = await store.mark_interrupted(p1)
    assert affected == 1

    q = await store.get(queued.id)
    p = await store.get(printing.id)
    assert q.state == JobState.QUEUED.value
    assert p.state == JobState.FAILED_RESTART.value
    assert p.error == "printer_interrupted"


@pytest.mark.asyncio
async def test_sqlite_store_list_pending_fifo(async_session_factory):
    store = SQLiteJobStore(async_session_factory)
    p1 = uuid4()
    j1 = Job(printer_id=p1, template_key="t", payload={"order": 1})
    await store.save_queued(j1)
    j2 = Job(printer_id=p1, template_key="t", payload={"order": 2})
    await store.save_queued(j2)
    # Note: SQLModel sets created_at via default_factory at construction;
    # tests rely on save order matching id assignment via uuid.

    pending = await store.list_pending(p1)
    assert [j.id for j in pending] == [j1.id, j2.id]


@pytest.mark.asyncio
async def test_sqlite_store_evict_terminal_older_than(async_session_factory):
    store = SQLiteJobStore(async_session_factory)
    p1 = uuid4()
    old = Job(printer_id=p1, template_key="t", payload={})
    young = Job(printer_id=p1, template_key="t", payload={})
    queued = Job(printer_id=p1, template_key="t", payload={})
    await store.save_queued(old)
    await store.mark_printing(old.id)
    await store.mark_done(old.id)
    # backdate finished_at
    async with async_session_factory() as s:
        fetched = await s.get(Job, old.id)
        fetched.finished_at = datetime.now(UTC) - timedelta(days=40)
        await s.commit()

    await store.save_queued(young)
    await store.mark_printing(young.id)
    await store.mark_done(young.id)
    await store.save_queued(queued)

    deleted = await store.evict_terminal_older_than(timedelta(days=30))
    assert deleted == 1
    assert await store.get(old.id) is None
    assert await store.get(young.id) is not None
    assert await store.get(queued.id) is not None
```

`async_session_factory` ist eine bestehende Fixture aus `tests/integration/conftest.py` — falls in `unit/services/conftest.py` nicht vorhanden, kopiere die Definition.

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd backend && pytest tests/unit/services/test_job_store_sqlite.py -v
```
Expected: FAIL `ModuleNotFoundError: No module named 'app.services.job_store_sqlite'`.

- [ ] **Step 3: Create SQLiteJobStore**

Datei: `backend/app/services/job_store_sqlite.py`

```python
"""SQLite-backed JobStore — delegates to jobs_repo for actual SQL.

Uses async_sessionmaker for per-operation sessions so we get clean
transactions and no connection-pool starvation.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.job import Job
from app.repositories import jobs as jobs_repo
from app.services.job_store import JobStore


class SQLiteJobStore(JobStore):
    """SQLite-backed JobStore implementation."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def save_queued(self, job: Job) -> None:
        async with self._session_factory() as session:
            session.add(job)
            await session.commit()
            await session.refresh(job)

    async def get(self, job_id: UUID) -> Job | None:
        async with self._session_factory() as session:
            return await jobs_repo.get(session, job_id)

    async def mark_printing(self, job_id: UUID) -> None:
        async with self._session_factory() as session:
            await jobs_repo.mark_printing(session, job_id)

    async def mark_done(self, job_id: UUID) -> None:
        async with self._session_factory() as session:
            await jobs_repo.mark_done(session, job_id, result={})

    async def mark_failed(self, job_id: UUID, error: str) -> None:
        async with self._session_factory() as session:
            await jobs_repo.mark_failed(session, job_id, error)

    async def mark_interrupted(self, printer_id: UUID) -> int:
        async with self._session_factory() as session:
            return await jobs_repo.mark_printing_as_failed_restart(
                session, printer_id,
            )

    async def list_pending(self, printer_id: UUID) -> list[Job]:
        async with self._session_factory() as session:
            return await jobs_repo.list_active(session, printer_id=printer_id)

    async def evict_terminal_older_than(self, age: timedelta) -> int:
        async with self._session_factory() as session:
            return await jobs_repo.evict_terminal_older_than(session, age)
```

- [ ] **Step 4: Add async_session_factory fixture to root conftest (OBLIGATORISCH — R2-C2+M8)**

**NICHT** in `tests/unit/services/conftest.py` eintragen! Die Fixture muss in
`backend/tests/conftest.py` (Root-Level) definiert werden, damit sie sowohl von
Unit-Tests (Task 3) als auch von Integration-Tests (Task 6 `test_print_queue_recovery.py`)
sichtbar ist. pytest-conftest-Sichtbarkeit: eine conftest.py gilt nur für Tests im gleichen
Verzeichnis und darunter.

Die bestehende `tests/integration/conftest.py` hat eine `db_session`-Fixture (einzelne
AsyncSession), aber **keine** `async_sessionmaker`-Fixture namens `async_session_factory`.
Die `tests/unit/services/conftest.py` hat ebenfalls keine solche Fixture.

Füge folgendes in `backend/tests/conftest.py` ein (nach den bestehenden `pytest_addoption`/
`pytest_collection_modifyitems` Funktionen):

```python
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel


@pytest_asyncio.fixture
async def async_session_factory(tmp_path):
    """Async sessionmaker-Fixture für SQLiteJobStore Tests.

    Erzeugt eine per-Test SQLite-DB (temp file, nicht :memory: für
    Task-Isolation). Sichtbar für alle Tests unterhalb von tests/.
    """
    db_path = tmp_path / "job_store_test.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(url, echo=False, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()
```

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
cd backend && pytest tests/unit/services/test_job_store_sqlite.py -v
```
Expected: 7 PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/job_store_sqlite.py backend/tests/unit/services/test_job_store_sqlite.py backend/tests/unit/services/conftest.py
git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" commit -m "feat(services): SQLiteJobStore delegiert an jobs_repo (Phase 2)

Per-operation Sessions via async_sessionmaker. Implementiert das
gleiche JobStore Protocol wie MemoryJobStore — Protocol-Conformance
durch isinstance-Check verifiziert.

Refs #93"
```

---

## Task 4: PrintQueue Refactor — store dependency + worker-saves

**Files:**
- Modify: `backend/app/services/print_queue.py:140-180` (Konstruktor + start())
- Modify: `backend/app/services/print_queue.py:516-560` (Worker-Loop)
- Test: `backend/tests/unit/services/test_print_queue_persistence.py` (neu)

- [ ] **Step 1: Write the failing test**

Datei: `backend/tests/unit/services/test_print_queue_persistence.py`

```python
"""PrintQueue must call store.mark_* on every state transition."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.models.job import Job, JobState
from app.services.job_store import MemoryJobStore
from app.services.print_queue import PrintQueue


@pytest.mark.asyncio
async def test_printqueue_constructor_accepts_store(mock_backend_factory, event_bus):
    """PrintQueue requires a JobStore in constructor."""
    store = MemoryJobStore()
    queue = PrintQueue(
        printer_ids=[uuid4()],
        backend_factory=mock_backend_factory,
        bus=event_bus,
        store=store,
    )
    assert queue._store is store


@pytest.mark.asyncio
async def test_printqueue_calls_mark_printing_then_mark_done(
    mock_backend_factory, event_bus, sample_image,
):
    """Worker must call store.mark_printing then store.mark_done on success."""
    store = AsyncMock(spec=MemoryJobStore)
    printer_id = uuid4()
    queue = PrintQueue(
        printer_ids=[printer_id],
        backend_factory=mock_backend_factory,
        bus=event_bus,
        store=store,
    )
    await queue.start()
    job_id = await queue.submit(printer_id, sample_image, tape_mm=12)
    await queue.wait_for_job(job_id)
    await queue.stop()

    store.mark_printing.assert_awaited_once_with(job_id)
    store.mark_done.assert_awaited_once_with(job_id)
    store.mark_failed.assert_not_awaited()
```

Helper-Fixtures `mock_backend_factory`, `event_bus`, `sample_image` existieren bereits in `tests/unit/services/conftest.py` (siehe bestehende `print_queue` tests). Falls nicht: anlegen analog zu bestehenden Tests.

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd backend && pytest tests/unit/services/test_print_queue_persistence.py -v
```
Expected: FAIL `TypeError: __init__() got an unexpected keyword argument 'store'`.

- [ ] **Step 3: Add `store` parameter to PrintQueue.__init__**

In `backend/app/services/print_queue.py` finde den `__init__`. Aktuelle Signatur enthaelt `bus`. Erweitere um `store`:

```python
def __init__(
    self,
    printer_ids: list[UUID],
    backend_factory: Callable[[UUID], PrinterBackend],
    bus: EventBus,
    store: JobStore,  # NEU
) -> None:
    self._store = store
    # ... rest unveraendert ...
```

Import oben in `print_queue.py`:
```python
from app.services.job_store import JobStore
```

- [ ] **Step 4: Add store.mark_printing/mark_done/mark_failed calls in worker (R2-C3)**

**KEIN** vereinfachter Pseudocode-Skelett — verwende die echte Datei-Struktur.
Zeilennummern beziehen sich auf `backend/app/services/print_queue.py` (Stand Branch-Basis):

**Insert 1 — nach Zeile ~513 (`if job.state != JobState.QUEUED: continue`):**
Zwischen Skip-Check und `try:`-Block, direkt VOR `_from = job.state`:

```python
        # Phase 2: Skip-Check MUSS vor mark_printing bleiben (R2-C3, Spec R1-C3)
        if job.state != JobState.QUEUED:
            continue

        # Phase 2: DB-State QUEUED->PRINTING persistieren (bridge: dataclass.id ist str)
        await self._store.mark_printing(job.id)

        try:
            _from = job.state
            JobStateMachine.transition(job, JobState.PRINTING)
```

**Insert 2 — PRINTING->COMPLETED (nach `JobStateMachine.transition(job, JobState.COMPLETED)`, ca. Zeile 534):**

```python
            JobStateMachine.transition(job, JobState.COMPLETED)
            await self._store.mark_done(job.id)   # Phase 2: DB-State persistieren
            self._notify_state_change(
```

**Insert 3 — PrinterError Handler (nach `JobStateMachine.transition(job, JobState.FAILED)`, ca. Zeile 553):**

```python
                except InvalidStateTransitionError:
                    logger.warning(...)
                # Phase 2: DB-State persistieren
                await self._store.mark_failed(job.id, f"{code}: {msg}")
                logger.exception("Job %s failed on %s (printer error)", ...)
```

**Insert 4 — Generic Exception Handler (nach `JobStateMachine.transition(job, JobState.FAILED)`, ca. Zeile 577):**

```python
                except InvalidStateTransitionError:
                    logger.warning(...)
                # Phase 2: DB-State persistieren
                await self._store.mark_failed(job.id, str(exc))
                logger.exception("Job %s failed on %s", ...)
```

**Bewahre vollständig:**
- SNMP-Preflight Checks (`job.tape_mm is None`, `job.image_payload is None`)
- Pause-Logik (`while self._worker_states[...] == PrinterWorkerState.PAUSED`)
- Differenzierte PrinterError vs. Exception Handler inkl. `_RECOVERABLE_PRINTER_ERRORS` pause_printer-Call
- `asyncio.CancelledError` re-raise
- `_notify_state_change` Calls an allen Transitionen

Kein `queue.task_done()` — der reale Worker ruft das nicht auf.

- [ ] **Step 5: Run existing print_queue tests — adapt SOFORT nach Konstruktor-Änderung (R2-M1)**

**Reihenfolge (R2-M1):** Bestehende Tests adapten DIREKT NACH Step 3, BEVOR neuer Test grün gemacht wird.
Nach Step 3 schlägt die Suite mit `TypeError: __init__() got unexpected keyword argument` fehl —
das muss zuerst behoben werden.

Run:
```bash
cd backend && pytest tests/unit/services/ -k print_queue -v
```
Adapte alle bestehenden `PrintQueue(...)` Aufrufe in Tests indem `store=MemoryJobStore()` ergänzt wird.
Nutze `grep -r "PrintQueue(" tests/` um alle Stellen zu finden.

Expected danach: bestehende Tests wieder grün.

- [ ] **Step 6: Run new unit test to verify it passes**

Run:
```bash
cd backend && pytest tests/unit/services/test_print_queue_persistence.py -v
```
Expected: 2 PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/print_queue.py backend/tests/unit/services/
git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" commit -m "feat(queue): PrintQueue ruft JobStore bei jeder State-Transition (Phase 2)

QUEUED -> PRINTING -> DONE/FAILED wird synchron in der DB persistiert.
Konstruktor bekommt store: JobStore als neuen Pflicht-Parameter.

Refs #93"
```

---

## Task 5: PrintService bekommt JobStore + create_queued vor queue.submit

**Files:**
- Modify: `backend/app/services/print_service.py:67-110`
- Test: `backend/tests/integration/test_print_service_persistence.py` (neu)

- [ ] **Step 1: Write the failing test**

Datei: `backend/tests/integration/test_print_service_persistence.py`

```python
"""PrintService must persist Job-row BEFORE handing off to PrintQueue."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.models.job import JobState
from app.schemas.print_request import PrintRequest


@pytest.mark.asyncio
async def test_submit_persists_queued_job_before_queue(
    print_service, sqlite_store, sample_request,
):
    """After submit_print_job, the job must exist in DB with state=QUEUED."""
    job_id = await print_service.submit_print_job(sample_request)
    persisted = await sqlite_store.get(job_id)
    assert persisted is not None
    assert persisted.state == JobState.QUEUED.value
    assert persisted.template_key == sample_request.template_id
    assert persisted.printer_id == print_service._printer_id
```

(Helper fixtures `print_service`, `sqlite_store`, `sample_request` definieren in dieser Test-Datei oder conftest.)

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd backend && pytest tests/integration/test_print_service_persistence.py -v
```
Expected: FAIL — entweder `AttributeError: PrintService has no attribute '_store'` oder `assert persisted is None`.

- [ ] **Step 3: Refactor PrintService**

In `backend/app/services/print_service.py` finde `__init__`. Ergaenze `store: JobStore` Parameter:

```python
def __init__(
    self,
    printer_id: UUID,
    queue: PrintQueue,
    renderer: LabelRenderer,
    loader: TemplateLoader,
    backend: PrinterBackend,
    store: JobStore,  # NEU
) -> None:
    self._printer_id = printer_id
    self._queue = queue
    self._renderer = renderer
    self._loader = loader
    self._backend = backend
    self._store = store  # NEU
```

Imports oben:
```python
from app.models.job import Job
from app.services.job_store import JobStore
```

In `submit_print_job` ersetze die letzte Zeile (`return await self._queue.submit(...)`) durch:

```python
# Render bleibt unveraendert ...
label_data = await self._resolve_label_data(request)
image = self._renderer.render(template, label_data)

# Phase 2: Persist BEFORE queue.submit
# R2-M3: PrintRequest (app/schemas/print_request.py) hat KEINE api_key_id/source_ip Felder.
# Diese kommen aus AuthContext (auth.api_key_id, auth.ip) — der Endpoint-Layer muss
# submit_print_job(request, auth_context) erweitern oder PrintService bekommt auth_context.
# Bis zur Klärung: None setzen, KEIN hasattr-Workaround.
db_job = Job(
    printer_id=self._printer_id,
    template_key=request.template_id,
    payload={
        "label_data": label_data.model_dump(),
        "tape_mm": template.tape_mm,
        "options": {
            "auto_cut": request.options.auto_cut,
            "high_resolution": request.options.high_resolution,
        },
    },
    api_key_id=None,    # TODO: aus AuthContext übergeben wenn Endpoint-Layer angepasst
    source_ip=None,     # TODO: aus AuthContext übergeben wenn Endpoint-Layer angepasst
)
await self._store.save_queued(db_job)

# Hand off to queue with the DB id
await self._queue.submit_with_id(
    db_job.id,
    self._printer_id,
    image,
    tape_mm=template.tape_mm,
    auto_cut=request.options.auto_cut,
    high_resolution=request.options.high_resolution,
)
return db_job.id
```

Analog `on_tape_mismatch="queue"` Pfad: `submit_paused_with_id` aufrufen mit `db_job.id` und vorher `store.save_queued`.

- [ ] **Step 4: Add `submit_with_id` to PrintQueue**

In `backend/app/services/print_queue.py` ergaenze nach existierendem `submit`:

```python
async def submit_with_id(
    self,
    job_id: UUID,
    printer_id: UUID,
    image: Image.Image,
    tape_mm: int,
    **options: Any,
) -> str:
    """Phase 2: like submit(), but uses an externally-generated job_id.

    Used by PrintService which creates the DB-row first (via store.save_queued)
    and passes the resulting id here.
    """
    if printer_id not in self._queues:
        raise KeyError(f"Unknown printer: {printer_id}")
    payload = await asyncio.to_thread(_serialize_image_to_png, image)
    job = Job(  # dataclass
        id=str(job_id),
        printer_id=printer_id,
        image_payload=payload,
        tape_mm=tape_mm,
        options=dict(options),
    )
    self._jobs[str(job_id)] = job  # ... oder bei Phase-2-Refactor: nur Queue.put
    await self._queues[printer_id].put(job)
    return str(job_id)
```

Analog `submit_paused_with_id` falls noetig.

- [ ] **Step 5: Update PrintService instantiation in lifespan**

In `backend/app/main.py` finde wo `PrintService` instantiiert wird. Ergaenze `store=job_store` (wird in Task 7 vollstaendig gewired — hier nur Parameter durchreichen).

- [ ] **Step 6: Run integration test to verify it passes**

Run:
```bash
cd backend && pytest tests/integration/test_print_service_persistence.py -v
```
Expected: PASS.

- [ ] **Step 7: Run existing PrintService tests — adapt**

Run:
```bash
cd backend && pytest tests/integration/ -k print_service -v
```
Adapte bestehende `PrintService(...)` constructor-Aufrufe (test-fixtures) um `store=MemoryJobStore()` zu uebergeben.

Expected: alle gruen.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/print_service.py backend/app/services/print_queue.py backend/tests/integration/test_print_service_persistence.py
git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" commit -m "feat(service): PrintService persistiert Job-Row vor queue.submit (Phase 2)

Neue submit_with_id() in PrintQueue erlaubt extern-generierte job_id.
PrintService legt erst die DB-Row an (store.save_queued) und reicht die
id durch — Hand-off ist atomisch und persistiert.

Refs #93"
```

---

## Task 6: PrintQueue Recovery in start()

**Files:**
- Modify: `backend/app/services/print_queue.py` — `start()` method
- Test: `backend/tests/integration/test_print_queue_recovery.py` (neu)

- [ ] **Step 1: Write the failing test**

Datei: `backend/tests/integration/test_print_queue_recovery.py`

```python
"""PrintQueue.start() must recover pending jobs from DB."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.models.job import Job, JobState
from app.services.job_store_sqlite import SQLiteJobStore
from app.services.print_queue import PrintQueue


@pytest.mark.asyncio
async def test_start_marks_printing_as_failed_restart(
    async_session_factory, mock_backend_factory, event_bus,
):
    """Jobs in PRINTING before start() must be marked FAILED_RESTART."""
    store = SQLiteJobStore(async_session_factory)
    printer_id = uuid4()

    # Pre-seed: a job in PRINTING state
    interrupted_job = Job(
        printer_id=printer_id, template_key="t", payload={},
        state=JobState.PRINTING.value,
    )
    await store.save_queued(interrupted_job)
    # Force PRINTING state manually (since save_queued always sets QUEUED)
    async with async_session_factory() as s:
        from sqlalchemy import update   # R2-M4: update kommt aus sqlalchemy, NICHT sqlmodel
        from sqlmodel import col
        await s.execute(
            update(Job).where(col(Job.id) == interrupted_job.id).values(
                state=JobState.PRINTING.value,
            )
        )
        await s.commit()

    queue = PrintQueue(
        printer_ids=[printer_id],
        backend_factory=mock_backend_factory,
        bus=event_bus,
        store=store,
    )
    await queue.start()

    fetched = await store.get(interrupted_job.id)
    assert fetched.state == JobState.FAILED_RESTART.value
    assert fetched.error == "printer_interrupted"

    await queue.stop()


@pytest.mark.asyncio
async def test_start_reenqueues_queued_jobs_in_fifo_order(
    async_session_factory, mock_backend_factory, event_bus,
):
    """Jobs in QUEUED state must be re-enqueued in created_at order."""
    store = SQLiteJobStore(async_session_factory)
    printer_id = uuid4()

    j1 = Job(printer_id=printer_id, template_key="t", payload={"o": 1})
    j2 = Job(printer_id=printer_id, template_key="t", payload={"o": 2})
    await store.save_queued(j1)
    await store.save_queued(j2)

    queue = PrintQueue(
        printer_ids=[printer_id],
        backend_factory=mock_backend_factory,
        bus=event_bus,
        store=store,
    )
    await queue.start()

    # asyncio.Queue order
    recovered_ids = []
    while not queue._queues[printer_id].empty():
        recovered_ids.append((await queue._queues[printer_id].get()).id)

    assert recovered_ids == [str(j1.id), str(j2.id)]
    await queue.stop()
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd backend && pytest tests/integration/test_print_queue_recovery.py -v
```
Expected: FAIL — start() does not call recovery yet, FAILED_RESTART assertion fails.

- [ ] **Step 3: Add recovery to PrintQueue.start()**

In `backend/app/services/print_queue.py` modifiziere `start()`:

```python
async def start(self) -> None:
    if self._running:
        return

    # Phase 2 Recovery: mark interrupted PRINTING jobs + reenqueue QUEUED
    for printer_id in self._queues:
        interrupted = await self._store.mark_interrupted(printer_id)
        if interrupted > 0:
            logger.warning(
                "Recovery: %d printing jobs on printer %s marked as interrupted",
                interrupted, printer_id,
            )
        pending_db_jobs = await self._store.list_pending(printer_id)
        for db_job in pending_db_jobs:
            if db_job.state == JobState.QUEUED.value:
                # Rerender image from template_key + payload
                image = await self._rerender_from_db_job(db_job)
                payload_bytes = await asyncio.to_thread(_serialize_image_to_png, image)
                wrapper = Job(  # dataclass
                    id=str(db_job.id),
                    printer_id=db_job.printer_id,
                    image_payload=payload_bytes,
                    tape_mm=db_job.payload.get("tape_mm"),
                    options=db_job.payload.get("options", {}),
                )
                await self._queues[printer_id].put(wrapper)
                logger.info("Recovery: re-enqueued QUEUED job %s on %s",
                            db_job.id, printer_id)

    # Original Worker-Spawn
    for printer_id in self._queues:
        self._workers[printer_id] = asyncio.create_task(
            self._worker(printer_id), name=f"printer-worker-{printer_id}"
        )
    self._running = True


async def _rerender_from_db_job(self, db_job) -> Image.Image:
    """Phase 2: rerender label image from persisted template_key + payload.

    Called during start() recovery. Requires renderer + loader to be wired
    via PrintQueue constructor — see lifespan.
    """
    if self._renderer is None or self._loader is None:
        raise RuntimeError(
            "PrintQueue recovery requires renderer + loader (pass via constructor)"
        )
    template = self._loader.get(db_job.template_key)
    # R2-C4: payload["label_data"] ist ein rohes dict (model_dump()).
    # renderer.render() erwartet ein LabelData-Objekt — KEIN dict.
    from app.schemas.label_data import LabelData
    label_data = LabelData.model_validate(db_job.payload["label_data"])
    return self._renderer.render(template, label_data)
```

PrintQueue.__init__ erweitern um `renderer` und `loader` als Optional:

```python
def __init__(
    self,
    printer_ids: list[UUID],
    backend_factory: ...,
    bus: ...,
    store: JobStore,
    renderer: LabelRenderer | None = None,  # NEU, optional
    loader: TemplateLoader | None = None,   # NEU, optional
) -> None:
    # ...
    self._renderer = renderer
    self._loader = loader
```

- [ ] **Step 4: Run recovery tests to verify they pass**

Run:
```bash
cd backend && pytest tests/integration/test_print_queue_recovery.py -v
```
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/print_queue.py backend/tests/integration/test_print_queue_recovery.py
git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" commit -m "feat(queue): PrintQueue.start() Recovery (Phase 2)

mark_interrupted(printer_id) markiert verloren-gegangene PRINTING jobs
als FAILED_RESTART. QUEUED jobs werden aus template_key+payload neu
gerendert und in FIFO-Reihenfolge re-enqueued.

Refs #93"
```

---

## Task 7: CleanupTask

**Files:**
- Create: `backend/app/services/cleanup_task.py`
- Test: `backend/tests/unit/services/test_cleanup_task.py`

- [ ] **Step 1: Write the failing test**

Datei: `backend/tests/unit/services/test_cleanup_task.py`

```python
"""CleanupTask runs evict_terminal_older_than periodically."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from app.services.cleanup_task import CleanupTask


@pytest.mark.asyncio
async def test_cleanup_validates_retention_days():
    store = AsyncMock()
    with pytest.raises(ValueError, match="retention_days must be >= 1"):
        CleanupTask(store=store, retention_days=0)


@pytest.mark.asyncio
async def test_cleanup_initial_run_on_start():
    store = AsyncMock()
    store.evict_terminal_older_than.return_value = 3
    task = CleanupTask(store=store, retention_days=30, interval=timedelta(seconds=99))
    await task.start()
    # stop() wartet intern auf den laufenden Task — nach stop() ist der
    # erste evict_terminal_older_than-Call garantiert erfolgt.
    await task.stop(timeout_s=1.0)

    store.evict_terminal_older_than.assert_awaited()
    args, _ = store.evict_terminal_older_than.call_args
    assert args[0] == timedelta(days=30)


@pytest.mark.asyncio
async def test_cleanup_fail_soft_on_exception():
    store = AsyncMock()
    store.evict_terminal_older_than.side_effect = RuntimeError("boom")
    task = CleanupTask(store=store, retention_days=30, interval=timedelta(seconds=99))
    await task.start()
    await task.stop(timeout_s=1.0)
    # No exception propagated; loop survives
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd backend && pytest tests/unit/services/test_cleanup_task.py -v
```
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Create CleanupTask**

Datei: `backend/app/services/cleanup_task.py`

```python
"""Phase 2: periodic background task to delete terminal jobs older than retention_days."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from app.services.job_store import JobStore

logger = logging.getLogger(__name__)

_DEFAULT_INTERVAL = timedelta(hours=24)


class CleanupTask:
    """Background asyncio task that periodically calls
    store.evict_terminal_older_than(retention).
    """

    def __init__(
        self,
        store: JobStore,
        retention_days: int,
        interval: timedelta = _DEFAULT_INTERVAL,
    ) -> None:
        if retention_days < 1:
            raise ValueError("retention_days must be >= 1")
        self._store = store
        self._retention = timedelta(days=retention_days)
        self._interval = interval
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._loop(), name="job-cleanup")

    async def stop(self, timeout_s: float = 5.0) -> None:
        self._stopping.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=timeout_s)
            except asyncio.TimeoutError:
                self._task.cancel()
                logger.warning("CleanupTask did not stop in %ss, cancelled", timeout_s)
            self._task = None

    async def _loop(self) -> None:
        await self._run_once()
        while not self._stopping.is_set():
            try:
                await asyncio.wait_for(
                    self._stopping.wait(),
                    timeout=self._interval.total_seconds(),
                )
            except asyncio.TimeoutError:
                await self._run_once()

    async def _run_once(self) -> None:
        try:
            deleted = await self._store.evict_terminal_older_than(self._retention)
            if deleted > 0:
                logger.info(
                    "CleanupTask: deleted %d terminal jobs older than %d days",
                    deleted, self._retention.days,
                )
        except Exception:
            logger.exception("CleanupTask: run_once failed")
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd backend && pytest tests/unit/services/test_cleanup_task.py -v
```
Expected: 3 PASS.

- [ ] **Step 5: Add config field**

In `backend/app/config.py` ergaenze in `class Settings`:

```python
job_retention_days: int = Field(
    default=30,
    ge=1,
    description="Terminal Jobs (DONE/FAILED/FAILED_RESTART/CANCELLED) werden nach diesem Zeitraum vom CleanupTask geloescht",
)
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/cleanup_task.py backend/app/config.py backend/tests/unit/services/test_cleanup_task.py
git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" commit -m "feat(services): CleanupTask + PRINTER_HUB_JOB_RETENTION_DAYS config (Phase 2)

Background asyncio task laeuft initial bei start() und dann alle 24h,
ruft store.evict_terminal_older_than(retention). Fail-soft bei
DB-Errors — Loop survives.

Refs #93"
```

---

## Task 8: GET /api/batches/{batch_id} Snapshot Endpoint

**Files:**
- Create: `backend/app/schemas/batch_read.py`
- Create: `backend/app/api/routes/batches.py`
- Modify: `backend/app/repositories/jobs.py` (add `list_by_ids`)
- Modify: `backend/app/main.py` (register batches router)
- Test: `backend/tests/integration/test_batch_snapshot_endpoint.py`

- [ ] **Step 1: Write the failing test (R2-C6)**

Datei: `backend/tests/integration/test_batch_snapshot_endpoint.py`

**Wichtig (R2-C6):** Fixtures `auth_client`, `sqlite_store`, `sample_batch_done`, `batch_with_ghost_ids`
existieren NICHT in der integration conftest. Stattdessen:
- `auth_client` → **`client`** (existiert in `tests/integration/conftest.py:222`)
- `sample_batch_done` und `batch_with_ghost_ids` müssen **explizit in dieser Datei** definiert werden

```python
"""GET /api/batches/{id} liefert Snapshot mit Jobs + Summary."""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from app.models.job import Job, JobState
from app.models.print_batch import PrintBatch
from app.repositories import jobs as jobs_repo


# --- Fixtures (R2-C6: explizit definiert, nicht aus nicht-existenter conftest) ---

@pytest_asyncio.fixture
async def sample_batch_done(db_session):
    """2 DONE-Jobs + PrintBatch in der Test-DB."""
    printer_id = uuid4()
    j1 = await jobs_repo.create_queued(
        db_session, printer_id=printer_id, template_key="t", payload={}
    )
    j2 = await jobs_repo.create_queued(
        db_session, printer_id=printer_id, template_key="t", payload={}
    )
    await jobs_repo.mark_printing(db_session, j1.id)
    await jobs_repo.mark_done(db_session, j1.id, result={})
    await jobs_repo.mark_printing(db_session, j2.id)
    await jobs_repo.mark_done(db_session, j2.id, result={})

    batch = PrintBatch(
        printer_id=printer_id,
        job_ids=[str(j1.id), str(j2.id)],
        created_by="test@example.com",
    )
    db_session.add(batch)
    await db_session.commit()
    await db_session.refresh(batch)
    return batch


@pytest_asyncio.fixture
async def batch_with_ghost_ids(db_session):
    """PrintBatch mit 3 job_ids, davon 2 nach Anlage gelöscht (Geister-IDs)."""
    printer_id = uuid4()
    j1 = await jobs_repo.create_queued(
        db_session, printer_id=printer_id, template_key="t", payload={}
    )
    await jobs_repo.mark_printing(db_session, j1.id)
    await jobs_repo.mark_done(db_session, j1.id, result={})

    ghost_id_1 = str(uuid4())  # nie in DB eingetragen
    ghost_id_2 = str(uuid4())  # nie in DB eingetragen

    batch = PrintBatch(
        printer_id=printer_id,
        job_ids=[str(j1.id), ghost_id_1, ghost_id_2],
        created_by="test@example.com",
    )
    db_session.add(batch)
    await db_session.commit()
    await db_session.refresh(batch)
    return batch


# --- Tests ---

@pytest.mark.asyncio
async def test_get_batch_returns_404_for_unknown(client):
    # client kommt aus tests/integration/conftest.py:222 (fake-auth, kein eigenes auth_client)
    resp = await client.get(f"/api/batches/{uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_batch_returns_summary_with_all_terminal(
    client, sample_batch_done,
):
    resp = await client.get(f"/api/batches/{sample_batch_done.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(sample_batch_done.id)
    assert body["summary"]["total"] == 2
    assert body["summary"]["done"] == 2
    assert body["summary"]["queued"] == 0
    assert body["summary"]["all_terminal"] is True
    assert len(body["jobs"]) == 2


@pytest.mark.asyncio
async def test_get_batch_jobs_in_batch_order(
    client, sample_batch_done,
):
    """Job-Reihenfolge im Response entspricht batch.job_ids Array, nicht DB-default."""
    resp = await client.get(f"/api/batches/{sample_batch_done.id}")
    body = resp.json()
    received_ids = [j["id"] for j in body["jobs"]]
    expected_ids = [str(jid) for jid in sample_batch_done.job_ids]
    assert received_ids == expected_ids


@pytest.mark.asyncio
async def test_get_batch_handles_missing_jobs(client, batch_with_ghost_ids):
    """Wenn Jobs vom Cleanup geloescht sind (Geister-IDs), werden sie uebersprungen."""
    resp = await client.get(f"/api/batches/{batch_with_ghost_ids.id}")
    body = resp.json()
    assert body["summary"]["total"] < len(batch_with_ghost_ids.job_ids)
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd backend && pytest tests/integration/test_batch_snapshot_endpoint.py -v
```
Expected: FAIL `404 from FastAPI` weil Route nicht existiert.

- [ ] **Step 3: Add `list_by_ids` to jobs_repo**

In `backend/app/repositories/jobs.py` anhaengen:

```python
async def list_by_ids(
    session: AsyncSession,
    job_ids: list[UUID],
) -> list[Job]:
    """Bulk-Fetch jobs by ids — order not guaranteed, caller re-orders."""
    if not job_ids:
        return []
    result = await session.execute(
        select(Job).where(col(Job.id).in_(job_ids))
    )
    return list(result.scalars())
```

- [ ] **Step 4: Create BatchRead schema**

Datei: `backend/app/schemas/batch_read.py`

```python
"""Phase 2: BatchRead Schema fuer GET /api/batches/{id}."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, computed_field

from app.schemas.job import JobRead


class BatchSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    total: int
    queued: int
    printing: int
    done: int
    failed: int

    @computed_field
    @property
    def all_terminal(self) -> bool:
        """True if no jobs are in queued or printing state.

        Hangar's Result-Page uses this to skip opening an SSE-connection
        when there's nothing live to update.
        """
        return (self.queued + self.printing) == 0


class BatchRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    printer_id: UUID
    created_by: str | None  # R2-C5: PrintBatch.created_by ist str (SSO-Email oder API-Key-ID), kein UUID
    created_at: datetime
    jobs: list[JobRead]
    summary: BatchSummary
```

- [ ] **Step 5: Create batches route**

Datei: `backend/app/api/routes/batches.py`

```python
"""Phase 2: GET /api/batches/{id} — Snapshot fuer Hangar Result-Page Initial-Render."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_read
from app.db.session import get_session
from app.models.job import JobState
from app.repositories import jobs as jobs_repo
from app.repositories import print_batches as batches_repo
from app.schemas.batch_read import BatchRead, BatchSummary
from app.schemas.job import JobRead

router = APIRouter(prefix="/api/batches", tags=["batches"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ReadAuthDep = Annotated[AuthContext, Depends(require_read)]


@router.get("/{batch_id}", response_model=BatchRead)
async def get_batch(
    batch_id: UUID,
    session: SessionDep,
    auth: ReadAuthDep,
) -> BatchRead:
    """Snapshot of a batch + all its current job states.

    Used by Hangar's /admin/print/result/{batch_id} for the initial render.
    summary.all_terminal == false means Hangar should open an SSE stream
    to /api/events?batch_id=... for live updates.
    """
    batch = await batches_repo.get(session, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")

    fetched_jobs = await jobs_repo.list_by_ids(session, list(batch.job_ids))
    job_map = {j.id: j for j in fetched_jobs}

    # Order matches batch.job_ids; missing (cleanup-evicted) jobs are skipped
    ordered = [job_map[jid] for jid in batch.job_ids if jid in job_map]

    summary = BatchSummary(
        total=len(ordered),
        queued=sum(1 for j in ordered if j.state == JobState.QUEUED.value),
        printing=sum(1 for j in ordered if j.state == JobState.PRINTING.value),
        done=sum(1 for j in ordered if j.state == JobState.DONE.value),
        failed=sum(
            1 for j in ordered
            if j.state in (JobState.FAILED.value, JobState.FAILED_RESTART.value)
        ),
    )

    return BatchRead(
        id=batch.id,
        printer_id=batch.printer_id,
        created_by=batch.created_by,
        created_at=batch.created_at,
        jobs=[JobRead.model_validate(j) for j in ordered],
        summary=summary,
    )
```

- [ ] **Step 6: Register router in app**

In `backend/app/main.py` finde wo andere Router registriert werden (`app.include_router(...)`). Ergaenze:

```python
from app.api.routes import batches as batches_routes
app.include_router(batches_routes.router)
```

- [ ] **Step 7: Run tests to verify they pass**

Run:
```bash
cd backend && pytest tests/integration/test_batch_snapshot_endpoint.py -v
```
Expected: 4 PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/repositories/jobs.py backend/app/schemas/batch_read.py backend/app/api/routes/batches.py backend/app/main.py backend/tests/integration/test_batch_snapshot_endpoint.py
git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" commit -m "feat(api): GET /api/batches/{id} Snapshot-Endpoint (Phase 2)

Liefert Batch-Metadaten + alle Job-States. summary.all_terminal sagt
Hangar ob noch ein SSE-Stream geoeffnet werden muss. Job-Reihenfolge
entspricht batch.job_ids; cleanup-geister werden uebersprungen.

Entblockt strausmann/hangar#81.

Refs #93"
```

---

## Task 9: Lifespan-Wiring

**Files:**
- Modify: `backend/app/main.py` — `lifespan` context

- [ ] **Step 1: Wire JobStore + CleanupTask + PrintQueue in lifespan (R2-M5)**

**Konkrete Änderungen in `backend/app/main.py`.**

Lese die Datei ZUERST um die realen Zeilennummern zu verifizieren (Stand 2026-05-31 ca. Zeile 304-344).

Reale Variable aus `app/db/engine.py` importiert: `async_session` (eine `async_sessionmaker`).
**NICHT** `async_session_factory` — diese Variable existiert nicht im Lifespan (R2-M5).

Imports oben in `main.py` ergänzen:
```python
from app.services.job_store_sqlite import SQLiteJobStore
from app.services.cleanup_task import CleanupTask
```

Änderungen im Lifespan (Insertion NACH `recover_inflight_jobs` entfernen, BEFORE queue-Setup,
ca. um Zeile 273 nach dem `async with async_session() as s:` Block):

```python
    # Phase 2: recover_inflight_jobs() ENTFERNT (Spec R1-C1) — PrintQueue.start() übernimmt

    # Phase 2: JobStore + CleanupTask
    # 'async_session' ist die async_sessionmaker aus app.db.engine (R2-M5 — NICHT async_session_factory)
    job_store = SQLiteJobStore(async_session)

    cleanup_task = CleanupTask(
        store=job_store,
        retention_days=settings.job_retention_days,
    )
    await cleanup_task.start()
    app.state.cleanup_task = cleanup_task
```

PrintQueue-Instantiierung (echte Signatur — R2-M5):
```python
    # Reale PrintQueue-Signatur: PrintQueue(printers=[printer], on_state_change=...)
    # KEIN printer_ids / backend_factory — die Signatur existiert nicht
    queue = PrintQueue(
        printers=[printer],                              # existiert bereits
        on_state_change=pq_producer.handle_transition,  # existiert bereits
        store=job_store,                                 # NEU
        renderer=shared_renderer,                        # NEU — für Recovery
        loader=TemplateLoader,                           # NEU — für Recovery
    )
    await queue.start()  # ruft intern mark_interrupted + list_pending
```

PrintService-Instantiierung (echte Parameter-Namen aus `print_service.py`):
```python
    app.state.print_service = PrintService(
        template_loader=TemplateLoader,    # bestehend
        renderer=shared_renderer,          # bestehend
        print_queue=queue,                 # bestehend
        lookup_service=AppLookupService(), # bestehend
        printer_id=printer.id,             # bestehend
        backend=backend,                   # bestehend
        store=job_store,                   # NEU
    )
```

Shutdown-Block (vor `queue.stop()`):
```python
    finally:
        if status_producer is not None:
            await status_producer.stop()
        await cleanup_task.stop()    # NEU — CleanupTask vor Queue stoppen
        await queue.stop(timeout_s=settings.printer_queue_timeout_s)
        await engine.dispose()
        ...
```

- [ ] **Step 2: Run full test suite — verify no regressions**

Run:
```bash
cd backend && pytest -q
```
Expected: alle gruen, inkl. der 6 neuen Test-Dateien. Erwartung ~860 tests passed.

Falls integration tests brechen weil sie `print_service` ohne `store` instantiieren: adapt diese tests indem sie `store=MemoryJobStore()` oder `store=SQLiteJobStore(...)` mitgeben.

- [ ] **Step 3: Commit**

```bash
git add backend/app/main.py backend/tests
git -c user.name="Björn Strausmann" -c user.email="strausmannservices@googlemail.com" commit -m "feat(lifespan): wire JobStore + CleanupTask in app startup (Phase 2)

SQLiteJobStore aus async_session_factory; CleanupTask laeuft initial
beim Start + alle 24h. PrintQueue + PrintService bekommen store via
DI fuer Recovery und Persistierung.

Refs #93"
```

---

## Task 10: Manuelle Verification + Push + PR

- [ ] **Step 1: Lokaler Smoke gegen Mock-Backend**

```bash
cd backend && PRINTER_HUB_PRINTER_BACKEND=mock uv run uvicorn app.main:app --reload --port 8001
```

In zweitem Terminal:
```bash
# Mock-Drucker existiert nach erstem Lifespan-Run
sqlite3 /tmp/printer-hub-test.db "SELECT id, slug FROM printers"
# Submit batch
curl -s -X POST -H "X-Label-Hub-Key: ..." -H "Content-Type: application/json" \
  -d '{"items":[{"template_id":"hangar-furniture-24mm","data":{"title":"x","primary_id":"x","qr_payload":"q"}}]}' \
  http://localhost:8001/api/print/<mock-slug>/batch
# Antwort: {"batch_id": "...", "job_ids": ["..."]}

# Snapshot
curl -s -H "X-Label-Hub-Key: ..." http://localhost:8001/api/batches/<batch_id> | jq
# erwartet: summary mit total=1, done=1, all_terminal=true

# DB check
sqlite3 /tmp/printer-hub-test.db "SELECT id, state, finished_at FROM jobs ORDER BY created_at DESC LIMIT 3"
```

Expected: Job-Row existiert, state=done, finished_at gesetzt.

- [ ] **Step 2: Restart-Recovery Smoke**

In Server-Terminal: `Ctrl-C`. Submit Batch mit 3 items in einer Schleife. Mitten drin: Server-Terminal `Ctrl-C`. Neu starten:

```bash
cd backend && PRINTER_HUB_PRINTER_BACKEND=mock uv run uvicorn app.main:app --reload --port 8001
```

In Logs erwartet:
```
Recovery: 1 printing jobs on printer ... marked as interrupted
Recovery: re-enqueued QUEUED job ... on ...
```

- [ ] **Step 3: Mypy + ruff**

```bash
cd backend && uv run mypy app && uv run ruff check app && uv run ruff format --check app
```
Expected: alles gruen. Falls Findings: fixen und committen.

- [ ] **Step 4: Push**

```bash
git push origin feat/phase-2-job-persistence
```

- [ ] **Step 5: PR erstellen**

```bash
gh pr create --title "feat: Phase 2 Job Persistence (DB-backed + Restart Recovery + Cleanup)" \
  --body "$(cat <<'EOF'
## Was

Hub Phase 2 — Jobs werden jetzt in der `jobs`-Tabelle persistiert.

- `JobStore` Protocol mit `MemoryJobStore` und `SQLiteJobStore`
- `PrintQueue` ruft `store.mark_*` bei jeder State-Transition synchron
- `PrintService` legt erst die DB-Row an, dann queue.submit (atomisch)
- `PrintQueue.start()` Recovery: PRINTING → FAILED_RESTART, QUEUED → re-enqueued via Rerender
- `CleanupTask` raeumt terminal Jobs aelter als `PRINTER_HUB_JOB_RETENTION_DAYS` (Default 30)
- `GET /api/batches/{id}` Snapshot-Endpoint mit `summary.all_terminal`

## Tests

- 5 neue Unit-Tests fuer `MemoryJobStore` Protocol-Conformance
- 7 neue Unit-Tests fuer `SQLiteJobStore` gegen echte SQLite
- 3 neue Unit-Tests fuer `CleanupTask` (validate, initial-run, fail-soft)
- 3 neue Repository-Tests
- 1 Integration-Test fuer `PrintService.submit` Persistierung
- 2 Integration-Tests fuer `PrintQueue.start()` Recovery
- 4 Integration-Tests fuer `GET /api/batches/{id}`

Bestehende ~831 Tests bleiben gruen.

## Spec & Plan

- Spec: `docs/superpowers/specs/2026-05-31-phase-2-job-persistence-design.md`
- Plan: `docs/superpowers/plans/2026-05-31-phase-2-job-persistence.md`

## Bezug

Closes #93. Entblockt strausmann/hangar#81 (Result-Page Live-Updates).
EOF
)" \
  --base main
```

- [ ] **Step 6: Watch CI**

Pipeline auf GitHub: warten bis alle Checks gruen. Bei Failures: fixen, committen, push.

---

## Self-Review

### Spec Coverage

| Spec-Section | Plan-Task | Status |
|--------------|-----------|--------|
| JobStore Protocol | Task 2 | gedeckt |
| SQLiteJobStore | Task 3 | gedeckt |
| MemoryJobStore | Task 2 | gedeckt |
| PrintQueue Refactor (constructor + worker saves) | Task 4 | gedeckt |
| PrintService persist before queue.submit | Task 5 | gedeckt |
| Worker-Restart-Recovery in start() | Task 6 | gedeckt |
| GET /api/batches/{id} Snapshot | Task 8 | gedeckt |
| BatchSummary.all_terminal | Task 8 | gedeckt |
| CleanupTask | Task 7 | gedeckt |
| Config: PRINTER_HUB_JOB_RETENTION_DAYS | Task 7 | gedeckt |
| Lifespan-Integration | Task 9 | gedeckt |
| Repository-Helper neu | Task 1 | gedeckt |
| Errata 1 (zwei Job-Klassen) | Task 4/5 (dataclass bleibt) | gedeckt |
| Errata 2 (Wiederverwendung jobs_repo) | Task 3 | gedeckt |
| Errata 3 (FAILED_RESTART + error field) | Task 1/3 | gedeckt |
| Errata 4 (PrintService bekommt store) | Task 5 | gedeckt |

Edge-Cases aus Spec:

| Edge-Case | Test |
|-----------|------|
| Recovery: PAUSED stays PAUSED | Spec sagt PAUSED bleibt — Task 6 nutzt `list_pending` der QUEUED+PRINTING zurueckgibt (PAUSED ist nicht in `_NON_TERMINAL`) — implizit gedeckt |
| Recovery: DONE unchanged | `list_pending` returnt nicht DONE — implizit gedeckt |
| Cleanup keeps recent terminal | Task 1 evict-Test, Task 7 |
| Cleanup skips non-terminal | Task 1 evict-Test asserts non-terminal not deleted |
| Concurrent state transitions | Per-operation Sessions in Task 3 — Race-Test optional ergaenzbar |
| Batch with missing jobs (ghost ids) | Task 8 test_get_batch_handles_missing_jobs |

### Placeholder Scan

Keine TODO/TBD/FIXME im Plan. Code-Snippets sind vollstaendig. Commit-Messages sind konkret.

### Type Consistency

- `JobStore.mark_interrupted(printer_id: UUID) -> int` — konsistent in Memory + SQLite + Tests
- `mark_printing_as_failed_restart` (repo) vs `mark_interrupted` (store) — bewusste Differenz: repo ist generisch, store ist semantisch
- `JobState.FAILED_RESTART` durchgaengig (nicht FAILED) fuer interrupted recovery
- `error="printer_interrupted"` durchgaengig (nicht error_code) — matched DB-Schema mit `error: str | None`

Plan ist konsistent zur Spec inkl. Errata. Ready for execution.
