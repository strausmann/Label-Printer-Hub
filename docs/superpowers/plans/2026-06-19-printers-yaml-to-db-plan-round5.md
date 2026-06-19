# Hub #124 — printers.yaml → DB + Admin-UI Implementation Plan (Round-5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Backend (Python/FastAPI) verlagert Drucker-Verwaltung von `printers.yaml` in DB-Tabelle mit JSON-Admin-API; Frontend (Go + chi + html/template + HTMX) bekommt `/admin/printers/` UI; CSRF-Hardening (gorilla/csrf) wird in selber Migration für existing Admin-Routes nachgerüstet.

**Architektur:** Two-Container: `label-printer-hub-backend` (Python, Port 8000, JSON-only) + `label-printer-hub-frontend` (Go, Port 8080, HTML+Reverse-Proxy). Pangolin-Resource 123 `labels.strausmann.cloud` mit headerAuthId 8 (claude-automation).

**Tech-Stack:** Backend: Python 3.12 + FastAPI + SQLAlchemy 2 async + aiosqlite + Pydantic v2 + Alembic + pytest. Frontend: Go 1.24 + chi v5 + html/template + HTMX 2.0.4 + Tailwind v4 + gorilla/csrf + oapi-codegen.

**Spec:** [2026-06-14-printers-yaml-to-db-design.md](../specs/2026-06-14-printers-yaml-to-db-design.md) Round-6 mit Known-Issues-Anhang.

**Issue:** https://github.com/strausmann/Label-Printer-Hub/issues/124

**Working-Branch:** `feat/issue-124-printers-db` (von `origin/main` ausgehend in Task 0.1)

---

## Plan-Prinzip: Live-Verifikation hat Vorrang

Spec hat dokumentierte Known Issues (Anhang am Ende der Spec). **Spec-Werte sind Vorschläge — Live-Container-Werte sind Wahrheit.** Jede Phase startet mit einem **Pre-Check-Step** der Production-Werte aus dem laufenden System zieht und in `docs/superpowers/plans/2026-06-19-phase0-live-state.md` speichert. Spec-Werte werden gegen diese Live-Werte abgeglichen — bei Konflikt gewinnt Live-Container.

Implementer-Pflicht pro Phase:
1. Lies `phase0-live-state.md` für relevante Werte (DB-Pfad, API-Prefix, etc.)
2. Wenn neue Werte gebraucht werden: `docker inspect` / `git show` / Backend-Live-Call → in phase0-live-state.md ergänzen
3. Bei Konflikt Spec ↔ Live: **NIEMALS** Spec-Wert nutzen, IMMER Live-Wert + PR-Kommentar mit Befund

---

## Phasen-Übersicht

| Phase | Beschreibung | Tasks | Risiko |
|---|---|---|---|
| 0 | Live-Check + Branch + Pre-Check-Doku | 1 (extensiv) | niedrig |
| 1 | Backend Foundation | 4 | niedrig |
| 2 | Backend Service-Layer | 5 | mittel |
| 3 | Backend JSON-Admin-API | 1 | niedrig |
| 4 | Backend PrintService enabled-Check | 1 | niedrig |
| 5 | Backend Removal (PrinterConfigLoader + Tests) | 1 | niedrig |
| 6 | Phase 6.0 Bootstrap + Pangolin-Verifikation | 2 | mittel |
| 7 | Frontend CSRF + Admin-UI | 4 | hoch (neue Sprache + Pattern) |
| 8 | Production-Deploy mit Live-Pfaden | 4 | mittel |

**Total: ~22 Tasks**, 5-8h Implementation.

---

## Phase 0 — Live-Check + Phase-0-State-Doku

### Task 0.1: Live-State sammeln + Branch erstellen

**Files:** `docs/superpowers/plans/2026-06-19-phase0-live-state.md` (neu, sammelt alle Live-Werte)

- [ ] **Step 1: Branch erstellen von origin/main**

```bash
cd /opt/repos/label-printer-hub
git fetch origin main
git checkout main && git pull --rebase
git checkout -b feat/issue-124-printers-db origin/main
```

- [ ] **Step 2: phase0-live-state.md erstellen mit allen Pre-Check-Werten**

Live-Daten sammeln und in der Doku festhalten:

```bash
# DB-Pfad
docker inspect label-printer-hub-backend --format '{{range .Mounts}}{{.Source}}→{{.Destination}}{{println}}{{end}}'
# → /docker/stacks/hangar-print-hub/data/hub→/data
# → /docker/stacks/hangar-print-hub/config/printers.yaml→/etc/hub/printers.yaml

# Container-Env
docker exec label-printer-hub-backend env | grep -E 'PRINTER_HUB|HUB_'

# Production-Image-Labels (Commit + Created)
docker inspect label-printer-hub-backend --format '{{.Config.Labels}}'

# DB-Inhalt (printers + Layouts)
docker exec label-printer-hub-backend python -c "
import sqlite3, json
conn = sqlite3.connect('/data/printer-hub.db')
for row in conn.execute('SELECT slug, name, model, backend, connection, enabled FROM printers'):
    print(row)
"

# Pangolin-Resource 123
mcp__pangolin-api__resource_by_resourceId resourceId=123
# Trace: niceId, fullDomain, sso, headerAuthId, headers (X-Pangolin-Token)
# HINWEIS (Round-2-Fix): headerAuthId 8 ist NICHT im API-Response sichtbar
# (Pangolin exponiert das Feld nicht). Stattdessen: Vault-Item-Smoke-Test
# als Verifikation: curl -u claude-automation:<pw> https://labels.../api/printers

# Stack-Env Baseline (für Phase 6.0 Merge-Check)
mcp__dockhand__get_stack_env(environmentId=10, name="label-printer-hub")
# Festhalten: Anzahl Variablen, alle Keys

# Image-Digest beider Container vor Deploy (für Phase 8.5 Rollback)
docker inspect label-printer-hub-backend --format '{{.Image}}'
docker inspect label-printer-hub-frontend --format '{{.Image}}'
# In phase0-live-state.md festhalten als ROLLBACK_BACKEND_IMAGE / ROLLBACK_FRONTEND_IMAGE

# Backend Routes-Inventur (existing API)
git show origin/main:backend/app/api/routes/admin_api_keys.py | grep -E "^router|@router"
# → prefix=/api/admin/api-keys (KEIN v1)

# Frontend go.mod CSRF-Library-Check
git show origin/main:frontend/go.mod | grep -iE "csrf|gorilla"
# → leer (CSRF muss noch eingeführt werden)

# Existing Frontend Admin-Routes
git show origin/main:frontend/cmd/server/main.go | grep -E "Route|Handle|Post|/admin/"
```

Inhalt von `phase0-live-state.md`:

```markdown
# Phase 0 Live-State (Issue #124, 2026-06-19)

## Container-Mounts
| Container | Host-Pfad | Container-Pfad |
|---|---|---|
| label-printer-hub-backend | /docker/stacks/hangar-print-hub/data/hub | /data |
| label-printer-hub-backend | /docker/stacks/hangar-print-hub/config/printers.yaml | /etc/hub/printers.yaml |

## Backend
- Image: ghcr.io/strausmann/label-printer-hub-backend:dev
- Revision: 2ff51d2c (main)
- Env PRINTER_HUB_PRINTERS_CONFIG=/etc/hub/printers.yaml
- Existing admin-api-keys-Route prefix: /api/admin/api-keys (KEIN v1)

## Frontend
- Image: ghcr.io/strausmann/label-printer-hub-frontend:dev
- Revision: 2ff51d2c (main)
- CSRF-Library: KEINE (go.mod check) — gorilla/csrf wird in Phase 7 eingeführt
- Existing Admin-Routes: /admin/api-keys/*

## Pangolin
- Resource-ID: 123
- niceId: label-printer-hub
- fullDomain: labels.strausmann.cloud
- sso: true
- headerAuthId: 8 (vault-item: "Pangolin Header Auth - Label Printer Hub", user: claude-automation)
- targets[0].port: 8080 (frontend)
- targets[0].hcEnabled: true, healthy
- targets[0].hcHostname: label-printer-hub-frontend

## Watchtower
- Container-Scope-Label: hangar-print-hub (HISTORISCH)
- Pause-Aufruf: nach containerName filtern, nicht nach scope

## DB-Stand (vor Migration)
- printers: <N> Rows (live ausfüllen)
- printers_audit: existiert NICHT (wird in Phase 1.3 erstellt)
- hub_layouts: <N> Rows (von Hangar-Layouts unverändert)
```

- [ ] **Step 3: Commit der Phase-0-Doku**

```bash
git add docs/superpowers/plans/2026-06-19-phase0-live-state.md
git commit -m "docs(#124): Phase 0 Live-State sammeln (alle Werte als ground truth)"
```

---

## Phase 1 — Backend Foundation

### Task 1.1: SQLite Engine SERIALIZABLE + WAL Connect-Listener

**Files:** `backend/app/db/engine.py` + `backend/tests/db/test_engine_pragmas.py`

**Pre-Check:** `phase0-live-state.md` → DB-Pfad (für Test-Setup)

