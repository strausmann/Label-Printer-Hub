# Phase 1k.3 — User-Presets (Hub-Backend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die ungenutzte `presets`-Tabelle zum Layout-Preset-Store ausbauen und eine CRUD-API + PNG-Preview bereitstellen, ohne den Druck-Pfad zu berühren.

**Architecture:** `presets`-Tabelle wird um `content_type` + `tape_mm` erweitert. Ein neuer `PresetService` validiert gegen `ContentType` / `TAPE_GEOMETRY` und kapselt Domain-Errors; ein neuer Router `presets_api.py` mappt CRUD + `preview.png`. Der Preview-Endpoint ruft die bestehende `LayoutEngine` auf — kein neuer Render-Pfad. Der Druck-Pfad (`POST /api/print`) bleibt unverändert.

**Tech Stack:** FastAPI, SQLModel/SQLAlchemy (async, SQLite + aiosqlite), Alembic, Pydantic v2, pytest + pytest-asyncio + httpx ASGITransport.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-06-23-user-presets-design.md` — verbindlich.
- TDD strict: Test zuerst schreiben, fehlschlagen sehen, dann minimal implementieren.
- Mutation-Logic Coverage ≥ 85% (`scripts/coverage-gate-strict.sh`).
- mypy strict + ruff: kein `Any` in öffentlichen Signaturen außer wo bestehend (`field_values: dict[str, Any]` ist erlaubt — bestehendes Schema).
- Deutsche Kommentare mit echten Umlauten (ä/ö/ü/ß).
- Test-IPs aus RFC-5737 (`192.0.2.x`) — Repo-Konvention (hier kaum relevant, Presets sind druckerlos).
- `content_type`-Default ist **`qr_three_lines`** (User-Vorgabe).
- Writes erfordern `require_print`, Reads/Preview `require_read`.
- Branch: `feat/phase-1k3-user-presets` (existiert bereits, Spec ist committed).
- Jeder Commit referenziert `Refs #104` (oder `#101`).
- Alle Pfade relativ zu Repo-Root `/opt/repos/label-printer-hub`. Tests laufen aus `backend/` (`cd backend && pytest ...`).

---

## File Structure

| Datei | Aktion | Verantwortung |
|-------|--------|---------------|
| `backend/app/models/preset.py` | Modify | Spalten `content_type` + `tape_mm` ergänzen |
| `backend/alembic/versions/<rev>_add_preset_layout_columns.py` | Create | Migration: 2 Spalten auf `presets` |
| `backend/app/repositories/presets.py` | Modify | `get_by_name` ergänzen (case-insensitive) |
| `backend/app/schemas/preset.py` | Create | Create/Update-Payloads + Response-Schema |
| `backend/app/services/preset_service.py` | Create | Domain-Errors + Validierung + CRUD-Orchestrierung + Preview-Render |
| `backend/app/api/routes/presets_api.py` | Create | HTTP-Router CRUD + `preview.png`, Auth-Deps |
| `backend/app/main.py` | Modify | Router registrieren |
| `backend/tests/db/test_presets_repo.py` | Create | Repo-Roundtrip + `get_by_name` |
| `backend/tests/db/test_preset_layout_migration.py` | Create | Migration fügt Spalten hinzu |
| `backend/tests/unit/services/test_preset_service.py` | Create | Validierung + Mutationen + Preview |
| `backend/tests/unit/api/test_presets_api.py` | Create | CRUD-Routes + Auth-Enforcement + Preview |

---

## Task 1: Preset-Model um `content_type` + `tape_mm` erweitern

**Files:**
- Modify: `backend/app/models/preset.py`
- Test: `backend/tests/db/test_presets_repo.py`

**Interfaces:**
- Produces: `Preset` SQLModel mit neuen Feldern `content_type: str` (Default `"qr_three_lines"`), `tape_mm: int` (Default `12`).

- [ ] **Step 1: Failing test — Preset mit neuen Feldern round-trippt**

Erstelle `backend/tests/db/test_presets_repo.py`:

```python
"""Repo-Tests für Preset-Aggregat (Phase 1k.3, Refs #104)."""

from __future__ import annotations

import pytest
from app.models.preset import Preset
from app.repositories import presets as preset_repo


@pytest.mark.asyncio
async def test_create_and_get_roundtrip_with_layout_fields(session):
    created = await preset_repo.create(
        session,
        Preset(name="Schublade A", content_type="qr_three_lines", tape_mm=12),
    )
    fetched = await preset_repo.get(session, created.id)
    assert fetched is not None
    assert fetched.name == "Schublade A"
    assert fetched.content_type == "qr_three_lines"
    assert fetched.tape_mm == 12


@pytest.mark.asyncio
async def test_defaults_applied(session):
    created = await preset_repo.create(session, Preset(name="Default-Preset"))
    assert created.content_type == "qr_three_lines"
    assert created.tape_mm == 12
```

Die `session`-Fixture kommt aus `backend/tests/db/conftest.py` (in-memory SQLite, `SQLModel.metadata.create_all`).

- [ ] **Step 2: Run test — erwartet FAIL**

Run: `cd backend && python -m pytest tests/db/test_presets_repo.py -v`
Expected: FAIL — `TypeError: 'content_type' is an invalid keyword argument for Preset` (Feld existiert noch nicht).

- [ ] **Step 3: Model erweitern**

In `backend/app/models/preset.py` innerhalb `class Preset`, nach dem `name`-Feld einfügen:

