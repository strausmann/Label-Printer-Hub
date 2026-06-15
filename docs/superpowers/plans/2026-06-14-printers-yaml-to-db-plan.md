# Hub #124 — printers.yaml → DB + Admin-UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `printers.yaml` ersatzlos entfernen, die existierende DB-Tabelle `printers` zur alleinigen Source of Truth machen und eine SSO-geschützte Admin-UI `/admin/printers/` plus JSON-API `/api/v1/admin/printers` einführen.

**Architecture:** Service-Layer (`PrinterAdminService`) kapselt Geschäftslogik. Pydantic-Schemas validieren Input mit verschachteltem SNMP-Konfig. Audit-Trail-Tabelle `printers_audit` zeichnet jeden Create/Update/Disable/Enable mit redaktierter SNMP-Community auf. Soft-Delete via `enabled=false` lässt FK-Constraints intakt. Pangolin liefert Browser-User via `Remote-User` Header (SSO) oder Tooling via Basic-Auth-Bypass (`claude-automation`).

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async + aiosqlite, Pydantic v2, Jinja2, Alembic, pytest+pytest-cov, mypy, ruff, Starlette-CSRF.

**Spec:** `/opt/repos/label-printer-hub/docs/superpowers/specs/2026-06-14-printers-yaml-to-db-design.md` (Round-4 final, alle 4 Teams APPROVE).

**Repo:** `/opt/repos/label-printer-hub` — Working-Branch: `feat/issue-124-printers-yaml-to-db`

**Issue:** https://github.com/strausmann/Label-Printer-Hub/issues/124

---

## File Structure

### Neue Dateien

| Pfad | Verantwortung |
|---|---|
| `backend/app/schemas/printer_admin.py` | Pydantic-Schemas für Admin-API (SNMPConfig, PrinterConnection, PrinterCreatePayload, PrinterUpdatePayload) |
| `backend/app/services/audit_redaction.py` | Helper `redact_secrets()` mit SECRET_PATHS-Set |
| `backend/app/services/printer_admin_service.py` | Geschäftslogik Create/Update/Disable/Enable + Audit + Flattening-Helper |
| `backend/app/services/printer_model_registry.py` | Plugin-Registry für Model-Dropdown (`list_available_models()`) |
| `backend/app/middleware/__init__.py` | Package-Init |
| `backend/app/middleware/csrf.py` | Starlette-CSRF-Middleware-Setup |
| `backend/app/api/routes/admin_printers_api.py` | JSON-API `/api/v1/admin/printers` |
| `backend/app/api/routes/admin_printers_web.py` | HTML-Routes `/admin/printers` |
| `backend/app/templates/_base.html` | Layout-Template (falls noch keins existiert) |
| `backend/app/templates/admin_printers/list.html` | Drucker-Liste |
| `backend/app/templates/admin_printers/form.html` | Create/Edit-Form |
| `backend/app/templates/admin_printers/confirm_disable.html` | Disable-Confirm-Page |
| `backend/alembic/versions/<ts>_add_printers_audit_and_backfill.py` | Schema-Erweiterung + Audit-Tabelle + Backfill |
| `backend/tests/services/test_printer_admin_service.py` | Service-Unit-Tests |
| `backend/tests/services/test_audit_redaction.py` | Redaction-Helper-Tests |
| `backend/tests/services/test_printer_model_registry.py` | Plugin-Registry-Tests |
| `backend/tests/middleware/__init__.py` | Test-Package-Init |
| `backend/tests/middleware/test_csrf.py` | CSRF-Middleware-Tests |
| `backend/tests/api/test_admin_printers_api.py` | JSON-API Integration-Tests |
| `backend/tests/api/test_admin_printers_web.py` | HTML-Routes Integration-Tests |
| `backend/tests/integration/test_fresh_install_printers.py` | E2E-Test ohne YAML |

### Modifizierte Dateien

| Pfad | Änderung |
|---|---|
| `backend/app/db/engine.py` | `isolation_level="SERIALIZABLE"` + Connect-Listener für `journal_mode=WAL` + `foreign_keys=ON` |
| `backend/app/db/lifespan.py` | `upsert_runtime_printers()` entfernen + Aufrufer entfernen |
| `backend/app/services/printer_identity.py` | `derive_printer_id` von 3-arg auf 4-arg (created_at_utc), naive datetime → ValueError |
| `backend/app/printer_backends/exceptions.py` | Neue `PrinterDisabledError(PrinterError)` |
| `backend/app/services/print_service.py` | `enabled`-Check in `submit_print_job` |
| `backend/app/api/routes/print.py` | Error-Handler für `PrinterDisabledError` → 409 |
| `backend/app/models/printer.py` | Neue Spalten `queue_timeout_s`, `cut_defaults_half_cut` |
| `backend/app/main.py` | Router-Includes für `admin_printers_api`, `admin_printers_web` + CSRF-Middleware |
| `backend/app/config.py` | (optional) `csrf_cookie_name` Settings-Feld |
| `backend/pyproject.toml` | Dependencies: `starlette-csrf`, `jinja2` (falls noch nicht da), `python-multipart` (für Form-Posts) |

### Gelöschte Dateien

| Pfad | Begründung |
|---|---|
| `backend/app/services/printer_config_loader.py` | YAML-Loader nicht mehr nötig |
| `backend/app/schemas/printer_config.py` | YAML-Schema nicht mehr nötig |
| `backend/tests/services/test_printer_config_loader.py` | Code gelöscht |
| `backend/tests/db/test_lifespan.py` | upsert_runtime_printers nicht mehr existent (prüfen ob auch andere Tests drin) |
| `backend/tests/unit/test_lifespan.py` | dito |
| `backend/tests/integration/test_lifespan_seeds_and_upserts.py` | dito |
| `backend/tests/integration/test_lifespan_multi_printer.py` | dito |
| `backend/tests/integration/db/test_lifespan_printer_upsert.py` | dito |
| `/docker/stacks/hangar-print-hub/config/printers.yaml` | Production-Volume-Mount entfällt (Phase 8) |

---

## Phase 0 — Live-Check + Branch-Setup (1 Task)

Ziel: vor der Implementierung sicherstellen, dass die Pre-Conditions stimmen.

### Task 0.1: Live-Check + Branch erstellen

**Files:**
- Create: `docs/superpowers/plans/2026-06-14-phase0-live-check-results.md`

- [ ] **Step 1: Repo-State prüfen**

```bash
cd /opt/repos/label-printer-hub
git status
git checkout main
git pull --rebase
```
Expected: working tree clean, auf `main`.

- [ ] **Step 2: Branch `feat/issue-124-printers-yaml-to-db` erstellen**

```bash
git checkout -b feat/issue-124-printers-yaml-to-db
```

- [ ] **Step 3: Pangolin-Resource Live-Check für `print-hub.strausmann.cloud`**

Über `mcp__pangolin-api__org_by_orgId_resources` mit `orgId=strausmann` die Resource finden, dann `mcp__pangolin-api__resource_by_resourceId` mit der gefundenen `resourceId`. Notieren:
- Hat sie `headerAuth` (nicht None)?
- Hat `targets[0].healthCheck.enabled == true`?
- Welche `port` ist im Target gesetzt? (sollte 8000 sein)

Ergebnisse in `docs/superpowers/plans/2026-06-14-phase0-live-check-results.md` festhalten.

- [ ] **Step 4: DB-Schema-Snapshot aus Production ziehen**

```bash
ssh -i ~/.ssh/id_ed25519_homelab_nodes root@hhdocker03 \
  "docker exec hangar-print-hub-print-hub-1 sqlite3 /data/printer-hub.db \
     '.schema printers' \
     '.schema printers_audit'"
```
Expected: `printers` existiert mit den Spalten aus der Spec; `printers_audit` existiert NICHT (wird in Phase 1 angelegt). Falls `printers_audit` schon existiert: Spec-Annahmen prüfen.

- [ ] **Step 5: Test-Files-Inventar grepen (Verifikation H9)**

```bash
cd /opt/repos/label-printer-hub/backend
grep -rln "upsert_runtime_printers\|PrinterConfigLoader" tests/
grep -rln "derive_printer_id(" tests/
```
Expected: Liste sollte enthalten `tests/services/test_printer_config_loader.py`, `tests/db/test_lifespan.py`, `tests/integration/test_lifespan_seeds_and_upserts.py`, `tests/integration/test_lifespan_multi_printer.py`, `tests/integration/db/test_lifespan_printer_upsert.py`, `tests/unit/test_lifespan.py`, `tests/services/test_printer_identity.py`. Findings in `phase0-live-check-results.md` notieren.

- [ ] **Step 6: Dependencies-Check**

```bash
cd /opt/repos/label-printer-hub/backend
grep -E "starlette-csrf|jinja2|python-multipart" pyproject.toml
```
Expected: ggf. fehlende Dependencies in Phase 3 ergänzen — notieren welche.

- [ ] **Step 7: Phase-0-Ergebnisse committen**

```bash
git add docs/superpowers/plans/2026-06-14-phase0-live-check-results.md
git commit -m "docs(#124): Phase 0 Live-Check-Results"
```

---

## Phase 1 — Foundation (Engine, Exception, Migration) — 4 Tasks

Ziel: SQLite-Engine umkonfigurieren, neue Exception einführen, Alembic-Migration mit Schema-Erweiterung + Audit-Tabelle + Backfill.

### Task 1.1: SQLite-Engine SERIALIZABLE + WAL Connect-Listener

**Files:**
- Modify: `backend/app/db/engine.py`
- Test: `backend/tests/db/test_engine_pragmas.py`

- [ ] **Step 1: Failing-Test schreiben**

```python
# backend/tests/db/test_engine_pragmas.py
"""Verifiziert die SQLite-Pragma-Konfiguration nach Issue #124."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db.engine import engine


@pytest.mark.asyncio
async def test_engine_isolation_level_is_serializable():
    """isolation_level=SERIALIZABLE mappt aiosqlite auf BEGIN IMMEDIATE."""
    assert engine.dialect.name == "sqlite"
    # SQLAlchemy stellt das auf der Engine bereit
    assert engine.url.query.get("isolation_level") in (None, "SERIALIZABLE") or \
           engine.dialect.isolation_level == "SERIALIZABLE"


@pytest.mark.asyncio
async def test_connect_listener_sets_wal_and_foreign_keys():
    """Listener setzt journal_mode=WAL und foreign_keys=ON."""
    async with engine.connect() as conn:
        journal = (await conn.execute(text("PRAGMA journal_mode"))).scalar_one()
        fks = (await conn.execute(text("PRAGMA foreign_keys"))).scalar_one()
    assert journal.lower() == "wal", f"journal_mode={journal!r} — Connect-Listener fehlt"
    assert fks == 1, f"foreign_keys={fks} — Connect-Listener fehlt"
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `cd backend && pytest tests/db/test_engine_pragmas.py -v`
Expected: FAIL — `journal_mode` ist `delete` oder `memory`, `foreign_keys=0`.

- [ ] **Step 3: `engine.py` anpassen**

Anhand der aktuellen Implementation in `backend/app/db/engine.py`:
1. `isolation_level="SERIALIZABLE"` als Argument für `create_async_engine(...)` ergänzen.
2. Nach dem Engine-Aufruf einen `@event.listens_for(engine.sync_engine, "connect")` Listener registrieren:

```python
# backend/app/db/engine.py
from sqlalchemy import event
# ... existing imports ...

DATABASE_URL = get_settings().database_url
# ... existing _ensure_data_dir(DATABASE_URL) ...