- [ ] Step 1: failing-Test schreiben (PRAGMA `journal_mode=WAL` + `foreign_keys=1`)
- [ ] Step 2: Tests laufen — FAIL
- [ ] Step 3: `engine.py` anpassen: `isolation_level="SERIALIZABLE"` + `@event.listens_for("connect")` Listener
- [ ] Step 4: Tests grün
- [ ] Step 5: Volle Test-Suite — keine Regressions
- [ ] Step 6: Commit `feat(#124): SQLite SERIALIZABLE + WAL Connect-Listener`

Code-Details siehe Spec Round-4 Sektion "M7 Transaktions-Strategie" + `backend/app/db/engine.py` existing.

### Task 1.2: PrinterDisabledError Exception

**Files:** `backend/app/printer_backends/exceptions.py` + `backend/tests/unit/printer_backends/test_exceptions.py`

- [ ] Step 1: failing-Test (PrinterDisabledError subclass of PrinterError + Konstruktor)
- [ ] Step 2: FAIL → Step 3: `PrinterDisabledError(PrinterError)` ergänzen
- [ ] Step 4: grün → Step 5: Commit `feat(#124): PrinterDisabledError fuer Soft-Delete`

Details: Spec Round-4 Sektion "Error Handling".

### Task 1.3: Alembic-Migration — Schema-Erweiterung + Audit + Backfill

**Files:** `backend/alembic/versions/<ts>_printers_audit_and_backfill.py` + `backend/app/models/printer.py` + `backend/tests/db/test_migration_124.py`

**Pre-Check:** `phase0-live-state.md` → printers-Tabelle Inhalt (für Backfill-Verifikation)

- [ ] Step 1: `alembic revision -m "add_printers_audit_and_backfill"` erzeugt Skeleton
- [ ] Step 2: Migration-Code mit `_backfill_snmp(bind)`-Helper als top-level Funktion (testbar)
- [ ] Step 3: ORM-Modell `Printer` um `queue_timeout_s` + `cut_defaults_half_cut` Spalten erweitern
- [ ] Step 4: Tests für Migration + Backfill (mit `run_sync` für AsyncConnection)
- [ ] Step 5: Volle Test-Suite + `alembic upgrade head` + downgrade-Test (no-op pass)
- [ ] Step 6: Commit `feat(#124): Alembic-Migration Schema-Erweiterung + printers_audit + Backfill`

Details: Spec Round-4 Sektion "Migration für Bestand" Phase 1b.

### Task 1.4: derive_printer_id 4-arg (timezone-aware Pflicht)

**Files:** `backend/app/services/printer_identity.py` + `backend/tests/services/test_printer_identity.py`

- [ ] Step 1: failing-Tests (4-arg, naive datetime → ValueError, UUID-Determinismus)
- [ ] Step 2: FAIL → Step 3: Funktion erweitern + ValueError für naive datetime
- [ ] Step 4: grün → Step 5: Aufrufer in `upsert_runtime_printers` (lifespan.py) anpassen — falls noch nicht in Phase 5 entfernt
- [ ] Step 6: Volle Test-Suite (alte 3-arg Tests entfernen oder migrieren)
- [ ] Step 7: Commit `feat(#124): derive_printer_id 4-arg mit timezone-aware created_at_utc`

---

## Phase 2 — Backend Service-Layer

### Task 2.1: Pydantic-Schemas (SNMP verschachtelt)

**Files:** `backend/app/schemas/printer_admin.py` (neu) + `backend/tests/schemas/test_printer_admin_schemas.py`

- [ ] TDD: SNMPConfig (discover+community, validator), PrinterConnection (host+port+snmp), PrinterCreatePayload, PrinterUpdatePayload, PrinterCutDefaults, PrinterQueueSettings — alle mit ge/le/pattern Validations
- [ ] Slug-Regex `^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$`
- [ ] Commit `feat(#124): Pydantic-Schemas fuer Admin-API`

Details: Spec Round-4 Sektion "Pydantic-Schemas".

### Task 2.2: audit_redaction.py

**Files:** `backend/app/services/audit_redaction.py` (neu) + Tests

- [ ] SECRET_PATHS frozenset, redact_secrets() mit deepcopy, 5 Edge-Cases (None, missing, etc.)
- [ ] Commit `feat(#124): audit_redaction.py SNMP-Community-Redaction`

### Task 2.3: printer_model_registry.py

**Files:** `backend/app/services/printer_model_registry.py` (neu) + Tests

- [ ] Plugin-Imports (ptouch.PRINTERS, brother_ql.MODELS) + HARDCODED_FALLBACK_MODELS
- [ ] Commit `feat(#124): printer_model_registry fuer Frontend-Model-Dropdown`