```python
    content_type: str = Field(
        default="qr_three_lines",
        description="Semantischer ContentType (siehe app.schemas.content_type.ContentType).",
    )
    tape_mm: int = Field(
        default=12,
        description="Ziel-Bandbreite in mm (muss in TAPE_GEOMETRY existieren).",
    )
```

- [ ] **Step 4: Run test — erwartet PASS**

Run: `cd backend && python -m pytest tests/db/test_presets_repo.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/preset.py backend/tests/db/test_presets_repo.py
git commit -m "feat(presets): content_type + tape_mm auf Preset-Model (Refs #104)"
```

---

## Task 2: Alembic-Migration für die zwei Spalten

**Files:**
- Create: `backend/alembic/versions/a1b2c3d4e5f6_add_preset_layout_columns.py`
- Test: `backend/tests/db/test_preset_layout_migration.py`

**Interfaces:**
- Consumes: aktueller Migrations-Head `42fbd015698d` (als `down_revision`).
- Produces: Migration-Modul mit `upgrade()`/`downgrade()`, `revision = "a1b2c3d4e5f6"`.

- [ ] **Step 1: Failing test — Migration fügt Spalten zu bestehender presets-Tabelle hinzu**

Erstelle `backend/tests/db/test_preset_layout_migration.py`:

```python
"""Migrationstest: presets bekommt content_type + tape_mm (Phase 1k.3, Refs #104)."""

from __future__ import annotations

import importlib

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

MIGRATION = "alembic.versions.a1b2c3d4e5f6_add_preset_layout_columns"


@pytest.mark.asyncio
async def test_upgrade_adds_columns_to_existing_presets_table():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    # Minimal-Vorzustand: presets-Tabelle ohne die neuen Spalten.
    async with eng.begin() as conn:
        await conn.execute(
            sa.text(
                "CREATE TABLE presets ("
                "id CHAR(32) PRIMARY KEY, name VARCHAR, printer_id CHAR(32), "
                "field_values JSON, created_at DATETIME, updated_at DATETIME)"
            )
        )
        mig = importlib.import_module(MIGRATION)
        await conn.run_sync(lambda sync_conn: _run_upgrade(sync_conn, mig))
        cols = await conn.run_sync(
            lambda c: {row[1] for row in c.execute(sa.text("PRAGMA table_info(presets)"))}
        )
    await eng.dispose()
    assert "content_type" in cols
    assert "tape_mm" in cols


def _run_upgrade(sync_conn, mig) -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    ctx = MigrationContext.configure(sync_conn)
    with Operations.context(ctx):
        mig.upgrade()
```

- [ ] **Step 2: Run test — erwartet FAIL**

Run: `cd backend && python -m pytest tests/db/test_preset_layout_migration.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'alembic.versions.a1b2c3d4e5f6_add_preset_layout_columns'`.

- [ ] **Step 3: Migration schreiben**

Erstelle `backend/alembic/versions/a1b2c3d4e5f6_add_preset_layout_columns.py`:

```python
"""add_preset_layout_columns

Phase 1k.3 (Refs #104): presets-Tabelle bekommt content_type + tape_mm, damit
Presets ein Layout (ContentType + Ziel-Band) speichern. Tabelle ist in
Produktion leer — server_default deckt eventuelle Bestandszeilen sauber ab.

Revision ID: a1b2c3d4e5f6
Revises: 42fbd015698d
Create Date: 2026-06-23

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "42fbd015698d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("presets", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "content_type",
                sa.String(length=32),
                nullable=False,
                server_default="qr_three_lines",
            )
        )
        batch_op.add_column(
            sa.Column(
                "tape_mm",
                sa.Integer(),
                nullable=False,
                server_default="12",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("presets", schema=None) as batch_op:
        batch_op.drop_column("tape_mm")
        batch_op.drop_column("content_type")
```

- [ ] **Step 4: Run test — erwartet PASS**

Run: `cd backend && python -m pytest tests/db/test_preset_layout_migration.py -v`
Expected: PASS.

- [ ] **Step 5: Migrations-Kette prüfen**

Run: `cd backend && python -m alembic heads`
Expected: genau ein Head `a1b2c3d4e5f6 (head)`. Falls mehrere Heads erscheinen, ist `down_revision` falsch — auf den vorher einzigen Head zeigen lassen.

- [ ] **Step 6: Commit**

```bash
git add backend/alembic/versions/a1b2c3d4e5f6_add_preset_layout_columns.py backend/tests/db/test_preset_layout_migration.py
git commit -m "feat(presets): Alembic-Migration content_type + tape_mm (Refs #104)"
```

---

## Task 3: Repository `get_by_name` (case-insensitive)

**Files:**
- Modify: `backend/app/repositories/presets.py`
- Test: `backend/tests/db/test_presets_repo.py`

**Interfaces:**
- Produces: `async def get_by_name(session, name: str) -> Preset | None` — case-insensitiver Vergleich auf `name`.

- [ ] **Step 1: Failing test — get_by_name findet case-insensitiv**

Ans Ende von `backend/tests/db/test_presets_repo.py` anhängen:

```python
@pytest.mark.asyncio
async def test_get_by_name_case_insensitive(session):
    await preset_repo.create(session, Preset(name="Schublade A"))
    assert await preset_repo.get_by_name(session, "schublade a") is not None
    assert await preset_repo.get_by_name(session, "SCHUBLADE A") is not None
    assert await preset_repo.get_by_name(session, "anderer") is None
```

- [ ] **Step 2: Run test — erwartet FAIL**