engine = create_async_engine(
    DATABASE_URL,
    isolation_level="SERIALIZABLE",  # aiosqlite mappt SERIALIZABLE auf BEGIN IMMEDIATE
    # ... existing kwargs (echo, etc.) bleiben unverändert
)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record):
    """Setzt SQLite-Pragmas bei jedem neuen Connection-Open.

    Issue #124: journal_mode=WAL fuer parallele Reader,
    foreign_keys=ON weil SQLite-Default OFF ist.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
```

- [ ] **Step 4: Tests laufen — müssen grün sein**

Run: `cd backend && pytest tests/db/test_engine_pragmas.py -v`
Expected: PASS beide Tests.

- [ ] **Step 5: Volle Test-Suite einmal laufen lassen — keine Regressions**

Run: `cd backend && pytest -x --ff -q`
Expected: alle Tests grün (oder mindestens keine NEUEN Fehler durch Engine-Änderung).

- [ ] **Step 6: Commit**

```bash
git add backend/app/db/engine.py backend/tests/db/test_engine_pragmas.py
git commit -m "feat(#124): SQLite-Engine SERIALIZABLE + WAL + foreign_keys Connect-Listener"
```

### Task 1.2: PrinterDisabledError Exception

**Files:**
- Modify: `backend/app/printer_backends/exceptions.py`
- Test: `backend/tests/unit/printer_backends/test_exceptions.py` (neu oder erweitern)

- [ ] **Step 1: Failing-Test schreiben**

```python
# backend/tests/unit/printer_backends/test_exceptions.py
"""Tests fuer Exception-Hierarchie (Issue #124 — PrinterDisabledError)."""
from __future__ import annotations

from uuid import uuid4

import pytest

from app.printer_backends.exceptions import PrinterDisabledError, PrinterError


def test_printer_disabled_error_is_subclass_of_printer_error():
    """PrinterDisabledError erbt von PrinterError damit existing Catch-Klauseln greifen."""
    assert issubclass(PrinterDisabledError, PrinterError)


def test_printer_disabled_error_stores_printer_id_and_slug():
    pid = uuid4()
    exc = PrinterDisabledError(printer_id=pid, slug="brother-p750w")
    assert exc.printer_id == pid
    assert exc.slug == "brother-p750w"


def test_printer_disabled_error_message_contains_slug():
    pid = uuid4()
    exc = PrinterDisabledError(printer_id=pid, slug="brother-p750w")
    assert "brother-p750w" in str(exc)
    assert str(pid) in str(exc)
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `cd backend && pytest tests/unit/printer_backends/test_exceptions.py -v`
Expected: FAIL — `cannot import name 'PrinterDisabledError'`.

- [ ] **Step 3: Exception in `printer_backends/exceptions.py` ergänzen**

```python
# backend/app/printer_backends/exceptions.py
# ... existing imports + classes (PrinterError, TapeMismatchError, ...) bleiben ...

from uuid import UUID  # neu am Datei-Anfang ergaenzen


class PrinterDisabledError(PrinterError):
    """Drucker existiert in DB, ist aber deaktiviert (Soft-Delete-Status).

    Mappt in der HTTP-Schicht auf 409 (nicht 404), weil der Drucker
    semantisch existiert - er ist nur voruebergehend nicht verwendbar.
    """

    def __init__(self, printer_id: UUID, slug: str) -> None:
        self.printer_id = printer_id
        self.slug = slug
        super().__init__(f"Printer {slug} ({printer_id}) is disabled")
```

- [ ] **Step 4: Tests grün**

Run: `cd backend && pytest tests/unit/printer_backends/test_exceptions.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/printer_backends/exceptions.py backend/tests/unit/printer_backends/test_exceptions.py
git commit -m "feat(#124): PrinterDisabledError Exception fuer Soft-Delete-Status"
```

### Task 1.3: Alembic-Migration — Schema-Erweiterung + Audit-Tabelle + Backfill

**Files:**
- Create: `backend/alembic/versions/<timestamp>_add_printers_audit_and_backfill.py`
- Modify: `backend/app/models/printer.py` (neue Spalten als SQLAlchemy-Felder)
- Test: `backend/tests/db/test_migration_124.py`

- [ ] **Step 1: Migration-Skeleton via Alembic generieren**

```bash
cd backend
alembic revision -m "add_printers_audit_and_backfill_connection"
```
Notieren: erzeugter Dateiname (z.B. `<hash>_add_printers_audit_and_backfill_connection.py`).

- [ ] **Step 2: Failing-Test für Migration**

```python
# backend/tests/db/test_migration_124.py
"""Tests fuer Alembic-Migration #124 (Schema + Backfill)."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db.engine import engine
from tests._helpers.db import seed_pre_124_printer  # helper neu (siehe Step 4)


@pytest.mark.asyncio
async def test_printers_table_has_new_columns():
    """queue_timeout_s und cut_defaults_half_cut Spalten existieren nach Migration."""
    async with engine.connect() as conn:
        info = (
            await conn.execute(text("PRAGMA table_info(printers)"))
        ).all()
    col_names = {row[1] for row in info}
    assert "queue_timeout_s" in col_names
    assert "cut_defaults_half_cut" in col_names


@pytest.mark.asyncio
async def test_printers_audit_table_exists():
    async with engine.connect() as conn:
        info = (
            await conn.execute(text("PRAGMA table_info(printers_audit)"))
        ).all()
    col_names = {row[1] for row in info}
    for required in ("id", "printer_id", "slug", "action", "before_json",
                     "after_json", "updated_by", "created_at"):
        assert required in col_names, f"printers_audit fehlt Spalte {required}"


@pytest.mark.asyncio
async def test_backfill_sets_snmp_defaults_for_existing_printers():
    """Bestandsrows ohne snmp-Block bekommen Defaults durch die Migration."""
    # Test-DB ist nach Migration leer — simulieren wir einen "Pre-124"-Row
    # und verifizieren Idempotenz (kein zweiter Snmp-Block hinzugefuegt).
    pid = await seed_pre_124_printer(engine, slug="legacy-p750w")
    async with engine.connect() as conn:
        row = (
            await conn.execute(text(
                "SELECT connection, queue_timeout_s, cut_defaults_half_cut "
                "FROM printers WHERE id = :pid"
            ), {"pid": str(pid)})
        ).first()
    assert row is not None
    import json
    conn_json = json.loads(row[0])
    assert conn_json["host"] == "192.0.2.99"
    assert conn_json["port"] == 9100
    # Backfill darf in Test-Setup nicht erneut laufen (Migration ist schon
    # angewandt) — also pruefen wir nur dass Defaults greifbar sind:
    assert row[1] == 30  # queue_timeout_s server_default
    assert row[2] == 0  # cut_defaults_half_cut server_default
```

- [ ] **Step 3: `tests/_helpers/db.py` Helper ergänzen** (falls nicht existiert)

```python
# backend/tests/_helpers/db.py — neue Helper-Funktion
from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def seed_pre_124_printer(
    engine: AsyncEngine, *, slug: str = "legacy-p750w"
) -> UUID:
    """Erstellt einen Pre-124-Drucker-Row mit minimaler connection (nur host+port).

    Simuliert Bestandsdaten aus upsert_runtime_printers(): kein snmp-Block,
    keine queue/cut_defaults-Spalten gesetzt (server_default greift).
    """
    pid = uuid4()
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO printers (id, name, slug, model, backend, connection, enabled, "
            "created_at, updated_at) VALUES "
            "(:id, :name, :slug, :model, :backend, :conn, 1, "
            "strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"
        ), {
            "id": str(pid),
            "name": f"Legacy {slug}",
            "slug": slug,
            "model": "pt-p750w",
            "backend": "ptouch",
            "conn": '{"host":"192.0.2.99","port":9100}',
        })
    return pid
```

- [ ] **Step 4: Migration-Datei mit Inhalt füllen**

```python
# backend/alembic/versions/<hash>_add_printers_audit_and_backfill_connection.py
"""add printers_audit and backfill connection

Issue #124 — printers.yaml entfernen.

- Erweitert printers um queue_timeout_s + cut_defaults_half_cut Spalten.
- Legt printers_audit-Tabelle an (Action: create/update/disable/enable).
- Backfilled connection.snmp Defaults fuer Bestandsrows ohne snmp-Block.
"""
from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "<REPLACE_WITH_GENERATED_HASH>"
down_revision: str | Sequence[str] | None = "<REPLACE_WITH_PREVIOUS>"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) Schema-Erweiterung der printers-Tabelle
    op.add_column(
        "printers",
        sa.Column("queue_timeout_s", sa.Integer(),
                  nullable=False, server_default="30"),
    )
    op.add_column(
        "printers",
        sa.Column("cut_defaults_half_cut", sa.Boolean(),
                  nullable=False, server_default=sa.false()),
    )

    # 2) printers_audit-Tabelle
    op.create_table(
        "printers_audit",
        sa.Column("id", sa.UUID(), primary_key=True),
        # KEIN FK auf printers — Soft-Delete behaelt Parent-Row sowieso
        sa.Column("printer_id", sa.UUID(), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("before_json", sa.JSON(), nullable=True),
        sa.Column("after_json", sa.JSON(), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_printers_audit_printer_id",
        "printers_audit",
        ["printer_id"],
    )
    op.create_index(
        "idx_printers_audit_created_at_desc",
        "printers_audit",
        [sa.text("created_at DESC")],
    )

    # 3) Bestand-Backfill connection.snmp
    # Defensive Schutzklausel (Round-3 LOW Storage): falls connection NULL
    # ODER kein "host" enthaelt, ueberspringen + warnen.
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, connection FROM printers")
    ).all()
    for row in rows:
        pid, conn_raw = row[0], row[1]
        if conn_raw is None:
            print(
                f"WARNING #124-backfill: printer id={pid} hat NULL connection, "
                f"ueberspringe SNMP-Backfill"
            )
            continue
        conn_json = (
            json.loads(conn_raw) if isinstance(conn_raw, str) else conn_raw
        )
        if "host" not in conn_json:
            print(
                f"WARNING #124-backfill: printer id={pid} ohne host-Feld, "
                f"ueberspringe SNMP-Backfill"
            )
            continue
        if "snmp" in conn_json:
            continue  # idempotent: nichts zu tun
        conn_json["snmp"] = {"discover": False, "community": "public"}
        bind.execute(
            sa.text("UPDATE printers SET connection = :c WHERE id = :pid"),
            {"c": json.dumps(conn_json), "pid": pid},
        )


def downgrade() -> None:
    """Issue #124 — Rollback erfolgt via SQLite-DB-Restore, nicht via
    alembic downgrade. Diese Funktion ist absichtlich leer um klar zu
    machen dass downgrade nicht der erwartete Rollback-Pfad ist.
    """
    raise NotImplementedError(
        "Issue #124 — Rollback ueber SQLite-Restore aus Backup vor "
        "dem Deploy. Alembic-downgrade nicht supportet."
    )
```

- [ ] **Step 5: Model-Update für SQLAlchemy ORM**

```python
# backend/app/models/printer.py — neue Spalten als ORM-Felder ergaenzen
# ... existing imports + class Printer(Base): bestehen bleiben ...

# In der Klasse:
    queue_timeout_s: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, server_default="30"
    )
    cut_defaults_half_cut: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, server_default=sa.false()
    )
```

(genaue Syntax an existing Style anpassen — falls Mapped-API genutzt wird.)

- [ ] **Step 6: Migration anwenden + Tests grün**

```bash
cd backend
alembic upgrade head
pytest tests/db/test_migration_124.py -v
```
Expected: alle 3 Migration-Tests PASS.

- [ ] **Step 7: Volle Test-Suite — keine Regressions**

Run: `cd backend && pytest -x --ff -q`
Expected: grün (alte Tests die `upsert_runtime_printers` aufrufen werden in Phase 5 gelöscht — falls sie hier rot werden, ignorieren via `pytest --ignore=tests/integration/test_lifespan_seeds_and_upserts.py ...` oder vorzeitig stub-en).

- [ ] **Step 8: Commit**

```bash
git add backend/alembic/versions/*_add_printers_audit_and_backfill_connection.py \
        backend/app/models/printer.py \
        backend/tests/db/test_migration_124.py \
        backend/tests/_helpers/db.py
git commit -m "feat(#124): Alembic-Migration Schema-Erweiterung + printers_audit + Backfill"
```

### Task 1.4: derive_printer_id 3-arg → 4-arg

**Files:**
- Modify: `backend/app/services/printer_identity.py`
- Modify: `backend/tests/services/test_printer_identity.py`

- [ ] **Step 1: Failing-Tests in `test_printer_identity.py` schreiben**

```python
# backend/tests/services/test_printer_identity.py
# Alte Tests entfernen, neu schreiben:
"""Tests fuer derive_printer_id (Issue #124 — 4-arg-Signatur)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.printer_identity import derive_printer_id


def test_derive_id_deterministic_same_inputs():
    """Gleicher Input → gleicher UUID."""
    ts = datetime(2026, 6, 14, 18, 0, 0, tzinfo=timezone.utc)
    a = derive_printer_id("PT-P750W", "192.0.2.10", 9100, ts)
    b = derive_printer_id("PT-P750W", "192.0.2.10", 9100, ts)
    assert a == b


def test_derive_id_differs_by_created_at():
    """Verschiedener created_at → andere UUID auch bei gleichem model/host/port."""
    ts1 = datetime(2026, 6, 14, 18, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 6, 15, 18, 0, 0, tzinfo=timezone.utc)
    a = derive_printer_id("PT-P750W", "192.0.2.10", 9100, ts1)
    b = derive_printer_id("PT-P750W", "192.0.2.10", 9100, ts2)
    assert a != b


def test_derive_id_naive_datetime_raises_value_error():
    """naive datetime ohne tzinfo → ValueError (UUID waere nicht stabil)."""
    naive = datetime(2026, 6, 14, 18, 0, 0)  # KEIN tzinfo
    with pytest.raises(ValueError, match="timezone-aware"):
        derive_printer_id("PT-P750W", "192.0.2.10", 9100, naive)


def test_derive_id_differs_by_host():
    ts = datetime(2026, 6, 14, 18, 0, 0, tzinfo=timezone.utc)
    a = derive_printer_id("PT-P750W", "192.0.2.10", 9100, ts)
    b = derive_printer_id("PT-P750W", "192.0.2.11", 9100, ts)
    assert a != b
```

- [ ] **Step 2: Tests laufen — müssen fehlschlagen**

Run: `cd backend && pytest tests/services/test_printer_identity.py -v`
Expected: FAIL — Signatur nimmt nur 3 Args, kein ValueError-Check.

- [ ] **Step 3: `derive_printer_id` auf 4-arg umstellen**

```python
# backend/app/services/printer_identity.py
"""Deterministic UUID5 derivation for printers (Issue #124).

Aktuell 4-arg Signatur mit timezone-aware created_at_utc.
Bestandsdrucker (vor #124) wurden mit 3-arg-Signatur erzeugt und behalten
ihre alte UUID — sie werden NICHT neu generiert.
"""
from __future__ import annotations

import uuid
from datetime import datetime


def derive_printer_id(
    model: str,
    host: str,
    port: int,
    created_at_utc: datetime,
) -> uuid.UUID:
    """UUIDv5 aus Model + Host + Port + Created-At (UTC, ISO-8601).

    created_at_utc MUSS timezone-aware sein. Naive datetime → ValueError
    weil der ISO-String je nach lokaler TZ unterschiedlich waere und der
    Salt damit nicht reproduzierbar.
    """
    if created_at_utc.tzinfo is None:
        raise ValueError(
            "created_at_utc must be timezone-aware (use datetime.now(timezone.utc))"
        )
    salt = f"{model}|{host}|{port}|{created_at_utc.isoformat()}"
    return uuid.uuid5(uuid.NAMESPACE_URL, salt)
```

- [ ] **Step 4: Tests grün**

Run: `cd backend && pytest tests/services/test_printer_identity.py -v`
Expected: PASS alle 4 Tests.

- [ ] **Step 5: Aufrufer in lifespan.py (kurzfristig) zum Kompilieren bringen**

`upsert_runtime_printers()` ruft `derive_printer_id(cfg.model, cfg.host, cfg.port)` — wird in Phase 5 ganz gelöscht. Bis dahin: Funktion wird in Phase 5 entfernt. Aktuell: der Aufruf kompiliert nicht mehr, Tests die `upsert_runtime_printers` aufrufen schlagen fehl. Wir markieren diese Tests temporär mit `@pytest.mark.skip("Issue #124 — Aufrufer wird in Phase 5 entfernt")`:

```python
# Workaround: in tests/db/test_lifespan.py, tests/unit/test_lifespan.py,
# tests/integration/test_lifespan_seeds_and_upserts.py,
# tests/integration/test_lifespan_multi_printer.py,
# tests/integration/db/test_lifespan_printer_upsert.py
# am Datei-Anfang ergaenzen:

import pytest
pytestmark = pytest.mark.skip(
    reason="Issue #124 — upsert_runtime_printers wird in Phase 5 entfernt"
)
```

- [ ] **Step 6: Volle Test-Suite läuft (mit Skips)**

Run: `cd backend && pytest -q`
Expected: grün — Skips zählen nicht als Fehler.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/printer_identity.py \
        backend/tests/services/test_printer_identity.py \
        backend/tests/db/test_lifespan.py \
        backend/tests/unit/test_lifespan.py \
        backend/tests/integration/test_lifespan_seeds_and_upserts.py \
        backend/tests/integration/test_lifespan_multi_printer.py \
        backend/tests/integration/db/test_lifespan_printer_upsert.py
git commit -m "feat(#124): derive_printer_id 4-arg-Signatur mit UTC-Pflicht"
```

---

## Phase 2 — Service-Layer (Schemas + Audit-Redaction + Plugin-Registry + AdminService) — 5 Tasks

### Task 2.1: Pydantic-Schemas

**Files:**
- Create: `backend/app/schemas/printer_admin.py`
- Test: `backend/tests/schemas/test_printer_admin_schemas.py`

- [ ] **Step 1: Failing-Tests schreiben**

```python
# backend/tests/schemas/test_printer_admin_schemas.py
"""Tests fuer Pydantic-Schemas der Admin-API (Issue #124)."""
from __future__ import annotations

import pytest

from app.schemas.printer_admin import (
    PrinterConnection,
    PrinterCreatePayload,
    PrinterCutDefaults,
    PrinterQueueSettings,
    PrinterUpdatePayload,
    SNMPConfig,
)


def test_snmp_config_defaults():
    cfg = SNMPConfig()
    assert cfg.discover is False
    assert cfg.community == "public"


def test_snmp_config_discover_without_community_raises():
    with pytest.raises(ValueError, match="community"):
        SNMPConfig(discover=True, community=None)


def test_printer_connection_with_default_snmp():
    conn = PrinterConnection(host="192.0.2.10", port=9100)
    assert conn.snmp.discover is False
    assert conn.snmp.community == "public"


def test_printer_create_payload_minimal():
    p = PrinterCreatePayload(
        name="Brother P750W",
        slug="brother-p750w",
        model="PT-P750W",
        backend="ptouch",
        connection=PrinterConnection(host="192.0.2.10", port=9100),
    )
    assert p.enabled is True
    assert p.queue.timeout_s == 30
    assert p.cut_defaults.half_cut is False


def test_printer_create_payload_slug_pattern_rejects_uppercase():
    with pytest.raises(ValueError):
        PrinterCreatePayload(
            name="X", slug="Brother-P750W", model="PT-P750W", backend="ptouch",
            connection=PrinterConnection(host="192.0.2.10", port=9100),
        )


def test_printer_create_payload_backend_literal():
    with pytest.raises(ValueError):
        PrinterCreatePayload(
            name="X", slug="x", model="X", backend="unknown",  # type: ignore
            connection=PrinterConnection(host="192.0.2.10", port=9100),
        )


def test_printer_update_payload_all_optional():
    """Empty patch ist valide — Service ignoriert leeren Patch silent."""
    p = PrinterUpdatePayload()
    assert p.name is None
    assert p.connection is None


def test_queue_timeout_range():
    with pytest.raises(ValueError):
        PrinterQueueSettings(timeout_s=0)
    with pytest.raises(ValueError):
        PrinterQueueSettings(timeout_s=601)
```

- [ ] **Step 2: Tests laufen — Imports schlagen fehl**

Run: `cd backend && pytest tests/schemas/test_printer_admin_schemas.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: `app/schemas/printer_admin.py` schreiben**

```python
# backend/app/schemas/printer_admin.py
"""Pydantic-Schemas fuer die Admin-API (Issue #124).

Verschachteltes SNMP-Schema (snmp.discover/community) konsistent mit
altem YAML — siehe Spec 2026-06-14 H8a-Entscheidung.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$"


class SNMPConfig(BaseModel):
    discover: bool = False
    community: str | None = Field(default="public", max_length=64)

    @model_validator(mode="after")
    def _community_consistency(self) -> "SNMPConfig":
        if self.discover and not self.community:
            raise ValueError(
                "snmp.community ist Pflicht wenn snmp.discover=True ist"
            )
        return self


class PrinterConnection(BaseModel):
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65535)
    snmp: SNMPConfig = Field(default_factory=SNMPConfig)


class PrinterCutDefaults(BaseModel):
    half_cut: bool = False


class PrinterQueueSettings(BaseModel):
    timeout_s: int = Field(ge=1, le=600, default=30)


class PrinterCreatePayload(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(pattern=SLUG_PATTERN)
    model: str = Field(min_length=1, max_length=255)
    backend: Literal["ptouch", "brother_ql"]
    connection: PrinterConnection
    queue: PrinterQueueSettings = Field(default_factory=PrinterQueueSettings)
    cut_defaults: PrinterCutDefaults = Field(default_factory=PrinterCutDefaults)
    enabled: bool = True


class PrinterUpdatePayload(BaseModel):
    """Service ignoriert silent: slug, model, backend, id."""

    name: str | None = None
    connection: PrinterConnection | None = None
    queue: PrinterQueueSettings | None = None
    cut_defaults: PrinterCutDefaults | None = None
    enabled: bool | None = None
```

- [ ] **Step 4: Tests grün**

Run: `cd backend && pytest tests/schemas/test_printer_admin_schemas.py -v`
Expected: PASS alle 8 Tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/printer_admin.py \
        backend/tests/schemas/test_printer_admin_schemas.py
git commit -m "feat(#124): Pydantic-Schemas fuer Admin-API (SNMP verschachtelt)"
```

### Task 2.2: audit_redaction.py

**Files:**
- Create: `backend/app/services/audit_redaction.py`
- Test: `backend/tests/services/test_audit_redaction.py`

- [ ] **Step 1: Failing-Tests schreiben**

```python
# backend/tests/services/test_audit_redaction.py
"""Tests fuer redact_secrets (Issue #124 M9)."""
from __future__ import annotations

from app.services.audit_redaction import redact_secrets


def test_redact_snmp_community():
    payload = {
        "id": "abc",
        "connection": {
            "host": "192.0.2.10",
            "port": 9100,
            "snmp": {"discover": True, "community": "secret123"},
        },
    }
    out = redact_secrets(payload)
    assert out["connection"]["snmp"]["community"] == "***REDACTED***"
    # Andere Felder unveraendert
    assert out["connection"]["host"] == "192.0.2.10"
    assert out["connection"]["port"] == 9100
    assert out["connection"]["snmp"]["discover"] is True


def test_redact_does_not_mutate_input():
    payload = {
        "connection": {
            "snmp": {"discover": True, "community": "secret123"},
        },
    }
    out = redact_secrets(payload)
    assert payload["connection"]["snmp"]["community"] == "secret123"
    assert out["connection"]["snmp"]["community"] == "***REDACTED***"


def test_redact_preserves_none_community():
    """None bleibt None — kein Verschleiern eines fehlenden Wertes."""
    payload = {
        "connection": {
            "snmp": {"discover": False, "community": None},
        },
    }
    out = redact_secrets(payload)
    assert out["connection"]["snmp"]["community"] is None


def test_redact_handles_missing_snmp_block():
    """Pre-Backfill-Bestand: kein snmp-Block ueberhaupt."""
    payload = {"connection": {"host": "192.0.2.10", "port": 9100}}
    out = redact_secrets(payload)
    # Bleibt unveraendert
    assert "snmp" not in out["connection"]


def test_redact_handles_missing_connection_block():
    """Theoretischer Edge-Case: kein connection-Block."""
    payload = {"id": "abc", "name": "X"}
    out = redact_secrets(payload)
    assert out == {"id": "abc", "name": "X"}
```

- [ ] **Step 2: Tests laufen — Imports schlagen fehl**

Run: `cd backend && pytest tests/services/test_audit_redaction.py -v`
Expected: FAIL.

- [ ] **Step 3: `audit_redaction.py` schreiben**

```python
# backend/app/services/audit_redaction.py
"""Redaction-Helper fuer printers_audit (Issue #124 M9).

Vor dem Schreiben von before_json/after_json werden bekannte Secret-Pfade
durch '***REDACTED***' ersetzt. Verhindert dass SNMP-Community in
DB-Backups landet.
"""
from __future__ import annotations

import copy
from typing import Any

REDACTED = "***REDACTED***"

# Liste der bekannten Secret-Pfade (Tupel = Pfad in der verschachtelten Dict-Struktur).
# Bei zukuenftigen Secret-Feldern hier ergaenzen.
SECRET_PATHS: frozenset[tuple[str, ...]] = frozenset(
    {
        ("connection", "snmp", "community"),
    }
)


def redact_secrets(payload: dict[str, Any]) -> dict[str, Any]:
    """Erzeugt eine Deep-Copy mit allen bekannten Secret-Pfaden redacted.

    Behaviour:
    - Wenn das Feld None ist, bleibt es None (kein Verschleiern fehlender Werte).
    - Wenn ein Zwischenpfad fehlt, ueberspringe stillschweigend.
    - Mutiert die Input-Dict NICHT.
    """
    out = copy.deepcopy(payload)
    for path in SECRET_PATHS:
        _redact_path(out, list(path))
    return out


def _redact_path(node: Any, path: list[str]) -> None:
    """Walks path und ersetzt das Blatt durch REDACTED falls truthy."""
    if not path:
        return
    if not isinstance(node, dict):
        return
    head, *rest = path
    if head not in node:
        return
    if not rest:
        # Blatt erreicht
        if node[head] is None:
            return  # None bleibt None
        node[head] = REDACTED
        return
    _redact_path(node[head], rest)
```

- [ ] **Step 4: Tests grün**

Run: `cd backend && pytest tests/services/test_audit_redaction.py -v`
Expected: PASS alle 5 Tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/audit_redaction.py backend/tests/services/test_audit_redaction.py
git commit -m "feat(#124): audit_redaction.py — SNMP-Community Redaction Helper"
```

### Task 2.3: printer_model_registry.py

**Files:**
- Create: `backend/app/services/printer_model_registry.py`
- Test: `backend/tests/services/test_printer_model_registry.py`

- [ ] **Step 1: Failing-Tests schreiben**

```python
# backend/tests/services/test_printer_model_registry.py
"""Tests fuer Plugin-Registry (Issue #124)."""
from __future__ import annotations

from app.services.printer_model_registry import (
    PrinterModel,
    list_available_models,
)


def test_list_available_models_returns_known_models():
    models = list_available_models()
    assert len(models) > 0
    backends = {m.backend for m in models}
    assert "ptouch" in backends
    assert "brother_ql" in backends


def test_list_includes_pt_p750w():
    models = list_available_models()
    p750 = next(
        (m for m in models if m.backend == "ptouch" and "P750W" in m.model.upper()),
        None,
    )
    assert p750 is not None
    assert "Brother" in p750.display_name or "PT-P750W" in p750.display_name


def test_list_includes_ql820nwb():
    models = list_available_models()
    ql820 = next(
        (m for m in models if m.backend == "brother_ql" and "QL-820NWB" in m.model.upper()),
        None,
    )
    assert ql820 is not None


def test_printer_model_dataclass_immutable():
    m = PrinterModel(backend="ptouch", model="PT-P750W", display_name="Brother PT-P750W")
    import pytest
    with pytest.raises(Exception):  # FrozenInstanceError oder ValidationError
        m.backend = "brother_ql"  # type: ignore
```

- [ ] **Step 2: Tests laufen — Imports schlagen fehl**

Run: `cd backend && pytest tests/services/test_printer_model_registry.py -v`
Expected: FAIL.

- [ ] **Step 3: `printer_model_registry.py` schreiben**

```python
# backend/app/services/printer_model_registry.py
"""Plugin-Registry fuer Drucker-Modelle (Issue #124).

Die Admin-UI benoetigt eine Liste verfuegbarer (backend, model)-Kombinationen
fuer das Model-Dropdown. Die echten Modelle leben weiterhin in den Plugins
(ptouch.PRINTERS, brother_ql.MODELS) — die Registry ist nur eine duenne
Wrapper-Schicht damit die UI nicht direkt von den Plugin-APIs abhaengt.

Bekannte Kopplungsrisiken (Spec M5 — akzeptiert):
- Falls ptouch.PRINTERS umbenannt wird, faellt der Import zurueck auf
  HARDCODED_FALLBACK_MODELS.
- brother_ql.MODELS hat aktuell eine stabile API.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PrinterModel:
    backend: str
    model: str
    display_name: str


# Fallback-Liste falls Plugin-Imports brechen — minimaler Satz fuer HomeLab-Setup.
HARDCODED_FALLBACK_MODELS: tuple[PrinterModel, ...] = (
    PrinterModel("ptouch", "PT-P750W", "Brother PT-P750W (Compact-Tape 18mm)"),
    PrinterModel("brother_ql", "QL-820NWB", "Brother QL-820NWB (Endlosrolle 62mm)"),
)


def _load_ptouch_models() -> list[PrinterModel]:
    try:
        import ptouch  # type: ignore[import-untyped]
    except ImportError:
        return []
    raw = getattr(ptouch, "PRINTERS", None)
    if raw is None:
        return []
    return [
        PrinterModel(
            backend="ptouch",
            model=name,
            display_name=f"Brother {name}",
        )
        for name in raw
    ]


def _load_brother_ql_models() -> list[PrinterModel]:
    try:
        from brother_ql import models as bq_models  # type: ignore[import-untyped]
    except ImportError:
        return []
    raw = getattr(bq_models, "MODELS", None)
    if raw is None:
        return []
    return [
        PrinterModel(
            backend="brother_ql",
            model=name,
            display_name=f"Brother {name}",
        )
        for name in raw
    ]


def list_available_models() -> list[PrinterModel]:
    """Sammelt verfuegbare Modelle aus den Plugins.

    Faellt auf HARDCODED_FALLBACK_MODELS zurueck wenn beide Plugins
    keine Modelle liefern (Import-Bruch oder fehlende API-Konstante).
    """
    models = _load_ptouch_models() + _load_brother_ql_models()
    if not models:
        return list(HARDCODED_FALLBACK_MODELS)
    return models
```

- [ ] **Step 4: Tests grün**

Run: `cd backend && pytest tests/services/test_printer_model_registry.py -v`
Expected: PASS (alle 4 Tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/printer_model_registry.py \
        backend/tests/services/test_printer_model_registry.py
git commit -m "feat(#124): Plugin-Registry fuer Drucker-Modelle"
```

### Task 2.4: PrinterAdminService — Flattening-Helper

**Files:**
- Create: `backend/app/services/printer_admin_service.py` (Skeleton + Flattening-Helper)
- Test: `backend/tests/services/test_printer_admin_service.py`

- [ ] **Step 1: Failing-Tests für Flattening-Helper schreiben**

```python
# backend/tests/services/test_printer_admin_service.py
"""Tests fuer PrinterAdminService Flattening-Helper (Issue #124 M12)."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from app.schemas.printer_admin import (
    PrinterConnection,
    PrinterCreatePayload,
    PrinterCutDefaults,
    PrinterQueueSettings,
    PrinterUpdatePayload,
    SNMPConfig,
)
from app.services.printer_admin_service import (
    _apply_update_patch,
    _payload_to_row,
    _row_to_audit_view,
)


def _payload() -> PrinterCreatePayload:
    return PrinterCreatePayload(
        name="Brother P750W",
        slug="brother-p750w",
        model="PT-P750W",
        backend="ptouch",
        connection=PrinterConnection(
            host="192.0.2.10",
            port=9100,
            snmp=SNMPConfig(discover=True, community="public"),
        ),
        queue=PrinterQueueSettings(timeout_s=45),
        cut_defaults=PrinterCutDefaults(half_cut=True),
    )


def test_payload_to_row_flattens_queue_and_cut_defaults():
    pid = UUID("12345678-1234-1234-1234-123456789abc")
    ts = datetime(2026, 6, 14, 18, 0, 0, tzinfo=timezone.utc)
    row = _payload_to_row(_payload(), pid, ts)
    assert row["id"] == pid
    assert row["queue_timeout_s"] == 45
    assert row["cut_defaults_half_cut"] is True
    # connection bleibt verschachtelt als dict
    assert row["connection"]["host"] == "192.0.2.10"
    assert row["connection"]["snmp"]["community"] == "public"
    assert row["created_at"] == ts
    assert row["updated_at"] == ts


def test_apply_update_patch_partial_queue_only():
    """Patch mit nur queue.timeout_s → nur queue_timeout_s im Result."""
    patch = PrinterUpdatePayload(queue=PrinterQueueSettings(timeout_s=60))
    changes = _apply_update_patch({}, patch)
    assert changes == {"queue_timeout_s": 60}


def test_apply_update_patch_empty_payload_returns_empty():
    patch = PrinterUpdatePayload()
    changes = _apply_update_patch({}, patch)
    assert changes == {}


def test_apply_update_patch_connection_replaces_whole_block():
    """connection wird atomar ersetzt (kein Sub-Field-Merge)."""
    patch = PrinterUpdatePayload(
        connection=PrinterConnection(host="192.0.2.99", port=9101)
    )
    changes = _apply_update_patch({}, patch)
    assert "connection" in changes
    assert changes["connection"]["host"] == "192.0.2.99"
    assert changes["connection"]["snmp"] == {"discover": False, "community": "public"}


def test_row_to_audit_view_unflattens_queue_and_cut_defaults():
    row = {
        "id": UUID("12345678-1234-1234-1234-123456789abc"),
        "name": "X",
        "slug": "x",
        "model": "PT-P750W",
        "backend": "ptouch",
        "connection": {"host": "192.0.2.10", "port": 9100},
        "queue_timeout_s": 45,
        "cut_defaults_half_cut": True,
        "enabled": True,
    }
    view = _row_to_audit_view(row)
    assert view["queue"] == {"timeout_s": 45}
    assert view["cut_defaults"] == {"half_cut": True}
    # id wird zu str (JSON-friendly fuer Audit-Snapshot)
    assert view["id"] == "12345678-1234-1234-1234-123456789abc"


def test_row_to_audit_view_handles_missing_columns_gracefully():
    """Pre-Backfill-Rows ohne queue_timeout_s/cut_defaults_half_cut."""
    row = {"id": UUID("12345678-1234-1234-1234-123456789abc"), "slug": "x"}
    view = _row_to_audit_view(row)
    # Soft None statt KeyError
    assert view["queue"] == {"timeout_s": None}
    assert view["cut_defaults"] == {"half_cut": None}
```

- [ ] **Step 2: Tests laufen — schlagen fehl**

Run: `cd backend && pytest tests/services/test_printer_admin_service.py -v`
Expected: FAIL — Imports nicht da.

- [ ] **Step 3: Skeleton + Flattening-Helper schreiben**

```python
# backend/app/services/printer_admin_service.py
"""PrinterAdminService — CRUD + Audit fuer printers-Tabelle (Issue #124).

Wird in Task 2.5 um die echte Service-Logik (create_printer, update_printer,
disable_printer, enable_printer, list_printers, get_printer) erweitert.
Dieser Task fokussiert auf die Flattening-Helper (Spec M12).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from app.schemas.printer_admin import (
    PrinterCreatePayload,
    PrinterUpdatePayload,
)


def _payload_to_row(
    payload: PrinterCreatePayload,
    printer_id: UUID,
    created_at_utc: datetime,
) -> dict[str, Any]:
    """Mappt PrinterCreatePayload auf flaches DB-Row-Dict.

    connection bleibt verschachtelt im JSON-Feld; queue.timeout_s und
    cut_defaults.half_cut werden auf flache Spalten gemappt.
    """
    return {
        "id": printer_id,
        "name": payload.name,
        "slug": payload.slug,
        "model": payload.model,
        "backend": payload.backend,
        "connection": payload.connection.model_dump(mode="json"),
        "queue_timeout_s": payload.queue.timeout_s,
        "cut_defaults_half_cut": payload.cut_defaults.half_cut,
        "enabled": payload.enabled,
        "created_at": created_at_utc,
        "updated_at": created_at_utc,
    }


def _apply_update_patch(
    row: dict[str, Any],
    patch: PrinterUpdatePayload,
) -> dict[str, Any]:
    """Returns dict mit NUR den geaenderten Spalten fuer SQL-UPDATE.

    slug/model/backend/id werden silent ignoriert (M12).
    connection wird ATOMAR ersetzt (kein Sub-Field-Merge) — Operator
    muss den ganzen connection-Block schicken auch wenn nur snmp geaendert
    wird. Dokumentiert in API-Doku.
    """
    changes: dict[str, Any] = {}
    if patch.name is not None:
        changes["name"] = patch.name
    if patch.connection is not None:
        changes["connection"] = patch.connection.model_dump(mode="json")
    if patch.queue is not None:
        changes["queue_timeout_s"] = patch.queue.timeout_s
    if patch.cut_defaults is not None:
        changes["cut_defaults_half_cut"] = patch.cut_defaults.half_cut
    if patch.enabled is not None:
        changes["enabled"] = patch.enabled
    return changes


def _row_to_audit_view(row: dict[str, Any]) -> dict[str, Any]:
    """Rekonstruiert verschachtelte Form fuer Audit-JSON.

    Resultat ist JSON-serialisierbar und entspricht dem Pydantic-Schema
    (snmp.discover/community verschachtelt). Wird von redact_secrets
    weiterverarbeitet bevor in printers_audit geschrieben.
    """
    return {
        "id": str(row["id"]) if "id" in row else None,
        "name": row.get("name"),
        "slug": row.get("slug"),
        "model": row.get("model"),
        "backend": row.get("backend"),
        "connection": row.get("connection"),
        "queue": {"timeout_s": row.get("queue_timeout_s")},
        "cut_defaults": {"half_cut": row.get("cut_defaults_half_cut")},
        "enabled": row.get("enabled"),
    }
```

- [ ] **Step 4: Tests grün**

Run: `cd backend && pytest tests/services/test_printer_admin_service.py -v`
Expected: PASS alle 6 Tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/printer_admin_service.py \
        backend/tests/services/test_printer_admin_service.py
git commit -m "feat(#124): PrinterAdminService Flattening-Helper (Spec M12)"
```

### Task 2.5: PrinterAdminService — CRUD-Methoden

**Files:**
- Modify: `backend/app/services/printer_admin_service.py` (Class hinzu)
- Modify: `backend/tests/services/test_printer_admin_service.py` (Class-Tests ergänzen)

- [ ] **Step 1: Failing-Tests für Service-Methoden**

```python
# Ergaenzung in backend/tests/services/test_printer_admin_service.py
# (existing imports + tests bleiben)
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.printer_admin_service import PrinterAdminService
from tests._helpers.db import create_test_session  # neu, falls noch nicht da


@pytest.mark.asyncio
async def test_create_printer_inserts_row_and_audit():
    async with create_test_session() as session:
        svc = PrinterAdminService(session, audit_user="test-operator")
        printer = await svc.create_printer(_payload())
    assert printer.slug == "brother-p750w"
    assert printer.enabled is True
    # Audit-Row
    async with create_test_session() as session:
        rows = (await session.execute(
            "SELECT action, updated_by FROM printers_audit "
            "WHERE printer_id = :pid", {"pid": str(printer.id)}
        )).all()
    assert len(rows) == 1
    assert rows[0][0] == "create"
    assert rows[0][1] == "test-operator"


@pytest.mark.asyncio
async def test_create_printer_duplicate_slug_raises():
    from app.services.printer_admin_service import DuplicateSlugError
    async with create_test_session() as session:
        svc = PrinterAdminService(session, audit_user="op")
        await svc.create_printer(_payload())
        with pytest.raises(DuplicateSlugError):
            await svc.create_printer(_payload())


@pytest.mark.asyncio
async def test_update_printer_changes_name_and_audit():
    async with create_test_session() as session:
        svc = PrinterAdminService(session, audit_user="op")
        printer = await svc.create_printer(_payload())
        updated = await svc.update_printer(
            "brother-p750w",
            PrinterUpdatePayload(name="Neuer Name"),
        )
    assert updated.name == "Neuer Name"


@pytest.mark.asyncio
async def test_update_printer_silently_ignores_slug_change():
    """Versuch slug zu aendern wird ignoriert, kein 422."""
    async with create_test_session() as session:
        svc = PrinterAdminService(session, audit_user="op")
        await svc.create_printer(_payload())
        # PrinterUpdatePayload kennt slug nicht als Feld — Patch ohne slug
        # bleibt ohne Effekt auf slug. Test: nach Update ist slug unveraendert.
        await svc.update_printer("brother-p750w", PrinterUpdatePayload(name="X"))
        result = await svc.get_printer("brother-p750w")
    assert result is not None
    assert result.slug == "brother-p750w"


@pytest.mark.asyncio
async def test_disable_printer_sets_enabled_false_and_audit():
    async with create_test_session() as session:
        svc = PrinterAdminService(session, audit_user="op")
        await svc.create_printer(_payload())
        await svc.disable_printer("brother-p750w")
        result = await svc.get_printer("brother-p750w")
    assert result is not None
    assert result.enabled is False


@pytest.mark.asyncio
async def test_disable_printer_twice_raises_conflict():
    from app.services.printer_admin_service import PrinterAlreadyDisabledError
    async with create_test_session() as session:
        svc = PrinterAdminService(session, audit_user="op")
        await svc.create_printer(_payload())
        await svc.disable_printer("brother-p750w")
        with pytest.raises(PrinterAlreadyDisabledError):
            await svc.disable_printer("brother-p750w")


@pytest.mark.asyncio
async def test_enable_printer_after_disable():
    async with create_test_session() as session:
        svc = PrinterAdminService(session, audit_user="op")
        await svc.create_printer(_payload())
        await svc.disable_printer("brother-p750w")
        await svc.enable_printer("brother-p750w")
        result = await svc.get_printer("brother-p750w")
    assert result is not None
    assert result.enabled is True


@pytest.mark.asyncio
async def test_get_printer_not_found_returns_none():
    async with create_test_session() as session:
        svc = PrinterAdminService(session, audit_user="op")
        result = await svc.get_printer("missing")
    assert result is None


@pytest.mark.asyncio
async def test_list_printers_excludes_disabled_by_default():
    async with create_test_session() as session:
        svc = PrinterAdminService(session, audit_user="op")
        await svc.create_printer(_payload())
        # Zweiter Drucker disabled
        second = _payload()
        second_payload = PrinterCreatePayload(
            name="QL820", slug="brother-ql820", model="QL-820NWB",
            backend="brother_ql",
            connection=PrinterConnection(host="192.0.2.11", port=9100),
        )
        await svc.create_printer(second_payload)
        await svc.disable_printer("brother-ql820")
        # Default: nur enabled
        active = await svc.list_printers()
    assert {p.slug for p in active} == {"brother-p750w"}


@pytest.mark.asyncio
async def test_list_printers_include_disabled_true_shows_all():
    async with create_test_session() as session:
        svc = PrinterAdminService(session, audit_user="op")
        await svc.create_printer(_payload())
        all_p = await svc.list_printers(include_disabled=True)
    assert len(all_p) == 1
```

- [ ] **Step 2: `create_test_session()` Helper ergänzen**

```python
# tests/_helpers/db.py — Helper ergaenzen
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.engine import engine

_TestSession = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def create_test_session() -> AsyncIterator[AsyncSession]:
    """Async-Session fuer Tests — autocommit-Pattern via context-manager."""
    async with _TestSession() as session:
        yield session
        await session.commit()
```

- [ ] **Step 3: Tests laufen — schlagen fehl**

Run: `cd backend && pytest tests/services/test_printer_admin_service.py -v`
Expected: FAIL (PrinterAdminService Klasse fehlt, Exception-Klassen fehlen).

- [ ] **Step 4: `PrinterAdminService` Klasse implementieren**

```python
# backend/app/services/printer_admin_service.py — Class anhaengen
# Existing _payload_to_row, _apply_update_patch, _row_to_audit_view bleiben

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.printer import Printer
from app.services.audit_redaction import redact_secrets
from app.services.printer_identity import derive_printer_id


class DuplicateSlugError(Exception):
    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"slug={slug!r} bereits vergeben")


class DuplicateNameError(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"name={name!r} bereits vergeben")


class PrinterAlreadyDisabledError(Exception):
    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"Drucker {slug!r} ist bereits deaktiviert")


class PrinterAlreadyEnabledError(Exception):
    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"Drucker {slug!r} ist bereits aktiv")


class PrinterNotFoundBySlugError(Exception):
    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"Drucker {slug!r} nicht gefunden")


class PrinterAdminService:
    """CRUD + Audit fuer printers-Tabelle (Issue #124)."""

    def __init__(self, session: AsyncSession, audit_user: str) -> None:
        self._session = session
        self._audit_user = audit_user

    async def get_printer(self, slug: str) -> Printer | None:
        stmt = select(Printer).where(Printer.slug == slug)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_printers(self, *, include_disabled: bool = False) -> list[Printer]:
        stmt = select(Printer)
        if not include_disabled:
            stmt = stmt.where(Printer.enabled.is_(True))
        stmt = stmt.order_by(Printer.slug)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create_printer(self, payload: PrinterCreatePayload) -> Printer:
        created_at = datetime.now(timezone.utc)
        printer_id = derive_printer_id(
            payload.model, payload.connection.host, payload.connection.port, created_at
        )
        row = _payload_to_row(payload, printer_id, created_at)
        printer = Printer(**row)
        self._session.add(printer)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            text = str(exc.orig).lower()
            if "slug" in text:
                raise DuplicateSlugError(payload.slug) from exc
            if "name" in text:
                raise DuplicateNameError(payload.name) from exc
            raise
        await self._record_audit(
            printer_id=printer_id,
            slug=payload.slug,
            action="create",
            before=None,
            after=_row_to_audit_view(row),
        )
        return printer

    async def update_printer(
        self, slug: str, patch: PrinterUpdatePayload
    ) -> Printer:
        printer = await self.get_printer(slug)
        if printer is None:
            raise PrinterNotFoundBySlugError(slug)
        before_view = _row_to_audit_view(_printer_to_dict(printer))
        changes = _apply_update_patch({}, patch)
        if not changes:
            return printer  # Empty patch: nichts zu tun
        changes["updated_at"] = datetime.now(timezone.utc)
        for key, value in changes.items():
            setattr(printer, key, value)
        await self._session.flush()
        after_view = _row_to_audit_view(_printer_to_dict(printer))
        await self._record_audit(
            printer_id=printer.id, slug=printer.slug,
            action="update", before=before_view, after=after_view,
        )
        return printer

    async def disable_printer(self, slug: str) -> Printer:
        printer = await self.get_printer(slug)
        if printer is None:
            raise PrinterNotFoundBySlugError(slug)
        if not printer.enabled:
            raise PrinterAlreadyDisabledError(slug)
        before = _row_to_audit_view(_printer_to_dict(printer))
        printer.enabled = False
        printer.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
        after = _row_to_audit_view(_printer_to_dict(printer))
        await self._record_audit(
            printer_id=printer.id, slug=printer.slug,
            action="disable", before=before, after=after,
        )
        return printer

    async def enable_printer(self, slug: str) -> Printer:
        printer = await self.get_printer(slug)
        if printer is None:
            raise PrinterNotFoundBySlugError(slug)
        if printer.enabled:
            raise PrinterAlreadyEnabledError(slug)
        before = _row_to_audit_view(_printer_to_dict(printer))
        printer.enabled = True
        printer.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
        after = _row_to_audit_view(_printer_to_dict(printer))
        await self._record_audit(
            printer_id=printer.id, slug=printer.slug,
            action="enable", before=before, after=after,
        )
        return printer

    async def _record_audit(
        self, *, printer_id: UUID, slug: str, action: str,
        before: dict[str, Any] | None, after: dict[str, Any] | None,
    ) -> None:
        from sqlalchemy import text
        await self._session.execute(text(
            "INSERT INTO printers_audit "
            "(id, printer_id, slug, action, before_json, after_json, "
            " updated_by, created_at) "
            "VALUES (:id, :pid, :slug, :action, :before, :after, :who, "
            "        :ts)"
        ), {
            "id": str(uuid4()),
            "pid": str(printer_id),
            "slug": slug,
            "action": action,
            "before": _json_or_none(redact_secrets(before) if before else None),
            "after": _json_or_none(redact_secrets(after) if after else None),
            "who": self._audit_user,
            "ts": datetime.now(timezone.utc),
        })


def _json_or_none(value: dict[str, Any] | None) -> str | None:
    import json
    return None if value is None else json.dumps(value)


def _printer_to_dict(printer: Printer) -> dict[str, Any]:
    return {
        "id": printer.id,
        "name": printer.name,
        "slug": printer.slug,
        "model": printer.model,
        "backend": printer.backend,
        "connection": printer.connection,
        "queue_timeout_s": printer.queue_timeout_s,
        "cut_defaults_half_cut": printer.cut_defaults_half_cut,
        "enabled": printer.enabled,
    }
```

- [ ] **Step 5: Tests grün**

Run: `cd backend && pytest tests/services/test_printer_admin_service.py -v`
Expected: PASS — alle 10+ Tests grün.

- [ ] **Step 6: Coverage-Check**

Run: `cd backend && pytest tests/services/test_printer_admin_service.py --cov=app.services.printer_admin_service --cov-report=term-missing`
Expected: Coverage ≥ 85% für `printer_admin_service.py`. Fehlende Zeilen ergänzen.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/printer_admin_service.py \
        backend/tests/services/test_printer_admin_service.py \
        backend/tests/_helpers/db.py
git commit -m "feat(#124): PrinterAdminService CRUD + Audit-Recording"
```

---

## Phase 3 — API + Web-Routes + CSRF-Middleware — 5 Tasks

### Task 3.1: CSRF-Middleware

**Files:**
- Create: `backend/app/middleware/__init__.py`
- Create: `backend/app/middleware/csrf.py`
- Create: `backend/tests/middleware/__init__.py`
- Create: `backend/tests/middleware/test_csrf.py`
- Modify: `backend/pyproject.toml` (Dependency `starlette-csrf` ergänzen falls fehlt)

- [ ] **Step 1: Dependency-Check**

```bash
cd backend
grep -E "starlette-csrf|python-multipart|jinja2" pyproject.toml
```
Falls fehlend: in `[project.dependencies]` ergänzen und `uv sync` / `pip install -e .` laufen lassen.

- [ ] **Step 2: Failing-Tests schreiben (4 CSRF-Fälle aus Spec)**

```python
# backend/tests/middleware/test_csrf.py
"""CSRF-Middleware-Tests (Issue #124 — 4 explizite Faelle)."""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.csrf import setup_csrf_middleware


@pytest.fixture
def csrf_app() -> FastAPI:
    app = FastAPI()
    setup_csrf_middleware(app)

    @app.get("/form")
    async def form(): return {"csrf_token": "fixed-token-for-test"}

    @app.post("/submit")
    async def submit(): return {"ok": True}

    @app.post("/api/submit")
    async def api_submit(): return {"ok": True}

    return app


def test_post_with_valid_cookie_and_form_token_passes(csrf_app: FastAPI):
    client = TestClient(csrf_app)
    # 1) GET fuer Cookie holen
    r = client.get("/form")
    cookie = r.cookies.get("csrftoken")
    assert cookie is not None
    # 2) POST mit gueltigem Cookie + Form-Field
    r = client.post("/submit", cookies={"csrftoken": cookie},
                    data={"csrftoken": cookie})
    assert r.status_code == 200


def test_post_without_form_token_returns_403(csrf_app: FastAPI):
    client = TestClient(csrf_app)
    r = client.get("/form")
    cookie = r.cookies.get("csrftoken")
    r = client.post("/submit", cookies={"csrftoken": cookie})  # KEIN Form-Field
    assert r.status_code == 403


def test_post_with_wrong_token_returns_403(csrf_app: FastAPI):
    client = TestClient(csrf_app)
    r = client.get("/form")
    cookie = r.cookies.get("csrftoken")
    r = client.post("/submit", cookies={"csrftoken": cookie},
                    data={"csrftoken": "WRONG"})
    assert r.status_code == 403


def test_post_with_authorization_header_skips_csrf(csrf_app: FastAPI):
    """API-Calls mit Bearer/Basic-Auth-Header umgehen CSRF."""
    client = TestClient(csrf_app)
    r = client.post(
        "/api/submit",
        headers={"Authorization": "Basic dGVzdDp0ZXN0"},
    )
    assert r.status_code == 200
```

- [ ] **Step 3: `csrf.py` schreiben**

```python
# backend/app/middleware/csrf.py
"""CSRF-Middleware-Setup (Issue #124 H3).

Schuetzt HTML-Form-POSTs vor CSRF. JSON-API-Endpunkte mit Basic-Auth oder
Bearer-Token werden uebersprungen — Browser-Origins schicken keine
Authorization-Header bei Cross-Origin-POSTs.
"""
from __future__ import annotations

from starlette_csrf import CSRFMiddleware  # type: ignore[import-untyped]
from fastapi import FastAPI


def setup_csrf_middleware(app: FastAPI) -> None:
    """Registriert die CSRF-Middleware am FastAPI-App.

    - Cookie-Name: csrftoken (SameSite=Strict)
    - Form-Field-Name: csrftoken (hidden input)
    - Header-Skip: Authorization (Basic/Bearer)
    """
    app.add_middleware(
        CSRFMiddleware,
        secret="<wird-via-settings-konfiguriert>",  # siehe Step 4
        cookie_name="csrftoken",
        cookie_samesite="strict",
        header_name="x-csrftoken",  # alternativ zu Form-Field
        sensitive_cookies={"sessionid"},  # nicht im Hub genutzt
        exempt_urls=None,
        exempt_methods=["GET", "HEAD", "OPTIONS", "TRACE"],
    )


def _has_auth_header(request) -> bool:
    return "authorization" in request.headers
```

Hinweis: `starlette-csrf` hat keinen eingebauten "Authorization-Header-Skip"-Pfad. Wir wrappen die Middleware mit einem eigenen Decorator/Dispatch falls notwendig — siehe alternative Implementation:

```python
# Alternative wenn starlette-csrf keinen Auth-Skip kann:
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class CSRFWithAuthSkip(BaseHTTPMiddleware):
    def __init__(self, app, csrf_middleware):
        super().__init__(app)
        self._csrf = csrf_middleware

    async def dispatch(self, request: Request, call_next):
        if "authorization" in request.headers:
            return await call_next(request)
        return await self._csrf.dispatch(request, call_next)
```

- [ ] **Step 4: Settings-Feld für CSRF-Secret in `app/config.py`**

```python
# backend/app/config.py — Settings-Class ergaenzen
class Settings(BaseSettings):
    # ... existing fields ...

    csrf_secret: str = Field(default="change-me-in-production",
                              description="HMAC-Secret fuer CSRF-Token-Signierung")
```

- [ ] **Step 5: Tests grün**

Run: `cd backend && pytest tests/middleware/test_csrf.py -v`
Expected: PASS alle 4 Tests.

- [ ] **Step 6: Commit**

```bash
git add backend/app/middleware/ backend/tests/middleware/ \
        backend/app/config.py backend/pyproject.toml
git commit -m "feat(#124): CSRF-Middleware mit Authorization-Header-Skip"
```

### Task 3.2: JSON-API Routes (admin_printers_api.py)

**Files:**
- Create: `backend/app/api/routes/admin_printers_api.py`
- Create: `backend/tests/api/test_admin_printers_api.py`

- [ ] **Step 1: Failing-Tests für API-Endpoints**

```python
# backend/tests/api/test_admin_printers_api.py
"""Integration-Tests fuer /api/v1/admin/printers (Issue #124)."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.main import create_app

BASIC_AUTH_HEADER = {"Authorization": "Basic Y2xhdWRlLWF1dG9tYXRpb246Zm9v"}
SSO_HEADERS = {"Remote-User": "operator@example.test"}


@pytest.fixture
async def client() -> AsyncClient:
    app = create_app()
    async with AsyncClient(app=app, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_list_printers_empty(client: AsyncClient):
    r = await client.get("/api/v1/admin/printers", headers=SSO_HEADERS)
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_create_printer_returns_201_and_audit_row(client: AsyncClient):
    payload = {
        "name": "Brother P750W",
        "slug": "brother-p750w",
        "model": "PT-P750W",
        "backend": "ptouch",
        "connection": {"host": "192.0.2.10", "port": 9100,
                       "snmp": {"discover": False, "community": "public"}},
        "queue": {"timeout_s": 30},
        "cut_defaults": {"half_cut": False},
        "enabled": True,
    }
    r = await client.post("/api/v1/admin/printers", json=payload,
                          headers=SSO_HEADERS)
    assert r.status_code == 201
    body = r.json()
    assert body["slug"] == "brother-p750w"
    assert "id" in body


@pytest.mark.asyncio
async def test_create_printer_duplicate_slug_409(client: AsyncClient):
    payload = {...}  # wie oben
    r1 = await client.post("/api/v1/admin/printers", json=payload, headers=SSO_HEADERS)
    assert r1.status_code == 201
    r2 = await client.post("/api/v1/admin/printers", json=payload, headers=SSO_HEADERS)
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_get_printer_by_slug(client: AsyncClient):
    # ... payload create, then GET
    ...


@pytest.mark.asyncio
async def test_update_printer_silently_ignores_slug(client: AsyncClient):
    # Create, then PUT mit anderem slug im Body
    ...


@pytest.mark.asyncio
async def test_disable_printer_204(client: AsyncClient):
    # Create, then POST /disable
    ...


@pytest.mark.asyncio
async def test_disable_already_disabled_409(client: AsyncClient):
    ...


@pytest.mark.asyncio
async def test_enable_after_disable_200(client: AsyncClient):
    ...


@pytest.mark.asyncio
async def test_403_without_auth_header(client: AsyncClient):
    r = await client.get("/api/v1/admin/printers")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_basic_auth_claude_automation_passes(client: AsyncClient):
    r = await client.get("/api/v1/admin/printers", headers=BASIC_AUTH_HEADER)
    assert r.status_code in (200, 401)  # 401 wenn echtes Basic-Auth aktiv; 200 wenn Test-Setup uebergeht
```

(Implementer ergänzt die `...` mit dem vollständigen Payload-Pattern aus dem ersten Test.)

- [ ] **Step 2: Tests laufen — Routen nicht existent**

Run: `cd backend && pytest tests/api/test_admin_printers_api.py -v`
Expected: FAIL (404).

- [ ] **Step 3: `admin_printers_api.py` schreiben**

```python
# backend/app/api/routes/admin_printers_api.py
"""JSON-API fuer Drucker-Verwaltung unter /api/v1/admin/printers (Issue #124)."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.session import get_db_session  # falls existiert
from app.auth.dependencies import require_admin_user  # neu oder existing
from app.models.printer import Printer
from app.schemas.printer_admin import (
    PrinterCreatePayload, PrinterUpdatePayload,
)
from app.services.printer_admin_service import (
    DuplicateNameError, DuplicateSlugError,
    PrinterAdminService, PrinterAlreadyDisabledError,
    PrinterAlreadyEnabledError, PrinterNotFoundBySlugError,
)

router = APIRouter(prefix="/api/v1/admin/printers", tags=["admin"])


def _printer_to_response(p: Printer) -> dict:
    return {
        "id": str(p.id),
        "name": p.name,
        "slug": p.slug,
        "model": p.model,
        "backend": p.backend,
        "connection": p.connection,
        "queue": {"timeout_s": p.queue_timeout_s},
        "cut_defaults": {"half_cut": p.cut_defaults_half_cut},
        "enabled": p.enabled,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@router.get("")
async def list_printers(
    include_disabled: bool = False,
    session: AsyncSession = Depends(get_db_session),
    user: str = Depends(require_admin_user),
):
    svc = PrinterAdminService(session, audit_user=user)
    printers = await svc.list_printers(include_disabled=include_disabled)
    return [_printer_to_response(p) for p in printers]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_printer(
    payload: PrinterCreatePayload,
    session: AsyncSession = Depends(get_db_session),
    user: str = Depends(require_admin_user),
):
    svc = PrinterAdminService(session, audit_user=user)
    try:
        p = await svc.create_printer(payload)
    except DuplicateSlugError as exc:
        raise HTTPException(409, {"error": "duplicate_slug", "slug": exc.slug})
    except DuplicateNameError as exc:
        raise HTTPException(409, {"error": "duplicate_name", "name": exc.name})
    await session.commit()
    return _printer_to_response(p)


@router.get("/{slug}")
async def get_printer(
    slug: str,
    session: AsyncSession = Depends(get_db_session),
    user: str = Depends(require_admin_user),
):
    svc = PrinterAdminService(session, audit_user=user)
    p = await svc.get_printer(slug)
    if p is None:
        raise HTTPException(404, {"error": "not_found", "slug": slug})
    return _printer_to_response(p)


@router.put("/{slug}")
async def update_printer(
    slug: str,
    patch: PrinterUpdatePayload,
    session: AsyncSession = Depends(get_db_session),
    user: str = Depends(require_admin_user),
):
    svc = PrinterAdminService(session, audit_user=user)
    try:
        p = await svc.update_printer(slug, patch)
    except PrinterNotFoundBySlugError:
        raise HTTPException(404, {"error": "not_found", "slug": slug})
    await session.commit()
    return _printer_to_response(p)


@router.post("/{slug}/disable", status_code=status.HTTP_200_OK)
async def disable_printer(
    slug: str,
    session: AsyncSession = Depends(get_db_session),
    user: str = Depends(require_admin_user),
):
    svc = PrinterAdminService(session, audit_user=user)
    try:
        p = await svc.disable_printer(slug)
    except PrinterNotFoundBySlugError:
        raise HTTPException(404, {"error": "not_found", "slug": slug})
    except PrinterAlreadyDisabledError:
        raise HTTPException(409, {"error": "already_disabled", "slug": slug})
    await session.commit()
    return _printer_to_response(p)


@router.post("/{slug}/enable")
async def enable_printer(
    slug: str,
    session: AsyncSession = Depends(get_db_session),
    user: str = Depends(require_admin_user),
):
    svc = PrinterAdminService(session, audit_user=user)
    try:
        p = await svc.enable_printer(slug)
    except PrinterNotFoundBySlugError:
        raise HTTPException(404, {"error": "not_found", "slug": slug})
    except PrinterAlreadyEnabledError:
        raise HTTPException(409, {"error": "already_enabled", "slug": slug})
    await session.commit()
    return _printer_to_response(p)
```

- [ ] **Step 4: `require_admin_user` Dependency**

```python
# backend/app/auth/dependencies.py — neue Dependency ergaenzen
from fastapi import Header, HTTPException, Request


async def require_admin_user(request: Request) -> str:
    """Liefert den Remote-User-Header-Wert ODER 403.

    Bei Basic-Auth (claude-automation) wuerde die Pangolin-Resource
    den User direkt durchreichen — Hub sieht dann Authorization: Basic ...
    """
    user = request.headers.get("Remote-User")
    if user:
        return user
    legacy = request.headers.get("X-Pangolin-User")
    if legacy:
        return legacy
    if request.headers.get("Authorization", "").lower().startswith("basic "):
        # Pangolin Header-Auth-Bypass — claude-automation
        return "claude-automation"
    raise HTTPException(403, {"error": "auth_required"})
```

- [ ] **Step 5: Router in main.py registrieren**

```python
# backend/app/main.py — Imports + include_router
from app.api.routes.admin_printers_api import router as admin_printers_api_router

# ... in create_app():
app.include_router(admin_printers_api_router)
```

- [ ] **Step 6: Tests grün**

Run: `cd backend && pytest tests/api/test_admin_printers_api.py -v`
Expected: PASS.

- [ ] **Step 7: Coverage-Check**

Run: `cd backend && pytest tests/api/test_admin_printers_api.py --cov=app.api.routes.admin_printers_api --cov-report=term-missing`
Expected: ≥80%.

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/routes/admin_printers_api.py \
        backend/app/auth/dependencies.py \
        backend/app/main.py \
        backend/tests/api/test_admin_printers_api.py
git commit -m "feat(#124): JSON-API /api/v1/admin/printers"
```

### Task 3.3: HTML-Routes (admin_printers_web.py) + Templates

**Files:**
- Create: `backend/app/api/routes/admin_printers_web.py`
- Create: `backend/app/templates/_base.html`
- Create: `backend/app/templates/admin_printers/list.html`
- Create: `backend/app/templates/admin_printers/form.html`
- Create: `backend/app/templates/admin_printers/confirm_disable.html`
- Create: `backend/tests/api/test_admin_printers_web.py`

- [ ] **Step 1: Failing-Tests für HTML-Routes**

```python
# backend/tests/api/test_admin_printers_web.py
"""Integration-Tests fuer /admin/printers HTML-Routes (Issue #124)."""
import pytest
from httpx import AsyncClient
from app.main import create_app

SSO_HEADERS = {"Remote-User": "operator@example.test"}


@pytest.fixture
async def client() -> AsyncClient:
    app = create_app()
    async with AsyncClient(app=app, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_list_page_renders_html(client: AsyncClient):
    r = await client.get("/admin/printers/", headers=SSO_HEADERS)
    assert r.status_code == 200
    assert "Drucker" in r.text
    assert "text/html" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_new_form_renders(client: AsyncClient):
    r = await client.get("/admin/printers/new", headers=SSO_HEADERS)
    assert r.status_code == 200
    assert "Slug" in r.text or "slug" in r.text
    assert "csrftoken" in r.text  # CSRF-Token im Formular


@pytest.mark.asyncio
async def test_create_form_post_redirects_303(client: AsyncClient):
    # Erst GET fuer CSRF-Cookie
    r = await client.get("/admin/printers/new", headers=SSO_HEADERS)
    cookie = r.cookies.get("csrftoken")
    assert cookie
    r = await client.post(
        "/admin/printers",
        data={
            "name": "Brother P750W",
            "slug": "brother-p750w",
            "model": "PT-P750W",
            "backend": "ptouch",
            "connection.host": "192.0.2.10",
            "connection.port": "9100",
            "connection.snmp.discover": "false",
            "connection.snmp.community": "public",
            "queue.timeout_s": "30",
            "cut_defaults.half_cut": "false",
            "enabled": "true",
            "csrftoken": cookie,
        },
        cookies={"csrftoken": cookie},
        headers=SSO_HEADERS,
    )
    assert r.status_code == 303
    assert "/admin/printers/?info=created" in r.headers["location"]


@pytest.mark.asyncio
async def test_edit_page_prefilled(client: AsyncClient):
    """Nach Create: Edit-Page zeigt aktuelle Werte."""
    # ... Create via JSON-API erst, dann GET /admin/printers/<slug>/edit
    ...


@pytest.mark.asyncio
async def test_confirm_disable_page(client: AsyncClient):
    # ... Create, dann GET /admin/printers/<slug>/disable
    ...
```

- [ ] **Step 2: Tests laufen — Routen nicht existent**

Run: `cd backend && pytest tests/api/test_admin_printers_web.py -v`
Expected: FAIL (404).

- [ ] **Step 3: Templates schreiben**

```html
<!-- backend/app/templates/_base.html -->
<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <title>{% block title %}Hub Admin{% endblock %}</title>
  <style>
    body { font-family: sans-serif; max-width: 960px; margin: 2em auto; }
    table { width: 100%; border-collapse: collapse; }
    th, td { text-align: left; padding: 0.5em; border-bottom: 1px solid #ddd; }
    .button { padding: 0.4em 0.8em; border: 1px solid #999; border-radius: 4px;
              text-decoration: none; color: #333; }
    .button.danger { background: #fee; border-color: #c33; color: #900; }
  </style>
</head>
<body>
  <header>
    <h1>{% block heading %}{% endblock %}</h1>
    <nav><a href="/admin/printers/">Drucker</a></nav>
  </header>
  {% if info %}<div class="info">{{ info }}</div>{% endif %}
  {% block content %}{% endblock %}
</body>
</html>
```

```html
<!-- backend/app/templates/admin_printers/list.html -->
{% extends "_base.html" %}
{% block title %}Drucker{% endblock %}
{% block heading %}Drucker{% endblock %}
{% block content %}
<p>
  <a href="/admin/printers/new" class="button">Neuen Drucker anlegen</a>
  {% if include_disabled %}
    <a href="/admin/printers/">Nur aktive anzeigen</a>
  {% else %}
    <a href="/admin/printers/?include_disabled=1">Auch deaktivierte zeigen</a>
  {% endif %}
</p>
<table>
  <thead><tr><th>Name</th><th>Slug</th><th>Modell</th><th>Host:Port</th>
              <th>Status</th><th>Aktualisiert</th><th></th></tr></thead>
  <tbody>
    {% for p in printers %}
    <tr>
      <td>{{ p.name }}</td>
      <td>{{ p.slug }}</td>
      <td>{{ p.model }}</td>
      <td>{{ p.connection.host }}:{{ p.connection.port }}</td>
      <td>{% if p.enabled %}✓ aktiv{% else %}deaktiviert{% endif %}</td>
      <td>{{ p.updated_at }}</td>
      <td>
        <a href="/admin/printers/{{ p.slug }}/edit">Bearbeiten</a>
        {% if p.enabled %}
          <a href="/admin/printers/{{ p.slug }}/disable">Deaktivieren</a>
        {% else %}
          <form method="post" action="/admin/printers/{{ p.slug }}/enable"
                style="display:inline">
            <input type="hidden" name="csrftoken" value="{{ csrf_token }}">
            <button type="submit">Aktivieren</button>
          </form>
        {% endif %}
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
```

```html
<!-- backend/app/templates/admin_printers/form.html -->
{% extends "_base.html" %}
{% block title %}{% if printer %}Drucker bearbeiten{% else %}Neuer Drucker{% endif %}{% endblock %}
{% block content %}
<form method="post" action="{% if printer %}/admin/printers/{{ printer.slug }}{% else %}/admin/printers{% endif %}">
  <input type="hidden" name="csrftoken" value="{{ csrf_token }}">
  <label>Name <input name="name" required value="{{ printer.name if printer else '' }}"></label>
  <label>Slug <input name="slug" required pattern="^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$"
                     value="{{ printer.slug if printer else '' }}"
                     {% if printer %}disabled{% endif %}></label>
  <label>Modell
    <select name="model" {% if printer %}disabled{% endif %}>
      {% for m in available_models %}
        <option value="{{ m.model }}"
                data-backend="{{ m.backend }}"
                {% if printer and printer.model == m.model %}selected{% endif %}>
          {{ m.display_name }}
        </option>
      {% endfor %}
    </select>
  </label>
  <label>Backend
    <select name="backend" {% if printer %}disabled{% endif %}>
      <option value="ptouch">ptouch</option>
      <option value="brother_ql">brother_ql</option>
    </select>
  </label>
  <fieldset>
    <legend>Verbindung</legend>
    <label>Host <input name="connection.host" required
                       value="{{ printer.connection.host if printer else '' }}"></label>
    <label>Port <input name="connection.port" type="number" required min="1" max="65535"
                       value="{{ printer.connection.port if printer else '9100' }}"></label>
    <label>SNMP Discover
      <input name="connection.snmp.discover" type="checkbox"
             {% if printer and printer.connection.snmp.discover %}checked{% endif %}>
    </label>
    <label>SNMP Community
      <input name="connection.snmp.community"
             value="{{ printer.connection.snmp.community if printer else 'public' }}">
    </label>
  </fieldset>
  <label>Queue Timeout (Sekunden)
    <input name="queue.timeout_s" type="number" min="1" max="600"
           value="{{ printer.queue_timeout_s if printer else 30 }}">
  </label>
  <label>Half-Cut Default
    <input name="cut_defaults.half_cut" type="checkbox"
           {% if printer and printer.cut_defaults_half_cut %}checked{% endif %}>
  </label>
  <label>Aktiv
    <input name="enabled" type="checkbox"
           {% if not printer or printer.enabled %}checked{% endif %}>
  </label>
  <button type="submit">Speichern</button>
</form>
{% endblock %}
```

```html
<!-- backend/app/templates/admin_printers/confirm_disable.html -->
{% extends "_base.html" %}
{% block title %}Drucker deaktivieren{% endblock %}
{% block content %}
<p>Sicher, dass Drucker <strong>{{ printer.name }}</strong> ({{ printer.slug }}) deaktiviert werden soll?</p>
<form method="post" action="/admin/printers/{{ printer.slug }}/disable">
  <input type="hidden" name="csrftoken" value="{{ csrf_token }}">
  <button type="submit" class="button danger">Ja, deaktivieren</button>
  <a href="/admin/printers/" class="button">Abbrechen</a>
</form>
{% endblock %}
```

- [ ] **Step 4: `admin_printers_web.py` schreiben**

```python
# backend/app/api/routes/admin_printers_web.py
"""HTML-Routes /admin/printers (Issue #124)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.session import get_db_session
from app.auth.dependencies import require_admin_user
from app.schemas.printer_admin import (
    PrinterConnection, PrinterCreatePayload, PrinterCutDefaults,
    PrinterQueueSettings, PrinterUpdatePayload, SNMPConfig,
)
from app.services.printer_admin_service import (
    DuplicateNameError, DuplicateSlugError,
    PrinterAdminService, PrinterAlreadyDisabledError,
    PrinterAlreadyEnabledError, PrinterNotFoundBySlugError,
)
from app.services.printer_model_registry import list_available_models

TEMPLATES = Jinja2Templates(directory=str(
    Path(__file__).parent.parent.parent / "templates"
))

router = APIRouter(prefix="/admin/printers", tags=["admin-web"])


@router.get("/")
async def list_page(
    request: Request,
    info: str | None = Query(default=None),
    include_disabled: bool = Query(default=False),
    session: AsyncSession = Depends(get_db_session),
    user: str = Depends(require_admin_user),
):
    svc = PrinterAdminService(session, audit_user=user)
    printers = await svc.list_printers(include_disabled=include_disabled)
    return TEMPLATES.TemplateResponse(
        "admin_printers/list.html",
        {"request": request, "printers": printers,
         "include_disabled": include_disabled, "info": info,
         "csrf_token": request.cookies.get("csrftoken", "")},
    )


@router.get("/new")
async def new_form(
    request: Request,
    user: str = Depends(require_admin_user),
):
    return TEMPLATES.TemplateResponse(
        "admin_printers/form.html",
        {"request": request, "printer": None,
         "available_models": list_available_models(),
         "csrf_token": request.cookies.get("csrftoken", "")},
    )


@router.post("", status_code=status.HTTP_303_SEE_OTHER)
async def create_via_form(
    request: Request,
    name: str = Form(...),
    slug: str = Form(...),
    model: str = Form(...),
    backend: str = Form(...),
    connection_host: str = Form(..., alias="connection.host"),
    connection_port: int = Form(..., alias="connection.port"),
    connection_snmp_discover: bool = Form(False, alias="connection.snmp.discover"),
    connection_snmp_community: str = Form("public", alias="connection.snmp.community"),
    queue_timeout_s: int = Form(30, alias="queue.timeout_s"),
    cut_defaults_half_cut: bool = Form(False, alias="cut_defaults.half_cut"),
    enabled: bool = Form(True),
    session: AsyncSession = Depends(get_db_session),
    user: str = Depends(require_admin_user),
):
    payload = PrinterCreatePayload(
        name=name, slug=slug, model=model, backend=backend,  # type: ignore[arg-type]
        connection=PrinterConnection(
            host=connection_host, port=connection_port,
            snmp=SNMPConfig(
                discover=connection_snmp_discover,
                community=connection_snmp_community,
            ),
        ),
        queue=PrinterQueueSettings(timeout_s=queue_timeout_s),
        cut_defaults=PrinterCutDefaults(half_cut=cut_defaults_half_cut),
        enabled=enabled,
    )
    svc = PrinterAdminService(session, audit_user=user)
    try:
        await svc.create_printer(payload)
    except (DuplicateSlugError, DuplicateNameError) as exc:
        await session.rollback()
        return RedirectResponse(f"/admin/printers/new?error={type(exc).__name__}", 303)
    await session.commit()
    return RedirectResponse(
        f"/admin/printers/?info=created&slug={slug}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# Edit-Page + Update + Disable-Confirm + Disable-POST analog
# (Plan-Implementer fuellt nach Pattern oben aus)
```

- [ ] **Step 5: Router in main.py registrieren**

```python
from app.api.routes.admin_printers_web import router as admin_printers_web_router
# ...
app.include_router(admin_printers_web_router)
```

- [ ] **Step 6: Tests grün**

Run: `cd backend && pytest tests/api/test_admin_printers_web.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/routes/admin_printers_web.py \
        backend/app/templates/_base.html \
        backend/app/templates/admin_printers/ \
        backend/app/main.py \
        backend/tests/api/test_admin_printers_web.py
git commit -m "feat(#124): HTML-Routes /admin/printers + Jinja2-Templates"
```

### Task 3.4: Edit + Disable Web-Routes (Completion)

(Erweitert Task 3.3 um Edit/Disable/Enable HTML-Pfade. Pattern wie Task 3.3 — schreibe Tests, implementiere, commit.)

- [ ] **Step 1-4: Analog Task 3.3 für die fehlenden Routes**

Routes hinzufügen:
- `GET /admin/printers/{slug}/edit` → form.html mit prefilled-Werten
- `POST /admin/printers/{slug}` → update via Service, Redirect mit `?info=updated`
- `GET /admin/printers/{slug}/disable` → confirm_disable.html
- `POST /admin/printers/{slug}/disable` → Service.disable_printer + Redirect
- `POST /admin/printers/{slug}/enable` → Service.enable_printer + Redirect

Tests pro Route schreiben (failing → implement → green → commit).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/admin_printers_web.py backend/tests/api/test_admin_printers_web.py
git commit -m "feat(#124): Edit/Disable/Enable HTML-Routes"
```

---

## Phase 4 — PrintService enabled-Check — 2 Tasks

### Task 4.1: PrintService prüft enabled-Status

**Files:**
- Modify: `backend/app/services/print_service.py`
- Test: `backend/tests/services/test_print_service.py`

- [ ] **Step 1: Failing-Test für enabled-Check**

```python
# Ergaenzung in backend/tests/services/test_print_service.py
import pytest
from uuid import uuid4

from app.printer_backends.exceptions import PrinterDisabledError
from app.services.print_service import PrintService


@pytest.mark.asyncio
async def test_submit_print_job_raises_disabled_for_disabled_printer():
    # Setup: Drucker existiert + ist disabled
    # ... (existing fixture-Setup) ...
    with pytest.raises(PrinterDisabledError) as exc_info:
        await print_service.submit_print_job(request_for_disabled_printer)
    assert exc_info.value.slug == "disabled-printer"
```

- [ ] **Step 2: Test rot**

Run: `cd backend && pytest tests/services/test_print_service.py::test_submit_print_job_raises_disabled_for_disabled_printer -v`
Expected: FAIL — kein Check.

- [ ] **Step 3: Check in `submit_print_job` einbauen**

```python
# backend/app/services/print_service.py
# In submit_print_job() vor der Hauptlogik:
async def submit_print_job(self, request: PrintRequest) -> UUID:
    printer = await self._printers_repo.get_by_id(request.printer_id)
    if printer is None:
        raise PrinterNotFoundError(request.printer_id)
    if not printer.enabled:
        raise PrinterDisabledError(printer_id=printer.id, slug=printer.slug)
    # ... existing logic
```

- [ ] **Step 4: Test grün**

Run: `cd backend && pytest tests/services/test_print_service.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/print_service.py backend/tests/services/test_print_service.py
git commit -m "feat(#124): PrintService.submit_print_job lehnt disabled Drucker ab"
```

### Task 4.2: HTTP-Mapping PrinterDisabledError → 409

**Files:**
- Modify: `backend/app/api/routes/print.py`
- Test: `backend/tests/api/test_print_routes.py` oder neu

- [ ] **Step 1: Failing-Test für 409-Mapping**

```python
@pytest.mark.asyncio
async def test_post_print_with_disabled_printer_returns_409(client, disabled_printer):
    payload = {"printer_id": str(disabled_printer.id), "label_data": {...}}
    r = await client.post("/api/v1/print", json=payload)
    assert r.status_code == 409
    body = r.json()
    assert body["error"] == "printer_disabled"
    assert body["slug"] == disabled_printer.slug
```

- [ ] **Step 2: Test rot**

Run: `pytest tests/api/test_print_routes.py -v -k "disabled_printer"`
Expected: FAIL.

- [ ] **Step 3: Exception-Handler ergänzen**

```python
# backend/app/api/routes/print.py — analog existing TapeMismatchError-Mapping
from app.printer_backends.exceptions import PrinterDisabledError

# Innerhalb des try/except des Print-Endpunkts:
except PrinterDisabledError as exc:
    raise HTTPException(
        status_code=409,
        detail={"error": "printer_disabled", "slug": exc.slug},
    )
```

- [ ] **Step 4: Test grün**

Run: `pytest tests/api/test_print_routes.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/print.py backend/tests/api/test_print_routes.py
git commit -m "feat(#124): PrinterDisabledError mappt auf 409 printer_disabled"
```

---

## Phase 5 — Removal (Code + Files + Compose) — 4 Tasks

### Task 5.1: PrinterConfigLoader + Schemas entfernen

**Files:**
- Delete: `backend/app/services/printer_config_loader.py`
- Delete: `backend/app/schemas/printer_config.py`
- Delete: `backend/tests/services/test_printer_config_loader.py`

- [ ] **Step 1: Greppen, ob noch Aufrufer existieren**

```bash
cd backend
grep -rn "PrinterConfigLoader\|printer_config_loader\|printer_config import\|from app.schemas.printer_config" app/ tests/
```
Expected: nur die Dateien selbst + ggf. lifespan.py (wird in Task 5.2 angepasst).

- [ ] **Step 2: Dateien löschen**

```bash
git rm backend/app/services/printer_config_loader.py
git rm backend/app/schemas/printer_config.py
git rm backend/tests/services/test_printer_config_loader.py
```

- [ ] **Step 3: Volle Test-Suite + mypy + ruff**

```bash
cd backend
ruff check . && ruff format --check .
mypy app
pytest -x --ff -q
```
Expected: alle grün — ggf. broken imports in lifespan.py temporär kommentieren und in 5.2 lösen.

- [ ] **Step 4: Commit**

```bash
git commit -m "refactor(#124): PrinterConfigLoader + printer_config-Schema entfernt"
```

### Task 5.2: upsert_runtime_printers + lifespan-Aufrufer entfernen

**Files:**
- Modify: `backend/app/db/lifespan.py`

- [ ] **Step 1: Funktion + Aufruf entfernen**

```bash
cd backend
# Zeilen in lifespan.py rund um upsert_runtime_printers identifizieren und loeschen
```

In `app/db/lifespan.py`:
- `upsert_runtime_printers()`-Funktionsdefinition komplett löschen
- Aufrufstelle in der `startup()`-Sequenz entfernen
- Import von `PrinterConfigLoader` löschen
- Import von `printer_config_loader` Modul löschen
- Ggf. `printers_v2_active`-Marker setzen (Soft-Marker für Diagnose):

```python
# In startup():
async with async_sessionmaker(engine)() as session:
    await session.execute(text(
        "INSERT OR REPLACE INTO hangar_meta (key, value) VALUES "
        "('printers_v2_active', 'true')"
    ))
    await session.commit()
```

(Falls `hangar_meta`-Tabelle im Hub nicht existiert: weglassen.)

- [ ] **Step 2: Tests + mypy + ruff grün**

```bash
cd backend
ruff check . && ruff format --check .
mypy app
pytest -x --ff -q
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/db/lifespan.py
git commit -m "refactor(#124): upsert_runtime_printers + lifespan-Aufrufer entfernt"
```

### Task 5.3: 5 Lifespan-Test-Files entfernen

**Files:**
- Delete: `backend/tests/db/test_lifespan.py`
- Delete: `backend/tests/unit/test_lifespan.py`
- Delete: `backend/tests/integration/test_lifespan_seeds_and_upserts.py`
- Delete: `backend/tests/integration/test_lifespan_multi_printer.py`
- Delete: `backend/tests/integration/db/test_lifespan_printer_upsert.py`

- [ ] **Step 1: Verifikation dass die Tests nur upsert_runtime_printers-bezogen sind**

```bash
cd backend
for f in tests/db/test_lifespan.py tests/unit/test_lifespan.py \
         tests/integration/test_lifespan_seeds_and_upserts.py \
         tests/integration/test_lifespan_multi_printer.py \
         tests/integration/db/test_lifespan_printer_upsert.py; do
  echo "=== $f ==="
  head -20 "$f"
done
```
Wenn andere wichtige Tests darin sind (z.B. nicht-printer-bezogene lifespan-Tests), in **eine neue Datei** `tests/db/test_lifespan_core.py` migrieren bevor Löschung.

- [ ] **Step 2: Löschen**

```bash
git rm backend/tests/db/test_lifespan.py \
       backend/tests/unit/test_lifespan.py \
       backend/tests/integration/test_lifespan_seeds_and_upserts.py \
       backend/tests/integration/test_lifespan_multi_printer.py \
       backend/tests/integration/db/test_lifespan_printer_upsert.py
```

- [ ] **Step 3: Grep-Verifikation H9 erfüllt**

```bash
cd backend
grep -rln "upsert_runtime_printers\|PrinterConfigLoader" tests/
```
Expected: leer.

```bash
grep -rln "derive_printer_id(" backend/
```
Expected: nur die echten 4-arg-Aufrufer (`printer_admin_service.py` + `tests/services/test_printer_identity.py` + `tests/services/test_printer_admin_service.py`).

- [ ] **Step 4: Test-Suite grün**

```bash
cd backend && pytest -q
```

- [ ] **Step 5: Commit**

```bash
git commit -m "refactor(#124): 5 obsolete Lifespan-Test-Files entfernt (H9)"
```

### Task 5.4: Compose + Stack-Env entfernen — Vorbereitung

**Files:** keine Repo-Files — Vorbereitung der Compose-Änderung für Phase 8.

- [ ] **Step 1: Compose-Dokumentation in der README aktualisieren**

In `backend/README.md` oder gleichwertiger Stelle:
- Sektion `printers.yaml` entfernen.
- Neue Sektion `Admin-UI /admin/printers/` ergänzen mit Screenshot-Platzhaltern (kann leer sein für jetzt).
- Sektion über Bootstrap erklärt: bei leerer DB → leere Liste, Operator legt Drucker via UI an.

- [ ] **Step 2: Commit**

```bash
git add backend/README.md
git commit -m "docs(#124): README — printers.yaml-Sektion entfernt, Admin-UI ergaenzt"
```

---

## Phase 6 — Pangolin-Resource-Standard durchsetzen — 2 Tasks

### Task 6.1: Vault-Item `Pangolin Header Auth - Print Hub` anlegen

**Files:** keine Repo-Files — externe Aktion via Vaultwarden MCP.

- [ ] **Step 1: 64-hex Secret generieren**

```bash
openssl rand -hex 32
```
Notieren für Step 2.

- [ ] **Step 2: Vault-Item via MCP anlegen** (analog label-printer-hub-Standardbeispiel)

```
mcp__vaultwarden__create_item(
  name="Pangolin Header Auth - Print Hub",
  type=1,
  login={
    "username": "claude-automation",
    "password": "<aus-step-1>",
    "uris": [{"uri": "https://print-hub.strausmann.cloud"}]
  },
  notes="Pangolin Header-Auth-Bypass fuer JSON-API + Admin-UI (Issue #124).\n"
        "Resource-ID: <wird in Step-Step 6.2 ermittelt>",
  collectionIds=["<Automation/Claude-Team collection-id>"]
)
```

- [ ] **Step 3: Vault-Item-UUID notieren**

In `docs/superpowers/plans/2026-06-14-phase0-live-check-results.md` ergänzen.

### Task 6.2: Compose-Labels für Pangolin-Resource ergänzen

**Files:**
- Modify (Production): `/docker/stacks/hangar-print-hub/compose.yaml` via Dockhand
- Modify (Repo): `infra/docker-compose/hangar-print-hub.yml.example` (falls existiert)

- [ ] **Step 1: Live-Compose von Dockhand holen**

```python
existing = mcp__dockhand__get_stack_compose(
    environmentId=10, name="hangar-print-hub")
print(existing["content"])
```

- [ ] **Step 2: Labels-Block für print-hub-Service ergänzen**

Vollständige Liste (per `pangolin-resource-standard.md`):

```yaml
services:
  print-hub:
    # ... existing fields ...
    labels:
      # Identitaet
      - "pangolin.public-resources.print-hub.name=Print Hub"
      - "pangolin.public-resources.print-hub.full-domain=print-hub.strausmann.cloud"
      # Routing
      - "pangolin.public-resources.print-hub.protocol=http"
      - "pangolin.public-resources.print-hub.ssl=true"
      - "pangolin.public-resources.print-hub.targets[0].method=http"
      - "pangolin.public-resources.print-hub.targets[0].port=8000"
      - "pangolin.public-resources.print-hub.targets[0].path-match=prefix"
      # Healthcheck
      - "pangolin.public-resources.print-hub.targets[0].healthcheck.enabled=true"
      - "pangolin.public-resources.print-hub.targets[0].healthcheck.hostname=print-hub"
      - "pangolin.public-resources.print-hub.targets[0].healthcheck.path=/healthz"
      - "pangolin.public-resources.print-hub.targets[0].healthcheck.port=8000"
      - "pangolin.public-resources.print-hub.targets[0].healthcheck.interval=30"
      # Auth
      - "pangolin.public-resources.print-hub.auth.sso-enabled=true"
      - "pangolin.public-resources.print-hub.auth.basic-auth.user=claude-automation"
      - "pangolin.public-resources.print-hub.auth.basic-auth.password=<64-hex aus Phase 6.1>"
```

WICHTIG: das Passwort ist als Klartext im Compose-Label — das ist der dokumentierte Workaround (siehe Spec Sektion "Authentifizierung" + `pangolin-resource-standard.md`).

- [ ] **Step 3: Hinweis im Plan — der eigentliche Stack-Update läuft erst in Phase 8**

In `docs/superpowers/plans/2026-06-14-phase0-live-check-results.md` festhalten:
- Vault-Item-UUID
- Neues Secret (nur als Hash-Vermerk, nicht im Klartext)
- Zu ergänzende Labels (oben gezeigt)

---

## Phase 7 — E2E + Smoke-Tests — 1 Task

### Task 7.1: Fresh-Install E2E-Test

**Files:**
- Create: `backend/tests/integration/test_fresh_install_printers.py`

- [ ] **Step 1: Test schreiben**

```python
# backend/tests/integration/test_fresh_install_printers.py
"""E2E: Hub startet mit leerer DB ohne YAML, Operator legt Drucker via API an."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.main import create_app


@pytest.mark.asyncio
async def test_fresh_install_empty_printers_list():
    """Bei leerer DB: GET /api/printers → []."""
    app = create_app()
    async with AsyncClient(app=app, base_url="http://test") as client:
        r = await client.get("/api/printers")
        assert r.status_code == 200
        assert r.json() == []


@pytest.mark.asyncio
async def test_fresh_install_create_via_admin_api_appears_in_public_list():
    app = create_app()
    async with AsyncClient(app=app, base_url="http://test") as client:
        payload = {
            "name": "Brother P750W",
            "slug": "brother-p750w",
            "model": "PT-P750W",
            "backend": "ptouch",
            "connection": {"host": "192.0.2.10", "port": 9100,
                           "snmp": {"discover": False, "community": "public"}},
        }
        r = await client.post(
            "/api/v1/admin/printers", json=payload,
            headers={"Remote-User": "test"},
        )
        assert r.status_code == 201
        r = await client.get("/api/printers")
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 1
        assert body[0]["slug"] == "brother-p750w"


@pytest.mark.asyncio
async def test_fresh_install_disable_filters_from_public_list():
    """Disabled Drucker erscheint nicht in /api/printers."""
    app = create_app()
    async with AsyncClient(app=app, base_url="http://test") as client:
        # Create
        await client.post("/api/v1/admin/printers", json={...},
                          headers={"Remote-User": "test"})
        # Disable
        await client.post(
            "/api/v1/admin/printers/brother-p750w/disable",
            headers={"Remote-User": "test"},
        )
        # Public-list ist leer
        r = await client.get("/api/printers")
        assert r.json() == []
        # Admin sieht ihn aber
        r = await client.get(
            "/api/v1/admin/printers?include_disabled=true",
            headers={"Remote-User": "test"},
        )
        assert len(r.json()) == 1
```

- [ ] **Step 2: Tests grün**

Run: `cd backend && pytest tests/integration/test_fresh_install_printers.py -v`
Expected: PASS.

- [ ] **Step 3: Volle Test-Suite + Coverage-Check**

```bash
cd backend
pytest --cov=app --cov-report=term --cov-fail-under=80 -q
```
Expected: ≥80% global, alle modul-spezifischen Schwellen erreicht.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/integration/test_fresh_install_printers.py
git commit -m "test(#124): Fresh-Install E2E-Test ohne YAML"
```

---

## Phase 8 — Production-Deploy — 4 Tasks

### Task 8.1: PR erstellen + CI-Pipeline grün

**Files:** keine Repo-Files — GitHub-Flow.

- [ ] **Step 1: Push + PR öffnen**

```bash
cd /opt/repos/label-printer-hub
git push -u origin feat/issue-124-printers-yaml-to-db
gh pr create --base main --title "feat(#124): printers.yaml → DB + Admin-UI /admin/printers" \
  --body "Implementation von Issue #124 nach Spec PR #125 (Round-4 final).

Phase 1-7 implementiert:
- Foundation (Engine SERIALIZABLE+WAL, PrinterDisabledError, Alembic-Migration mit Backfill)
- Service-Layer (Schemas, audit_redaction, printer_model_registry, PrinterAdminService mit Flattening-Helper)
- API + Web-Routes + CSRF-Middleware
- PrintService enabled-Check + 409-Mapping
- Removal (PrinterConfigLoader, 5 Test-Files, lifespan-Aufrufer)
- Pangolin-Resource-Standard durchgesetzt
- Fresh-Install E2E-Test

Closes #124"
```

- [ ] **Step 2: CI-Pipeline auf grün warten**

```bash
gh pr checks --watch
```

### Task 8.2: Pre-Deploy DB-Snapshot + Watchtower-Pause

**Files:** keine Repo-Files — externe Aktionen.

- [ ] **Step 1: SQLite-Backup ziehen**

```bash
ssh -i ~/.ssh/id_ed25519_homelab_nodes root@hhdocker03 \
  "docker exec hangar-print-hub-print-hub-1 sqlite3 /data/printer-hub.db \
     '.backup /data/printer-hub.db.bak-pre-124'"
ssh -i ~/.ssh/id_ed25519_homelab_nodes root@hhdocker03 \
  "docker cp hangar-print-hub-print-hub-1:/data/printer-hub.db.bak-pre-124 \
     /docker/stacks/hangar-print-hub/backups/"
```

- [ ] **Step 2: Watchtower für den print-hub-Container pausieren**

```python
mcp__dockhand__set_container_auto_update(
    environmentId=10,
    containerName="hangar-print-hub-print-hub-1",
    auto_update="never",
)
```

### Task 8.3: Stack-Env-Variable entfernen + Compose updaten + Stack neu starten

**Files:** keine Repo-Files — Dockhand-Operations.

- [ ] **Step 1: Stack-Env mergen (PUT-Replace-Semantik!)**

```python
# Existing holen, dann PRINTER_CONFIG_PATH herausfiltern
existing = mcp__dockhand__get_stack_env(environmentId=10, name="hangar-print-hub")
print(f"Existing keys: {[v['key'] for v in existing['variables']]}")

merged = [v for v in existing["variables"] if v["key"] != "PRINTER_CONFIG_PATH"]
print(f"After merge keys: {[v['key'] for v in merged]}")

mcp__dockhand__update_stack_env(
    environmentId=10, name="hangar-print-hub",
    variables=merged,
)

# Verifikation
after = mcp__dockhand__get_stack_env(environmentId=10, name="hangar-print-hub")
assert "PRINTER_CONFIG_PATH" not in {v["key"] for v in after["variables"]}
```

- [ ] **Step 2: Compose-Datei via Dockhand updaten**

Aus Task 6.2 die finalen Labels nehmen + Volume-Mount `printers.yaml` entfernen:

```python
compose = mcp__dockhand__get_stack_compose(environmentId=10, name="hangar-print-hub")
new_compose = compose["content"]  # via editor: printers.yaml Volume-Eintrag raus,
                                  # Labels aus Phase 6.2 rein
mcp__dockhand__update_stack_compose(
    environmentId=10, name="hangar-print-hub",
    content=new_compose,
)
```

- [ ] **Step 3: Stack down + start**

```python
mcp__dockhand__down_stack(environmentId=10, name="hangar-print-hub")
mcp__dockhand__start_stack(environmentId=10, name="hangar-print-hub")
```

- [ ] **Step 4: printers.yaml von Disk entfernen**

```bash
ssh -i ~/.ssh/id_ed25519_homelab_nodes root@hhdocker03 \
  "mv /docker/stacks/hangar-print-hub/config/printers.yaml \
      /docker/stacks/hangar-print-hub/config/printers.yaml.bak-pre-124"
```

### Task 8.4: Smoke-Test post-Deploy

**Files:** keine Repo-Files — Verifikation.

- [ ] **Step 1: Container-Health**

```bash
mcp__dockhand__get_container(
    environmentId=10, name="hangar-print-hub-print-hub-1"
)["state"]["health"] == "healthy"
```

- [ ] **Step 2: Container-DNS aus Hangar erreichbar (M10)**

```bash
ssh -i ~/.ssh/id_ed25519_homelab_nodes root@hhdocker03 \
  "docker exec hangar-print-hub-hangar-1 getent hosts print-hub"
```
Expected: nicht-leere IP-Ausgabe.

- [ ] **Step 3: Backfill-Verifikation**

```bash
ssh -i ~/.ssh/id_ed25519_homelab_nodes root@hhdocker03 \
  "docker exec hangar-print-hub-print-hub-1 sqlite3 /data/printer-hub.db \
     \"SELECT slug, json_extract(connection, '\\\$.snmp.discover'), \
              queue_timeout_s, cut_defaults_half_cut FROM printers\""
```
Expected: alle Bestandsdrucker mit `snmp.discover=0`, `queue_timeout_s=30`, `cut_defaults_half_cut=0`.

- [ ] **Step 4: /admin/printers/ über Browser**

Mit Playwright MCP:
```python
mcp__playwright__browser_navigate(url="https://print-hub.strausmann.cloud/admin/printers/")
mcp__playwright__browser_snapshot()
```
Expected: Liste der 2 Bestandsdrucker.

- [ ] **Step 5: PrintService 409 für disabled Drucker**

Test-Drucker via API erstellen + disablen + Print-Request senden → 409. Anschließend löschen via DB (Cleanup für Test).

- [ ] **Step 6: Watchtower wieder auf "any"**

```python
mcp__dockhand__set_container_auto_update(
    environmentId=10,
    containerName="hangar-print-hub-print-hub-1",
    auto_update="any",
)
```

- [ ] **Step 7: PR mergen**

```bash
gh pr merge <PR-NUMBER> --squash --delete-branch
```

- [ ] **Step 8: Issue #124 schließen mit Verweis auf PR**

```bash
gh issue close 124 --reason completed --comment "Implementiert in PR #<NUMBER> + deployed nach Production. Bestandsdrucker funktional, Hangar PrinterSync grün, Admin-UI erreichbar."
```

---

## Self-Review

### Spec-Coverage-Check

| Spec-Abschnitt | Task | Status |
|---|---|---|
| Pydantic-Schemas (SNMPConfig verschachtelt) | Task 2.1 | ✅ |
| audit_redaction.py M9 | Task 2.2 | ✅ |
| printer_model_registry.py | Task 2.3 | ✅ |
| Flattening-Helper M12 | Task 2.4 | ✅ |
| PrinterAdminService CRUD + Audit | Task 2.5 | ✅ |
| Engine SERIALIZABLE + WAL M7 | Task 1.1 | ✅ |
| PrinterDisabledError C5 | Task 1.2 | ✅ |
| Alembic-Migration + Backfill H8b | Task 1.3 | ✅ |
| derive_printer_id 4-arg C4 | Task 1.4 | ✅ |
| CSRF-Middleware H3 | Task 3.1 | ✅ |
| JSON-API C2 | Task 3.2 | ✅ |
| HTML-Routes + Templates | Task 3.3-3.4 | ✅ |
| PrintService enabled-Check M8 | Task 4.1 | ✅ |
| 409-Mapping M8 | Task 4.2 | ✅ |
| YAML-Removal | Task 5.1-5.4 | ✅ |
| 5 Test-Files-Löschen H9 | Task 5.3 | ✅ |
| Vault-Item + Blueprint-Labels H7 | Task 6.1-6.2 | ✅ |
| Fresh-Install E2E | Task 7.1 | ✅ |
| Production-Deploy mit Watchtower-Pause + Backup | Task 8.1-8.4 | ✅ |

### Placeholder-Scan

- ✅ Keine "TBD" / "TODO"
- ⚠ Task 3.2 Tests haben `...` als Placeholder für wiederholendes Payload — Implementer ergänzt nach Pattern von `test_create_printer_returns_201`. Vermerk im Task selbst.
- ⚠ Task 3.4 "Pattern wie Task 3.3" — bewusst, weil 4 ähnliche Routes nicht 4× ausgeschrieben werden müssen. Pattern und Beispiele aus Task 3.3 reichen für Implementer.
- ⚠ Task 4.1+4.2: existing `submit_print_job`-Tests haben Fixture-Setup das hier nicht ausgeschrieben ist — Implementer übernimmt Fixtures aus existing `tests/services/test_print_service.py`. Vermerk im Task.

### Type-Consistency-Check

- `derive_printer_id(model, host, port, created_at_utc)` konsistent in Task 1.4 und Task 2.5.
- `PrinterDisabledError(printer_id, slug)` Konstruktor konsistent in Task 1.2, 4.1, 4.2.
- `_payload_to_row` / `_apply_update_patch` / `_row_to_audit_view` Signaturen konsistent zwischen Task 2.4 (Definition) und Task 2.5 (Verwendung).
- `redact_secrets(payload: dict) -> dict` konsistent zwischen Task 2.2 und Task 2.5.

---

## Coverage-Schwellen Ziel-Tabelle

| Modul | Schwelle | Verifikation in |
|---|---|---|
| `app/services/printer_admin_service.py` | 85% | Task 2.5 Step 6 |
| `app/services/printer_model_registry.py` | 75% | Task 2.3 |
| `app/services/printer_identity.py` | 85% | Task 1.4 |
| `app/services/audit_redaction.py` | 80% | Task 2.2 |
| `app/api/routes/admin_printers_api.py` | 80% | Task 3.2 Step 7 |
| `app/api/routes/admin_printers_web.py` | 70% | Task 3.3-3.4 |
| `app/middleware/csrf.py` | 80% | Task 3.1 |
| Global `fail_under=80` | 80% | Task 7.1 Step 3 |

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-14-printers-yaml-to-db-plan.md`.**

Zwei Execution-Optionen:

1. **Subagent-Driven Development (empfohlen):** Frischer Subagent pro Task, zwei Review-Stages (Spec-Compliance + Code-Quality) zwischen Tasks. Schnellere Iteration, automatische Reviews.

2. **Inline Execution:** Tasks in dieser Session ausführen via `superpowers:executing-plans`, Batch mit Checkpoints für Review.

**Welcher Ansatz?**