### Task 2.4: PrinterAdminService Flattening-Helper

**Files:** `backend/app/services/printer_admin_service.py` (neu, Skeleton) + Tests

- [ ] `_payload_to_row`, `_apply_update_patch`, `_row_to_audit_view` als Modul-Funktionen mit Tests
- [ ] Commit `feat(#124): PrinterAdminService Flattening-Helper (Spec M12)`

### Task 2.5: PrinterAdminService CRUD + Audit

**Files:** Erweiterung von `printer_admin_service.py` + Tests

- [ ] Class mit create_printer, update_printer, disable_printer, enable_printer, list_printers (include_disabled), get_printer, _record_audit
- [ ] Coverage ≥85%
- [ ] Commit `feat(#124): PrinterAdminService CRUD + Audit-Recording`

### Task 2.6: printers_repo.list_all enabled-Filter (C2-Round-1)

**Files:** `backend/app/repositories/printers.py` + Tests

- [ ] `include_disabled` Parameter ergänzen, Default False
- [ ] Tests für 3 Verhalten (default, include_disabled=True, leer)
- [ ] Commit `feat(#124): printers_repo enabled-Filter`

### Task 2.7: GET /api/printers nutzt Filter

**Files:** `backend/app/api/routes/printers.py` + Tests

- [ ] Route nutzt repo-Default (include_disabled=False)
- [ ] Smoke-Test: disabled Drucker filtert raus
- [ ] Commit `feat(#124): GET /api/printers filtert disabled`

---

## Phase 3 — Backend JSON-Admin-API

### Task 3.1: /api/v1/admin/printers JSON-API + Auth

**Files:** `backend/app/api/routes/admin_printers_api.py` (neu) + `backend/app/auth/dependencies.py` (require_admin_user Dependency) + `backend/app/main.py` (Router-Include) + Tests

**Pre-Check:** `phase0-live-state.md` → existing admin-api-keys Route-Pattern (auth-style)

- [ ] 6 Endpoints: GET (list+include_disabled), POST (create+409 duplicate), GET/{slug} (detail+404), PUT/{slug} (update silent-ignore), POST/{slug}/disable, POST/{slug}/enable
- [ ] Auth: `require_admin_user` Dependency die `Remote-User` ODER `X-Remote-User` (vom Frontend) ODER Basic-Auth (claude-automation Bypass) akzeptiert
- [ ] 9 Tests (alle Endpoints + 403 ohne Auth + 409 Duplicate)
- [ ] Coverage ≥80%
- [ ] Commit `feat(#124): JSON-API /api/v1/admin/printers`

Details: Spec Round-4 Sektion "JSON-API" + Round-5 Auth-Flow.

---

## Phase 4 — Backend PrintService enabled-Check

### Task 4.1: PrintService.submit_print_job enabled-Check + 409-Mapping

**Files:** `backend/app/services/print_service.py` + `backend/app/api/routes/print.py` + Tests

- [ ] Service raised PrinterDisabledError bei disabled
- [ ] Route mappt auf 409 mit Body `{"error": "printer_disabled", "slug": "..."}`
- [ ] 2 Tests (service-level + http-level)
- [ ] Commit `feat(#124): PrintService enabled-Check + 409-Mapping`

---

## Phase 5 — Backend Removal

### Task 5.1: PrinterConfigLoader + bootstrap-Aufrufer + 5 Test-Files entfernen

**Files:**
- Delete: `backend/app/services/printer_config_loader.py`
- Delete: `backend/app/schemas/printer_config.py`
- Modify: `backend/app/db/lifespan.py` (upsert_runtime_printers entfernen)
- Delete: 5 Test-Files (test_printer_config_loader, test_lifespan (db+unit), test_lifespan_seeds_and_upserts, test_lifespan_multi_printer, test_lifespan_printer_upsert)

**Pre-Check:** `grep -rn "PrinterConfigLoader\|printer_config_loader\|upsert_runtime_printers" backend/` → muss leer sein nach Cleanup

- [ ] Step 1: grep verifiziert dass keine externen Aufrufer übrig sind
- [ ] Step 2: Files löschen + lifespan.py minimieren
- [ ] Step 3: ruff + mypy + pytest grün
- [ ] Step 4: Commit `refactor(#124): PrinterConfigLoader + lifespan-Sync + 5 Test-Files entfernt`

---

## Phase 6 — Bootstrap + Pangolin-Verifikation

### Task 6.0: Service-Account-Key + CSRF_KEY Bootstrap

**Pre-Check:** `phase0-live-state.md` → existing admin-api-keys Auth-Methode