Run: `cd backend && python -m pytest tests/db/test_presets_repo.py::test_get_by_name_case_insensitive -v`
Expected: FAIL — `AttributeError: module 'app.repositories.presets' has no attribute 'get_by_name'`.

- [ ] **Step 3: `get_by_name` implementieren**

In `backend/app/repositories/presets.py`, oberhalb von `create`, einfügen (und `func` importieren):

```python
from sqlalchemy import func, select  # ersetzt den bestehenden `from sqlalchemy import select`


async def get_by_name(session: AsyncSession, name: str) -> Preset | None:
    """Case-insensitiver Lookup über den Namen (für Duplikat-Prüfung)."""
    result = await session.execute(
        select(Preset).where(func.lower(Preset.name) == name.lower())
    )
    return result.scalars().first()
```

- [ ] **Step 4: Run test — erwartet PASS**

Run: `cd backend && python -m pytest tests/db/test_presets_repo.py -v`
Expected: PASS (alle Tests in der Datei).

- [ ] **Step 5: Commit**

```bash
git add backend/app/repositories/presets.py backend/tests/db/test_presets_repo.py
git commit -m "feat(presets): get_by_name case-insensitive im Repository (Refs #104)"
```

---

## Task 4: Pydantic-Schemas (Create/Update/Response)

**Files:**
- Create: `backend/app/schemas/preset.py`
- Test: `backend/tests/unit/services/test_preset_service.py` (Schema-Teil — Datei wird hier angelegt)

**Interfaces:**
- Produces:
  - `PresetCreatePayload(name: str, content_type: ContentType, tape_mm: int, field_values: dict[str, Any] = {}, printer_id: UUID | None = None)`
  - `PresetUpdatePayload(name | content_type | tape_mm | field_values | printer_id, alle optional)`
  - `PresetResponse(id, name, content_type, tape_mm, field_values, printer_id, created_at, updated_at)`

- [ ] **Step 1: Failing test — Payload akzeptiert ContentType-Enum, lehnt leeren Namen ab**

Erstelle `backend/tests/unit/services/test_preset_service.py`:

```python
"""Tests für PresetService + Preset-Schemas (Phase 1k.3, Refs #104)."""

from __future__ import annotations

import pytest
from app.schemas.content_type import ContentType
from app.schemas.preset import PresetCreatePayload
from pydantic import ValidationError


def test_create_payload_accepts_content_type_enum():
    payload = PresetCreatePayload(
        name="Schublade A",
        content_type=ContentType.QR_THREE_LINES,
        tape_mm=12,
        field_values={"primary_id": "A1", "title": "Schrauben",
                      "qr_payload": "x", "secondary": ["M3"]},
    )
    assert payload.content_type == ContentType.QR_THREE_LINES
    assert payload.tape_mm == 12


def test_create_payload_rejects_empty_name():
    with pytest.raises(ValidationError):
        PresetCreatePayload(name="", content_type=ContentType.QR_ONLY, tape_mm=12)
```

- [ ] **Step 2: Run test — erwartet FAIL**

Run: `cd backend && python -m pytest tests/unit/services/test_preset_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.schemas.preset'`.

- [ ] **Step 3: Schemas schreiben**

Erstelle `backend/app/schemas/preset.py`:

```python
"""Pydantic-Schemas für die Preset-CRUD-API (Phase 1k.3, Refs #104)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.content_type import ContentType


class PresetCreatePayload(BaseModel):
    """Body für POST /api/v1/presets."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    content_type: ContentType
    tape_mm: int = Field(ge=1)
    field_values: dict[str, Any] = Field(default_factory=dict)
    printer_id: UUID | None = None


class PresetUpdatePayload(BaseModel):
    """Body für PUT /api/v1/presets/{id} — PATCH-Semantik, alle Felder optional."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    content_type: ContentType | None = None
    tape_mm: int | None = Field(default=None, ge=1)
    field_values: dict[str, Any] | None = None
    printer_id: UUID | None = None


class PresetResponse(BaseModel):
    """Response-Darstellung eines Presets."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    content_type: ContentType
    tape_mm: int
    field_values: dict[str, Any]
    printer_id: UUID | None
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 4: Run test — erwartet PASS**

Run: `cd backend && python -m pytest tests/unit/services/test_preset_service.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/preset.py backend/tests/unit/services/test_preset_service.py
git commit -m "feat(presets): Create/Update/Response-Schemas (Refs #104)"
```

---

## Task 5: PresetService — Domain-Errors + Validierung + CRUD

**Files:**
- Create: `backend/app/services/preset_service.py`
- Modify: `backend/app/services/layout_engine.py` (kleiner öffentlicher Accessor `required_fields`)
- Test: `backend/tests/unit/services/test_preset_service.py`

**Interfaces:**
- Consumes: `PresetCreatePayload`, `PresetUpdatePayload`, `app.repositories.presets`, `TAPE_GEOMETRY`, `ContentType`, `LayoutEngine.required_fields`.
- Produces:
  - Errors: `PresetNotFoundError(preset_id: UUID)`, `DuplicatePresetNameError(name: str)`, `UnsupportedTapeError` (wiederverwendet aus `app.printer_backends.exceptions`), `ContentTypeDataMismatchError` (wiederverwendet).
  - `class PresetService(session)` mit `async create(payload) -> Preset`, `async get(preset_id) -> Preset`, `async list_all() -> list[Preset]`, `async update(preset_id, payload) -> Preset`, `async delete(preset_id) -> None`.
  - Klassenmethode `LayoutEngine.required_fields(content_type) -> tuple[str, ...]`.

- [ ] **Step 1: Failing test — Service validiert tape + required-fields + Name-Duplikat, und CRUD**

Ans Ende von `backend/tests/unit/services/test_preset_service.py` anhängen:

```python
import pytest_asyncio
from app.printer_backends.exceptions import (
    ContentTypeDataMismatchError,
    UnsupportedTapeError,
)
from app.schemas.preset import PresetUpdatePayload
from app.services.preset_service import (
    DuplicatePresetNameError,
    PresetNotFoundError,
    PresetService,
)
from uuid import uuid4