- [ ] **Step 1: Backend-API-Key direkt im Container erstellen (Round-6-Fix: echte Repo-API + echter Scope)**

Code-Quality-Review Round-5 hat aufgezeigt:
- `APIKeyService` existiert NICHT, Codebase nutzt Repository-Pattern: `app/repositories/api_keys.py::create(session, key)`
- Scopes sind `read | print | admin` (3-stufige Hierarchie), NICHT `admin:printers`/`admin:read`

Korrigiert: Bootstrap nutzt das echte Pattern aus `admin_api_keys_routes.py` (existing key-creation-Endpoint):

```bash
ssh -i ~/.ssh/id_ed25519_homelab_nodes root@hhdocker03 \
  "docker exec label-printer-hub-backend python -c \"
import asyncio
import secrets
from datetime import datetime, timezone
from uuid import uuid4
import bcrypt
from app.db.session import get_session_factory
from app.repositories import api_keys as api_keys_repo
from app.models.api_key import ApiKey

async def main():
    plaintext = 'lh_' + secrets.token_urlsafe(32)
    key_hash = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt()).decode()
    key_prefix = plaintext[:11]
    key = ApiKey(
        id=uuid4(),
        name='frontend-service-account',
        key_hash=key_hash,
        key_prefix=key_prefix,
        scopes=['admin'],   # 3-stufige Hierarchie, admin ist top
        rate_limit_per_minute=600,
        enabled=True,
        created_at=datetime.now(timezone.utc),
    )
    factory = get_session_factory()
    async with factory() as session:
        await api_keys_repo.create(session, key)
    print(f'PLAINTEXT_KEY={plaintext}')

asyncio.run(main())\""
```

**Implementer-Verifikation vor Step 1:**
```bash
docker exec label-printer-hub-backend python -c "from app.models.api_key import ApiKey; import inspect; print(inspect.signature(ApiKey.__init__))"
```
Falls Konstruktor-Signatur abweicht: anpassen statt erfinden. Bei Unsicherheit: existing `admin_api_keys_routes.py::create_api_key` als Live-Vorbild lesen (auf `main`).

- [ ] **Step 2: Plaintext in Vault speichern (Collection: Automation/Claude-Team)**

```python
mcp__vaultwarden__create_item(
  name="Hub Frontend Service-Account API-Key",
  type=1,
  login={"username": "frontend-service-account",
         "password": "<plaintext>"},
  notes="Backend-API-Key fuer Hub-Frontend → Backend Service-Account-Auth. Scope: admin:printers (Issue #124)",
  collectionIds=["<Automation/Claude-Team UUID>"],
)
```

- [ ] **Step 3: CSRF-Key generieren (64-hex-Zeichen für gorilla/csrf)**

```bash
openssl rand -hex 32
# → 64-Zeichen-String z.B. "5ad7..."
```

- [ ] **Step 4: CSRF-Key in Vault**

```python
mcp__vaultwarden__create_item(
  name="Hub Frontend CSRF Key",
  type=1,
  login={"password": "<64-hex-string>"},
  notes="32 raw bytes (= 64 hex chars) fuer gorilla/csrf in Hub-Frontend (Issue #124)",
  collectionIds=["<Automation/Claude-Team UUID>"],
)
```

- [ ] **Step 4b: Compose-Pass-Through für die neuen Secrets (M2-Round-5 ops, KRITISCH gegen Silent-Failure)**

`update_stack_env` schreibt nur die Dockhand-DB-Tabelle. Damit der Container die Vars sieht, müssen sie in `compose.yaml` unter `environment:` als `${VAR}` deklariert sein. Sonst Silent-Failure: Vars sind in Dockhand-DB, Container sieht sie nie.

Frontend-Container (Beispiel):
```yaml
services:
  frontend:
    image: ghcr.io/strausmann/label-printer-hub-frontend:${HUB_VERSION}
    environment:
      BACKEND_URL: http://backend:8000
      BACKEND_SERVICE_ACCOUNT_KEY: ${BACKEND_SERVICE_ACCOUNT_KEY}
      CSRF_KEY: ${CSRF_KEY}
```

Implementer-Pflicht:
- `mcp__dockhand__get_stack_compose(environmentId=10, name="label-printer-hub")` aktuelles Compose holen
- Frontend-Service-Block prüfen — fehlende `environment:` Einträge ergänzen
- `mcp__dockhand__update_stack_compose(...)` mit erweitertem Compose

Verifikation NACH Stack-Restart:
```bash
docker exec label-printer-hub-frontend env | grep -E "BACKEND_SERVICE_ACCOUNT_KEY|CSRF_KEY"
# Beide Vars müssen erscheinen (nur Wert-Prefix sichtbar wegen Secret-Maskierung)
```

- [ ] **Step 5: Stack-Env via Dockhand merge** (Pflicht: existing → filter → put)

```python
existing = mcp__dockhand__get_stack_env(environmentId=10, name="label-printer-hub")
new_vars = list(existing["variables"])
# Filter: doppelte Keys entfernen
new_vars = [v for v in new_vars if v["key"] not in ("BACKEND_SERVICE_ACCOUNT_KEY", "CSRF_KEY")]
new_vars.append({"key": "BACKEND_SERVICE_ACCOUNT_KEY", "value": "<plaintext>", "isSecret": True})
new_vars.append({"key": "CSRF_KEY", "value": "<64-hex>", "isSecret": True})
mcp__dockhand__update_stack_env(environmentId=10, name="label-printer-hub", variables=new_vars)
```

- [ ] **Step 6: Stack down + start damit neue ENV-VARs in Containern landen**

```python
mcp__dockhand__down_stack(environmentId=10, name="label-printer-hub")
mcp__dockhand__start_stack(environmentId=10, name="label-printer-hub")
# Verifikation
docker exec label-printer-hub-frontend env | grep -E "BACKEND_SERVICE_ACCOUNT_KEY|CSRF_KEY"
```

- [ ] **Step 7: Phase-0-Doku ergänzen mit Bootstrap-Outcome**

### Task 6.1: Pangolin-Resource verifizieren + Vault-Notes fixen

- [ ] **Step 1: Resource 123 live abrufen**

```python
mcp__pangolin-api__resource_by_resourceId(resourceId=123)
# Erwartet: niceId="label-printer-hub", headerAuthId=8, sso=True
```

- [ ] **Step 2: headerAuthId 8 Vault-Item verifizieren**

Item "Pangolin Header Auth - Label Printer Hub" existiert, user=claude-automation, password=<live>.

- [ ] **Step 3: Vault-Notes Site-Nummer fixen** (L1 Round-5)

Notes-Feld "Site 4 (HHDOCKER02)" → "Site 6 (HHDOCKER03)".

```python
mcp__vaultwarden__edit_item(id="<vault-item-uuid>", notes="Site 6 (HHDOCKER03)\n... existing notes ...")
```

- [ ] **Step 4: Pangolin-Resource-Standard-Labels-Check** (Phase 0)

healthcheck.hostname=label-printer-hub-frontend → ✅ schon gesetzt (live-verifiziert in Round-5)

- [ ] **Step 5: Commit der Phase-6-Updates**

---

## Phase 7 — Frontend CSRF + Admin-UI

### Task 7.1: gorilla/csrf Library + bestehende Admin-Routes nachrüsten

**Files:** `frontend/go.mod` + `frontend/cmd/server/main.go` + alle existing `frontend/web/templates/admin_*.html` Templates

- [ ] **Step 1: Library hinzufügen**

```bash
cd /opt/repos/label-printer-hub/frontend
go get github.com/gorilla/csrf
go mod tidy
```

- [ ] **Step 2: CSRF-Middleware setup in main.go**

```go
csrfKey := os.Getenv("CSRF_KEY")
// 64 hex chars erwartet (= 32 raw bytes)
if len(csrfKey) != 64 {
    log.Fatal("CSRF_KEY env-var must be 64 hex chars (32 raw bytes)")
}
csrfBytes, err := hex.DecodeString(csrfKey)
if err != nil || len(csrfBytes) != 32 {
    log.Fatal("CSRF_KEY must be 64 hex chars decoding to 32 bytes")
}
csrfMW := csrf.Protect(
    csrfBytes,
    csrf.Secure(true),
    csrf.SameSite(csrf.SameSiteStrictMode),
    csrf.CookieName("__Host-csrf"),
    csrf.RequestHeader("X-CSRF-Token"),
    csrf.FieldName("csrf_token"),
)
```

- [ ] **Step 3: Bestehende Admin-Routes mit csrfMW versehen**

```go
r.Route("/admin", func(r chi.Router) {
    r.Use(csrfMW)
    // existing:
    r.Get("/api-keys", h.AdminAPIKeysList)
    r.Post("/api-keys", h.AdminAPIKeysCreate)
    r.Post("/api-keys/{id}/revoke", h.AdminAPIKeysRevoke)
    // ... weitere existing
})
```

- [ ] **Step 4: Alle existing Admin-Templates `{{ .csrfField }}` in POST-Forms ergänzen**

`frontend/web/templates/admin_api_keys_create.html` etc. — 1-Zeile pro Form.

- [ ] **Step 5: Tests für CSRF (4 Fälle: valid, missing field, wrong token, Authorization-Header skip)**