def _valid_three_line_fields() -> dict:
    return {"primary_id": "A1", "title": "Schrauben",
            "qr_payload": "https://x", "secondary": ["M3"]}


@pytest.mark.asyncio
async def test_create_persists_and_returns(session):
    svc = PresetService(session)
    preset = await svc.create(PresetCreatePayload(
        name="Schublade A", content_type=ContentType.QR_THREE_LINES,
        tape_mm=12, field_values=_valid_three_line_fields()))
    assert preset.id is not None
    assert preset.content_type == "qr_three_lines"


@pytest.mark.asyncio
async def test_create_rejects_unsupported_tape(session):
    svc = PresetService(session)
    with pytest.raises(UnsupportedTapeError):
        await svc.create(PresetCreatePayload(
            name="Bad Tape", content_type=ContentType.QR_ONLY,
            tape_mm=999, field_values={"qr_payload": "x"}))


@pytest.mark.asyncio
async def test_create_rejects_missing_required_fields(session):
    svc = PresetService(session)
    with pytest.raises(ContentTypeDataMismatchError):
        await svc.create(PresetCreatePayload(
            name="Missing", content_type=ContentType.QR_THREE_LINES,
            tape_mm=12, field_values={"primary_id": "A1"}))  # title/qr/secondary fehlen


@pytest.mark.asyncio
async def test_create_rejects_duplicate_name_case_insensitive(session):
    svc = PresetService(session)
    await svc.create(PresetCreatePayload(
        name="Schublade A", content_type=ContentType.QR_ONLY,
        tape_mm=12, field_values={"qr_payload": "x"}))
    with pytest.raises(DuplicatePresetNameError):
        await svc.create(PresetCreatePayload(
            name="schublade a", content_type=ContentType.QR_ONLY,
            tape_mm=12, field_values={"qr_payload": "x"}))


@pytest.mark.asyncio
async def test_update_patches_name(session):
    svc = PresetService(session)
    created = await svc.create(PresetCreatePayload(
        name="Alt", content_type=ContentType.QR_ONLY,
        tape_mm=12, field_values={"qr_payload": "x"}))
    updated = await svc.update(created.id, PresetUpdatePayload(name="Neu"))
    assert updated.name == "Neu"


@pytest.mark.asyncio
async def test_update_missing_raises_not_found(session):
    svc = PresetService(session)
    with pytest.raises(PresetNotFoundError):
        await svc.update(uuid4(), PresetUpdatePayload(name="X"))


@pytest.mark.asyncio
async def test_delete_missing_raises_not_found(session):
    svc = PresetService(session)
    with pytest.raises(PresetNotFoundError):
        await svc.delete(uuid4())


@pytest.mark.asyncio
async def test_delete_removes(session):
    svc = PresetService(session)
    created = await svc.create(PresetCreatePayload(
        name="Weg", content_type=ContentType.QR_ONLY,
        tape_mm=12, field_values={"qr_payload": "x"}))
    await svc.delete(created.id)
    with pytest.raises(PresetNotFoundError):
        await svc.get(created.id)
```

Die `session`-Fixture: lege eine lokale Fixture am Anfang der Datei an (analog `tests/db/conftest.py`), da diese Datei unter `tests/unit/services/` liegt:

```python
import app.models  # noqa: F401 — registriert alle Models
import pytest_asyncio
from app.db.engine import _apply_pragmas
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel


@pytest_asyncio.fixture
async def session():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(eng.sync_engine, "connect", _apply_pragmas)
    async with eng.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False)
    async with factory() as s:
        yield s
    await eng.dispose()
```

- [ ] **Step 2: Run test — erwartet FAIL**

Run: `cd backend && python -m pytest tests/unit/services/test_preset_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.preset_service'`.

- [ ] **Step 3: `required_fields`-Accessor auf LayoutEngine ergänzen**

In `backend/app/services/layout_engine.py`, als Methode der Klasse `LayoutEngine` (nach `render`), einfügen:

```python
    @classmethod
    def required_fields(cls, content_type: ContentType) -> tuple[str, ...]:
        """Öffentlicher Accessor auf die Pflichtfelder eines ContentType."""
        return cls._REQUIRED_FIELDS[content_type]
```

- [ ] **Step 4: PresetService schreiben**

Erstelle `backend/app/services/preset_service.py`:

```python
"""PresetService — Validierung + CRUD für Layout-Presets (Phase 1k.3, Refs #104).

Presets speichern ein Layout (ContentType + Ziel-Band + Default-Feldwerte).
Der Service validiert gegen TAPE_GEOMETRY und die ContentType-Pflichtfelder,
bevor er ans Repository delegiert. Domain-Errors werden im Router auf
HTTP-Statuscodes gemappt.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.preset import Preset
from app.printer_backends.exceptions import (
    ContentTypeDataMismatchError,
    UnsupportedTapeError,
)
from app.repositories import presets as preset_repo
from app.schemas.content_type import ContentType
from app.schemas.preset import PresetCreatePayload, PresetUpdatePayload
from app.schemas.tape_geometry import TAPE_GEOMETRY
from app.services.layout_engine import LayoutEngine


class PresetNotFoundError(Exception):
    def __init__(self, preset_id: UUID) -> None:
        self.preset_id = preset_id
        super().__init__(f"Preset {preset_id} nicht gefunden")


class DuplicatePresetNameError(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Preset-Name {name!r} bereits vergeben")


def _validate_layout(
    content_type: ContentType, tape_mm: int, field_values: dict[str, object]
) -> None:
    """Tape + ContentType-Pflichtfelder prüfen. Wirft Domain-Errors bei Verstoß."""
    if tape_mm not in TAPE_GEOMETRY:
        raise UnsupportedTapeError(tape_mm=tape_mm)
    required = LayoutEngine.required_fields(content_type)
    missing = [
        f
        for f in required
        if (v := field_values.get(f)) is None
        or (hasattr(v, "__len__") and len(v) == 0)
    ]
    if missing:
        raise ContentTypeDataMismatchError(
            content_type=str(content_type), missing_fields=tuple(missing)
        )


class PresetService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self) -> list[Preset]:
        return await preset_repo.list_all(self._session)

    async def get(self, preset_id: UUID) -> Preset:
        preset = await preset_repo.get(self._session, preset_id)
        if preset is None:
            raise PresetNotFoundError(preset_id)
        return preset

    async def create(self, payload: PresetCreatePayload) -> Preset:
        _validate_layout(payload.content_type, payload.tape_mm, payload.field_values)
        if await preset_repo.get_by_name(self._session, payload.name) is not None:
            raise DuplicatePresetNameError(payload.name)
        preset = Preset(
            name=payload.name,
            content_type=str(payload.content_type),
            tape_mm=payload.tape_mm,
            field_values=dict(payload.field_values),
            printer_id=payload.printer_id,
        )
        return await preset_repo.create(self._session, preset)

    async def update(self, preset_id: UUID, payload: PresetUpdatePayload) -> Preset:
        existing = await self.get(preset_id)
        merged_ct = payload.content_type or ContentType(existing.content_type)
        merged_tape = payload.tape_mm if payload.tape_mm is not None else existing.tape_mm
        merged_fields = (
            payload.field_values
            if payload.field_values is not None
            else existing.field_values
        )
        _validate_layout(merged_ct, merged_tape, merged_fields)
        if payload.name is not None and payload.name.lower() != existing.name.lower():
            clash = await preset_repo.get_by_name(self._session, payload.name)
            if clash is not None:
                raise DuplicatePresetNameError(payload.name)
        changes: dict[str, object] = {}
        if payload.name is not None:
            changes["name"] = payload.name
        if payload.content_type is not None:
            changes["content_type"] = str(payload.content_type)
        if payload.tape_mm is not None:
            changes["tape_mm"] = payload.tape_mm
        if payload.field_values is not None:
            changes["field_values"] = dict(payload.field_values)
        if "printer_id" in payload.model_fields_set:
            changes["printer_id"] = payload.printer_id
        updated = await preset_repo.update(self._session, preset_id, **changes)
        if updated is None:  # pragma: no cover — get() oben garantiert Existenz
            raise PresetNotFoundError(preset_id)
        return updated

    async def delete(self, preset_id: UUID) -> None:
        ok = await preset_repo.delete(self._session, preset_id)
        if not ok:
            raise PresetNotFoundError(preset_id)
```

- [ ] **Step 5: Run test — erwartet PASS**