- [ ] **Step 6: Go test -race grün, Commit `feat(#124): gorilla/csrf + existing Admin-Routes nachgeruestet`**

### Task 7.2: Backend-OpenAPI exportieren + oapi-codegen aktualisieren

**Files:** `backend/openapi.json` (re-generieren) + `frontend/internal/api/<generated>.go`

**Pre-Check:** Backend Tasks 1-6 müssen abgeschlossen sein (neue Endpoints für gen-client verfügbar)

- [ ] **Step 1: Backend OpenAPI-Schema generieren**

```bash
cd backend
# Backend exportiert openapi.json beim Start oder via CLI
python -c "from app.main import create_app; import json; print(json.dumps(create_app().openapi(), indent=2))" > openapi.json
```

- [ ] **Step 2: oapi-codegen für Frontend**

```bash
cd frontend
make gen-client
```

- [ ] **Step 3: Generated client tests bestehen**

```bash
go test ./internal/api/...
```

- [ ] **Step 4: Commit `feat(#124): OpenAPI + oapi-codegen Update fuer Admin-Printers Endpoints`**

### Task 7.3: Go-Handler admin_printers.go

**Files:** `frontend/internal/handlers/admin_printers.go` (neu) + Tests

**Pre-Check:** `phase0-live-state.md` → admin_api_keys.go Pattern-Lektüre

- [ ] **Step 1: 8 Handler analog admin_api_keys.go-Pattern**:
  - AdminPrintersList — `GET /admin/printers/`
  - AdminPrintersNewForm — `GET /admin/printers/new`
  - AdminPrintersCreate — `POST /admin/printers`
  - AdminPrintersEditForm — `GET /admin/printers/{slug}/edit`
  - AdminPrintersUpdate — `POST /admin/printers/{slug}`
  - AdminPrintersDisableConfirm — `GET /admin/printers/{slug}/disable`
  - AdminPrintersDisable — `POST /admin/printers/{slug}/disable`
  - AdminPrintersEnable — `POST /admin/printers/{slug}/enable`

- [ ] **Step 2: Backend-Calls via oapi-codegen Client + Service-Account-Key + X-Remote-User Header**

- [ ] **Step 3: Tests mit httptest (handler-Level + Template-Smoke)**

- [ ] **Step 4: Coverage ≥80% (per go test -coverprofile)**

- [ ] **Step 5: Commit `feat(#124): Frontend admin_printers.go 8 Handler`**

### Task 7.4: Templates + Router-Wireup

**Files:**
- `frontend/web/templates/admin_printers.html` (neu)
- `frontend/web/templates/admin_printers_form.html` (neu)
- `frontend/web/templates/admin_printers_confirm_disable.html` (neu)
- `frontend/cmd/server/main.go` (Router-Updates)

- [ ] Step 1: 3 Templates nach `admin_api_keys.html`-Pattern (Tailwind + HTMX)
- [ ] Step 2: Templates haben `{{ .csrfField }}` in POST-Forms
- [ ] Step 3: Router in main.go `r.Route("/admin/printers", ...)` mit csrfMW
- [ ] Step 4: Integration-Tests grün
- [ ] Step 5: Commit `feat(#124): Frontend Admin-UI Templates + Router-Wireup`

---

## Phase 8 — Production-Deploy

### Task 8.1: PR erstellen + CI grün

- [ ] **Step 1: Push + PR öffnen gegen `main`**

```bash
git push -u origin feat/issue-124-printers-db
gh pr create --base main \
  --title "feat(#124): printers.yaml → DB + Admin-UI + CSRF-Hardening" \
  --body "Closes #124. Spec: docs/superpowers/specs/2026-06-14-printers-yaml-to-db-design.md (Round-6 Working Draft). Plan: docs/superpowers/plans/2026-06-19-printers-yaml-to-db-plan-round5.md."
```

- [ ] **Step 2: CI-Pipeline grün warten**

```bash
gh pr checks --watch
```

### Task 8.2: Pre-Deploy DB-Backup + Watchtower-Pause (LIVE-PFADE)

**Pre-Check:** `phase0-live-state.md` → Mount-Pfade

- [ ] **Step 1: Watchtower-Pause für beide Container**

```python
for container in ["label-printer-hub-backend", "label-printer-hub-frontend"]:
    mcp__dockhand__set_container_auto_update(
        environmentId=10, containerName=container, policy="never",
    )
```

- [ ] **Step 2: SQLite-Backup via docker cp (LIVE-VERIFIZIERTE Pfade!)**

```bash
ssh -i ~/.ssh/id_ed25519_homelab_nodes root@hhdocker03 \
  "mkdir -p /docker/stacks/hangar-print-hub/backups && \
   docker stop label-printer-hub-backend && \
   cp /docker/stacks/hangar-print-hub/data/hub/printer-hub.db \
      /docker/stacks/hangar-print-hub/backups/printer-hub.db.bak-pre-124 && \
   cp /docker/stacks/hangar-print-hub/data/hub/printer-hub.db-wal \
      /docker/stacks/hangar-print-hub/backups/printer-hub.db-wal.bak-pre-124 2>/dev/null || true && \
   cp /docker/stacks/hangar-print-hub/data/hub/printer-hub.db-shm \
      /docker/stacks/hangar-print-hub/backups/printer-hub.db-shm.bak-pre-124 2>/dev/null || true && \
   docker start label-printer-hub-backend"
```

### Task 8.3: PR mergen + Image auto-built + Stack updaten

- [ ] **Step 1: PR review + merge**
- [ ] **Step 2: CI baut neues Image `:dev` mit neuer Revision**
- [ ] **Step 3: Stack mit neuem Image deployen**

```python
mcp__dockhand__deploy_stack(environmentId=10, name="label-printer-hub")
# Oder: pull_image + down/start wenn nötig
```

### Task 8.4: Post-Deploy Smoke-Test (mit LIVE-Pfaden)

- [ ] Backend `GET /healthz` 200
- [ ] DB Backfill verifiziert (`docker exec label-printer-hub-backend python -c "..."` mit live DB-Pfad)
- [ ] Backend `GET /api/v1/admin/printers` mit claude-automation-Header-Auth → 200 + Liste
- [ ] Frontend `https://labels.strausmann.cloud/admin/printers/` Browser-Test (via Playwright oder manual SSO)
  - **Hinweis Pangolin Bug #3099:** Pangolin zeigt evtl Basic-Auth-Dialog statt SSO-Redirect. **Cancel im Dialog → SSO-Flow startet automatisch.** Nicht als Smoke-Fail markieren — bekannter Pangolin-Upstream-Bug, siehe `pangolin-resource-standard.md` R8.
- [ ] Test-Drucker create/disable/enable via UI → Audit-Rows korrekt + redact_secrets greift
- [ ] Hangar PrinterSync verifiziert (sieht nur enabled Drucker)
- [ ] Watchtower wieder auf "any" für beide Container

### Task 8.5: Rollback-Pfad (nur bei Smoke-Fail)

- [ ] `mcp__dockhand__stop_container("label-printer-hub-backend")`
- [ ] DB-Restore: `rm db-wal db-shm; cp .bak ./printer-hub.db`
- [ ] Frontend-Image-Rollback via Dockhand
- [ ] `start_container` + Health-Check

---

## Coverage-Schwellen

| Modul | Schwelle |
|---|---|
| Backend printer_admin_service.py | 85% |
| Backend audit_redaction.py | 80% |
| Backend printer_identity.py | 85% |
| Backend admin_printers_api.py | 80% |
| Backend printers_repo.list_all | 85% |
| Frontend admin_printers.go | 80% |
| Frontend cmd/server CSRF-Wireup | 70% |
| Global Backend fail_under | 80% |

---

## Self-Review

**Spec-Coverage:** Alle Spec-Akzeptanzkriterien (Backend + Frontend) sind in Phasen 1-7 abgedeckt. Phase 8 Deploy verifiziert per Smoke-Test.

**Live-Pfade in Phase 8:** Alle docker-Befehle nutzen `phase0-live-state.md` Pfade (`/docker/stacks/hangar-print-hub/...`, NICHT `/docker/stacks/label/...`).

**Spec-Live-Konflikt-Pattern:** Jede Phase hat einen Pre-Check-Step der relevante Werte aus `phase0-live-state.md` zieht. Bei Konflikt mit Spec gewinnt Live.

**Bootstrap-Henne-Ei:** Phase 6.0 nutzt SSH-Direktaufruf in den Backend-Container (kein Pangolin-curl-Pfad) — robuster.

**CSRF-Key-Format:** 64-Hex-Zeichen-String, hex.DecodeString → 32 raw bytes für gorilla/csrf. Validation in Phase 7.1 Step 2 prüft 64-Zeichen + DecodeString-Erfolg.

---

## Execution Handoff

**Plan complete und committed.**

Implementer-Optionen:
1. **Subagent-Driven Development** — fresh Subagent pro Task, Spec-Reviewer + Code-Quality-Reviewer Stages
2. **Inline-Execution** via `superpowers:executing-plans` — Batch mit Checkpoints

Welcher Ansatz?