Run: `cd backend && python -m pytest tests/unit/services/test_preset_service.py -v`
Expected: PASS (alle Service-Tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/preset_service.py backend/app/services/layout_engine.py backend/tests/unit/services/test_preset_service.py
git commit -m "feat(presets): PresetService mit Validierung + CRUD (Refs #104)"
```

---

## Task 6: Preview-Rendering im Service (Preset → PNG)

**Files:**
- Modify: `backend/app/services/preset_service.py`
- Test: `backend/tests/unit/services/test_preset_service.py`

**Interfaces:**
- Produces: `async PresetService.render_preview_png(preset_id: UUID) -> bytes` — lädt Preset, mappt `field_values` → `LabelData`, rendert via `LayoutEngine` zu PNG-Bytes. Wirft `PresetNotFoundError` (404), `UnsupportedTapeError` (409), `ContentTypeDataMismatchError` (422).

- [ ] **Step 1: Failing test — Preview liefert PNG-Bytes**

Ans Ende von `backend/tests/unit/services/test_preset_service.py` anhängen:

```python
@pytest.mark.asyncio
async def test_render_preview_png_returns_png_bytes(session):
    svc = PresetService(session)
    created = await svc.create(PresetCreatePayload(
        name="Preview", content_type=ContentType.QR_THREE_LINES,
        tape_mm=12, field_values=_valid_three_line_fields()))
    png = await svc.render_preview_png(created.id)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"  # PNG-Magic


@pytest.mark.asyncio
async def test_render_preview_missing_raises_not_found(session):
    svc = PresetService(session)
    with pytest.raises(PresetNotFoundError):
        await svc.render_preview_png(uuid4())
```

- [ ] **Step 2: Run test — erwartet FAIL**

Run: `cd backend && python -m pytest tests/unit/services/test_preset_service.py -k preview -v`
Expected: FAIL — `AttributeError: 'PresetService' object has no attribute 'render_preview_png'`.

- [ ] **Step 3: Methode implementieren**

In `backend/app/services/preset_service.py` die Imports ergänzen:

```python
import io

from app.schemas.label_data import LabelData
```

Und in `class PresetService` die Methode ergänzen:

```python
    async def render_preview_png(self, preset_id: UUID) -> bytes:
        """Rendert ein Preset als PNG. Nutzt die bestehende LayoutEngine."""
        preset = await self.get(preset_id)
        fv = preset.field_values
        label = LabelData(
            primary_id=fv.get("primary_id"),
            title=fv.get("title"),
            qr_payload=fv.get("qr_payload"),
            source_app="preview",
            secondary=tuple(fv.get("secondary", ()) or ()),
            items=tuple(fv.get("items", ()) or ()),
        )
        engine = LayoutEngine()
        image = engine.render(preset.tape_mm, ContentType(preset.content_type), label)
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()
```

Hinweis: Falls `LabelData.items` typisierte `LabelDataItem`-Objekte erwartet, im ersten Wurf nur die ContentTypes ohne `items` (alle außer `qr_with_listing`) durch die Preview unterstützen — `items` bleibt leer. `qr_with_listing`-Preview ist Folge-Arbeit (im Out-of-Scope der Spec implizit, hier explizit als `# pragma`-frei dokumentiert).

- [ ] **Step 4: Run test — erwartet PASS**

Run: `cd backend && python -m pytest tests/unit/services/test_preset_service.py -v`
Expected: PASS (alle).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/preset_service.py backend/tests/unit/services/test_preset_service.py
git commit -m "feat(presets): PNG-Preview-Rendering im Service (Refs #104)"
```

---

## Task 7: CRUD-Router `presets_api.py` (ohne Preview)

**Files:**
- Create: `backend/app/api/routes/presets_api.py`
- Test: `backend/tests/unit/api/test_presets_api.py`

**Interfaces:**
- Consumes: `PresetService`, `PresetCreatePayload`, `PresetUpdatePayload`, `PresetResponse`, `require_read`, `require_print`, `get_session`.
- Produces: `router = APIRouter(prefix="/api/v1/presets", tags=["presets"])` mit GET(list), POST, GET/{id}, PUT/{id}, DELETE/{id}.

- [ ] **Step 1: Failing test — CRUD-Happy-Paths + Fehlercodes + Auth**

Erstelle `backend/tests/unit/api/test_presets_api.py`:

```python
"""Unit-Tests für /api/v1/presets CRUD (Phase 1k.3, Refs #104).

Auth über dependency_overrides — analog test_admin_printers_api.py.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import app.models  # noqa: F401
import pytest
from app.api.routes.presets_api import router as presets_router
from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_print, require_read
from app.db.engine import _apply_pragmas
from app.db.session import get_session
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel


def _make_engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(eng.sync_engine, "connect", _apply_pragmas)
    return eng


@pytest.fixture
async def session():
    eng = _make_engine()
    async with eng.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False)
    async with factory() as s:
        yield s
    await eng.dispose()


def _build_app(session: AsyncSession, *, with_write: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(presets_router)

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override_session
    read_ctx = AuthContext(source="api-key", scope="read", api_key_id=uuid4(), ip="192.0.2.1")
    app.dependency_overrides[require_read] = lambda: read_ctx
    if with_write:
        print_ctx = AuthContext(source="api-key", scope="print", api_key_id=uuid4(), ip="192.0.2.1")
        app.dependency_overrides[require_print] = lambda: print_ctx
    return app


def _payload(name: str = "Schublade A") -> dict:
    return {
        "name": name,
        "content_type": "qr_three_lines",
        "tape_mm": 12,
        "field_values": {"primary_id": "A1", "title": "Schrauben",
                         "qr_payload": "https://x", "secondary": ["M3"]},
    }


@pytest.mark.asyncio
async def test_create_then_get(session):
    app = _build_app(session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post("/api/v1/presets", json=_payload())
        assert r.status_code == 201
        pid = r.json()["id"]
        g = await ac.get(f"/api/v1/presets/{pid}")
        assert g.status_code == 200
        assert g.json()["content_type"] == "qr_three_lines"


@pytest.mark.asyncio
async def test_list_returns_created(session):
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        await ac.post("/api/v1/presets", json=_payload())
        r = await ac.get("/api/v1/presets")
        assert r.status_code == 200
        assert len(r.json()) == 1


@pytest.mark.asyncio
async def test_create_duplicate_name_returns_409(session):
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        await ac.post("/api/v1/presets", json=_payload())
        r = await ac.post("/api/v1/presets", json=_payload(name="schublade a"))
        assert r.status_code == 409


@pytest.mark.asyncio
async def test_create_unsupported_tape_returns_422(session):
    app = _build_app(session)
    bad = _payload()
    bad["tape_mm"] = 999
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/api/v1/presets", json=bad)
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_missing_fields_returns_422(session):
    app = _build_app(session)
    bad = _payload()
    bad["field_values"] = {"primary_id": "A1"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/api/v1/presets", json=bad)
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_get_missing_returns_404(session):
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(f"/api/v1/presets/{uuid4()}")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_update_patches(session):
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        pid = (await ac.post("/api/v1/presets", json=_payload())).json()["id"]
        r = await ac.put(f"/api/v1/presets/{pid}", json={"name": "Neu"})
        assert r.status_code == 200
        assert r.json()["name"] == "Neu"


@pytest.mark.asyncio
async def test_delete_returns_204_then_404(session):
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        pid = (await ac.post("/api/v1/presets", json=_payload())).json()["id"]
        d = await ac.delete(f"/api/v1/presets/{pid}")
        assert d.status_code == 204
        assert (await ac.delete(f"/api/v1/presets/{pid}")).status_code == 404


@pytest.mark.asyncio
async def test_write_requires_print_scope(session):
    # Ohne require_print-Override greift die echte Scope-Dependency → 401/403.
    app = _build_app(session, with_write=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/api/v1/presets", json=_payload())
        assert r.status_code in (401, 403)
```

- [ ] **Step 2: Run test — erwartet FAIL**

Run: `cd backend && python -m pytest tests/unit/api/test_presets_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api.routes.presets_api'`.

- [ ] **Step 3: Router schreiben**

Erstelle `backend/app/api/routes/presets_api.py`:

```python
"""JSON-CRUD-API für Layout-Presets (Phase 1k.3, Refs #104).

Routes
------
GET    /api/v1/presets            — Liste (require_read)
POST   /api/v1/presets            — Anlegen 201 (require_print)
GET    /api/v1/presets/{id}       — Einzeln 200/404 (require_read)
PUT    /api/v1/presets/{id}       — Update 200/404/409/422 (require_print)
DELETE /api/v1/presets/{id}       — Löschen 204/404 (require_print)

Preview (preview.png) folgt in einem separaten Modul-Abschnitt.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import AuthContext
from app.auth.scope_deps import require_print, require_read
from app.db.session import get_session
from app.printer_backends.exceptions import (
    ContentTypeDataMismatchError,
    UnsupportedTapeError,
)
from app.schemas.preset import (
    PresetCreatePayload,
    PresetResponse,
    PresetUpdatePayload,
)
from app.services.preset_service import (
    DuplicatePresetNameError,
    PresetNotFoundError,
    PresetService,
)

router = APIRouter(prefix="/api/v1/presets", tags=["presets"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ReadAuthDep = Annotated[AuthContext, Depends(require_read)]
WriteAuthDep = Annotated[AuthContext, Depends(require_print)]


def _map_validation_error(exc: Exception) -> HTTPException:
    if isinstance(exc, UnsupportedTapeError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    if isinstance(exc, ContentTypeDataMismatchError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    if isinstance(exc, DuplicatePresetNameError):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    raise exc  # pragma: no cover — unerwarteter Typ


@router.get("", response_model=list[PresetResponse])
async def list_presets(session: SessionDep, _auth: ReadAuthDep) -> list[PresetResponse]:
    presets = await PresetService(session).list_all()
    return [PresetResponse.model_validate(p) for p in presets]


@router.post("", response_model=PresetResponse, status_code=status.HTTP_201_CREATED)
async def create_preset(
    payload: PresetCreatePayload, session: SessionDep, _auth: WriteAuthDep
) -> PresetResponse:
    try:
        preset = await PresetService(session).create(payload)
    except (UnsupportedTapeError, ContentTypeDataMismatchError, DuplicatePresetNameError) as exc:
        raise _map_validation_error(exc) from exc
    return PresetResponse.model_validate(preset)


@router.get("/{preset_id}", response_model=PresetResponse)
async def get_preset(
    preset_id: UUID, session: SessionDep, _auth: ReadAuthDep
) -> PresetResponse:
    try:
        preset = await PresetService(session).get(preset_id)
    except PresetNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return PresetResponse.model_validate(preset)


@router.put("/{preset_id}", response_model=PresetResponse)
async def update_preset(
    preset_id: UUID,
    payload: PresetUpdatePayload,
    session: SessionDep,
    _auth: WriteAuthDep,
) -> PresetResponse:
    try:
        preset = await PresetService(session).update(preset_id, payload)
    except PresetNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (UnsupportedTapeError, ContentTypeDataMismatchError, DuplicatePresetNameError) as exc:
        raise _map_validation_error(exc) from exc
    return PresetResponse.model_validate(preset)


@router.delete("/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_preset(
    preset_id: UUID, session: SessionDep, _auth: WriteAuthDep
) -> Response:
    try:
        await PresetService(session).delete(preset_id)
    except PresetNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 4: Run test — erwartet PASS**

Run: `cd backend && python -m pytest tests/unit/api/test_presets_api.py -v`
Expected: PASS (alle CRUD-Tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/presets_api.py backend/tests/unit/api/test_presets_api.py
git commit -m "feat(presets): CRUD-Router /api/v1/presets (Refs #104)"
```

---

## Task 8: Preview-Endpoint `GET /{id}/preview.png`

**Files:**
- Modify: `backend/app/api/routes/presets_api.py`
- Test: `backend/tests/unit/api/test_presets_api.py`

**Interfaces:**
- Consumes: `PresetService.render_preview_png`.
- Produces: Route `GET /api/v1/presets/{id}/preview.png` → `image/png` (200), 404, 409 (bad tape), 422 (fehlende Felder).

- [ ] **Step 1: Failing test — Preview liefert PNG / 404**

Ans Ende von `backend/tests/unit/api/test_presets_api.py` anhängen:

```python
@pytest.mark.asyncio
async def test_preview_png_ok(session):
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        pid = (await ac.post("/api/v1/presets", json=_payload())).json()["id"]
        r = await ac.get(f"/api/v1/presets/{pid}/preview.png")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.asyncio
async def test_preview_png_missing_returns_404(session):
    app = _build_app(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(f"/api/v1/presets/{uuid4()}/preview.png")
        assert r.status_code == 404
```

- [ ] **Step 2: Run test — erwartet FAIL**

Run: `cd backend && python -m pytest tests/unit/api/test_presets_api.py -k preview -v`
Expected: FAIL — 404 erwartet PNG bzw. Route fehlt (404 für ok-Test wegen fehlender Route).

- [ ] **Step 3: Preview-Route ergänzen**

In `backend/app/api/routes/presets_api.py` die Route ergänzen (keine neuen Imports nötig — `render_preview_png` ist async und wird direkt awaited; die CPU-Arbeit ist klein genug für den Request-Pfad, eine spätere `to_thread`-Optimierung ist Folge-Arbeit):

```python
@router.get(
    "/{preset_id}/preview.png",
    responses={
        200: {"content": {"image/png": {}}},
        404: {"description": "Preset nicht gefunden"},
        409: {"description": "Tape-Breite nicht unterstützt"},
        422: {"description": "field_values deckt content_type nicht ab"},
    },
)
async def preview_preset_png(
    preset_id: UUID, session: SessionDep, _auth: ReadAuthDep
) -> Response:
    try:
        png = await PresetService(session).render_preview_png(preset_id)
    except PresetNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except UnsupportedTapeError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ContentTypeDataMismatchError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return Response(content=png, media_type="image/png")
```

- [ ] **Step 4: Run test — erwartet PASS**

Run: `cd backend && python -m pytest tests/unit/api/test_presets_api.py -v`
Expected: PASS (alle, inkl. Preview).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/presets_api.py backend/tests/unit/api/test_presets_api.py
git commit -m "feat(presets): preview.png-Endpoint (Refs #104)"
```

---

## Task 9: Router in `main.py` registrieren + Smoke-Test

**Files:**
- Modify: `backend/app/main.py`
- Test: `backend/tests/unit/api/test_presets_api.py`

**Interfaces:**
- Consumes: `app.api.routes.presets_api.router`.
- Produces: registrierte Routen in der echten App.

- [ ] **Step 1: Failing test — Route ist in der echten App registriert**

Ans Ende von `backend/tests/unit/api/test_presets_api.py` anhängen:

```python
def test_presets_router_registered_in_app():
    from app.main import create_app

    # create_app() liefert einen _LifespanManager-Wrapper; die FastAPI-Instanz
    # liegt in ._app (Unwrap-Muster aus tests/api/test_openapi_completeness.py).
    inner_app = create_app()._app  # type: ignore[attr-defined]
    paths = {r.path for r in inner_app.routes}
    assert "/api/v1/presets" in paths
    assert "/api/v1/presets/{preset_id}/preview.png" in paths
```

- [ ] **Step 2: Run test — erwartet FAIL**

Run: `cd backend && python -m pytest tests/unit/api/test_presets_api.py::test_presets_router_registered_in_app -v`
Expected: FAIL — Pfad nicht in `app.routes`.

- [ ] **Step 3: Router registrieren**

In `backend/app/main.py`:
- Bei den Router-Imports (nach Zeile 87, `admin_printers_api_router`) ergänzen:

```python
from app.api.routes.presets_api import router as presets_api_router
```

- Bei den `include_router`-Aufrufen (nach Zeile 715, `admin_printers_api_router`) ergänzen:

```python
    app.include_router(presets_api_router)
```

- [ ] **Step 4: Run test — erwartet PASS**

Run: `cd backend && python -m pytest tests/unit/api/test_presets_api.py -v`
Expected: PASS (alle).

- [ ] **Step 5: Volle Test-Suite + Lint + Coverage-Gate**

```bash
cd backend && python -m pytest tests/ -q
cd backend && python -m ruff check app/ tests/
cd backend && python -m mypy app/
```
Expected: alle grün; keine ruff/mypy-Fehler in den neuen Dateien.

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py backend/tests/unit/api/test_presets_api.py
git commit -m "feat(presets): Router in App registrieren + Smoke-Test (Refs #104)"
```

---

## Self-Review (gegen Spec)

**Spec-Coverage:**
- presets-Tabelle erweitern (content_type/tape_mm, Default qr_three_lines/12) → Task 1 + 2 ✓
- CRUD /api/v1/presets + preview.png → Task 7 + 8 ✓
- Validierung content_type ∈ ContentType / tape ∈ TAPE_GEOMETRY / required fields → Task 5 ✓
- Auth: Writes require_print, Reads require_read → Task 7 (Test `test_write_requires_print_scope`) ✓
- Preview nutzt LayoutEngine, kein neuer Render-Pfad → Task 6 ✓
- Tests Mutation-Pfade Happy+Error → Task 5/7 ✓
- Out of scope (Overrides, Editor-UI, PrintRequest) → nicht berührt ✓

**Offen / bewusst nicht im Plan:**
- `qr_with_listing`-Preview mit `items` → Task 6 Hinweis: Folge-Arbeit.
- Doku-Pipeline (MkDocs-Seite + Blog) → nach Merge via Doku-Workflow (separat, nicht Code-Plan).
- #104 Re-Scope + Label `superpowers:brainstorming` → PM-Team (separat).

**Platzhalter-Scan:** keine TBD/TODO; jeder Code-Step enthält vollständigen Code.

**Typ-Konsistenz:** `PresetService`, `PresetCreatePayload/UpdatePayload/Response`, `render_preview_png`, `get_by_name`, `required_fields` durchgängig gleich benannt in Tasks 4–9.
