# Hub Printers YAML → DB + Admin-UI Design

> **Status:** WORKING DRAFT (Round-6 mit known issues) — Plan-Strategie übernimmt Live-Verifikation
>
> **WICHTIG für Implementer:** Diese Spec hat dokumentierte known issues (siehe Anhang "Known Issues für Plan-Live-Verifikation" am Ende). **Spec-Werte sind Vorschläge — Live-Container-Werte sind die Wahrheit.** Der Implementation-Plan ist so konzipiert dass jede Phase mit einem Pre-Check-Step startet der Production-Werte aus dem laufenden Container zieht (Mount-Pfade, API-URLs, Volumes). Wenn ein Spec-Wert mit Live-Container kollidiert: Live-Container gewinnt.
> **Issue:** [#124 — printers.yaml entfernen, Drucker in DB + Admin-UI](https://github.com/strausmann/Label-Printer-Hub/issues/124)
> **PR:** [#125](https://github.com/strausmann/Label-Printer-Hub/pull/125)
> **Related:** Hangar #110 (hardcoded Drucker-/Möbel-Spezifika entfernen)
> **Datum:** 2026-06-14
> **Autor:** Brainstorming-Session mit @strausmann (2026-06-14)
> **Reviews adressiert:**
> - Round-1: ops, network, storage, code-quality (alle 4 NEEDS_FIXES)
> - Round-2: ops APPROVE, network/storage/code-quality NEEDS_FIXES (3 HIGH + 4 MED + 4 LOW)
> - Round-3: ops/network/storage APPROVE, code-quality NEEDS_FIXES (2 MED + 1 LOW: M11 LabelHubException, M12 Flattening, Engine-Snippet)
> - Round-4: alle 4 Teams APPROVE
> - **Round-5: Live-State-Reset auf approved Round-4-Spec angewandt (Two-Container-Architektur)**

## Round-5 — Live-State-Reset (2026-06-19)

Nach 4 Round-Approvals der Spec hat die Implementation-Vorbereitung (Plan-Phase 0 Live-Check) fundamentale Live-State-Diskrepanzen aufgedeckt. **Der Kern der Spec (YAML→DB Migration) bleibt korrekt.** Geändert wird ausschließlich der Live-State-Kontext (Stack-Name, Container, Domain, Admin-UI-Layer).

### Production Live-State (Hub Image revision `2ff51d2c`, Branch `main`, verifiziert 2026-06-19)

| Spec Round-1-4 Annahme | Production Live-State | Round-5 Anpassung |
|---|---|---|
| Single-Container `print-hub-1` | **Two-Container:** `label-printer-hub-backend` (Python/FastAPI, Port 8000) + `label-printer-hub-frontend` (Go + chi + html/template + HTMX, Port 8080) | Backend bleibt JSON-only, Admin-UI verschiebt sich ins Frontend |
| Stack `hangar-print-hub` | Stack `label-printer-hub` (Pfad `/docker/stacks/label-printer-hub/`) | Stack-Pfad anpassen |
| Domain `print-hub.example.test` | Domain `labels.example.test` (Pangolin Resource `resourceId: 123`, `niceId: label-printer-hub`) | URL anpassen |
| Pangolin-Resource muss erstellt werden | Resource **existiert bereits vollständig** mit `headerAuthId: 8`, `sso: true`, `x-pangolin-token`-Trust-Header | Phase 0 verifiziert Bestand statt Resource neu zu erstellen |
| printers.yaml-Pfad `/etc/printer-hub/printers.yaml` | Production-Pfad **`/etc/hub/printers.yaml`** (verifiziert via `docker exec label-printer-hub-backend env`) | Pfad korrigieren |
| Watchtower-Pause für 1 Container | Watchtower-Pause für **beide** Container (backend + frontend) | Phase 8 anpassen |
| Backend serviert HTML-Routes `/admin/printers/` mit Jinja2 + CSRF | **Backend serviert nur JSON.** HTML-Templates leben im **Frontend (Go)** unter `frontend/web/templates/`. Pattern verifiziert: `admin_api_keys.html` + `frontend/internal/handlers/admin_api_keys.go` existieren auf `main`. | Phase 3 wird Go-Frontend-Tasks: `admin_printers.go` Handler + 3 `admin_printers*.html` Templates analog API-Keys-Pattern |
| CSRF-Middleware im Backend (Starlette-CSRF) | Backend hat KEIN HTML → braucht keine CSRF-Middleware. Frontend (Go) hat eigenen CSRF-Stack (`gorilla/csrf` o.ä. — Pattern aus existierenden Admin-Routes übernehmen) | CSRF-Tasks komplett ins Frontend verschieben |

### Production-Auth-Flow (verifiziert)

```
Browser
  → Pangolin labels.example.test (resourceId 123, SSO + Header-Auth-Bypass via headerAuthId 8)
  → Frontend (label-printer-hub-frontend:8080, Go/chi)
    → Liest Remote-User, X-Pangolin-Token aus Request
    → Reverse-Proxy für /api/*
    → HTML-Templates für /, /printers/{id}, /jobs, /templates, /lookup, /admin/api-keys/
  → Backend (label-printer-hub-backend:8000, FastAPI)
    → JSON-API only
    → Akzeptiert Service-Account-API-Key vom Frontend
    → Akzeptiert Pangolin-SSO-Headers (Remote-User, X-Pangolin-Token-Trust)
```

### Auth-Konzept für /admin/printers (Round-5)

- **Browser → Frontend:** Pangolin SSO (Remote-User + X-Pangolin-Token), Frontend-CSRF für POST-Forms.
- **Frontend → Backend:** Service-Account-API-Key (Backend's existing `admin_api_keys` System) als `Authorization: Bearer` plus `X-Remote-User` Header mit dem Browser-User (für `updated_by` im Audit).
- **Direct API-Tooling → Backend:** Pangolin Header-Auth-Bypass (`claude-automation`-Credentials aus `headerAuthId 8`-Vault-Item) ODER direkter Backend-API-Key.

### Round-5 Findings Verarbeitung

| Round-5 Aspekt | Status | Wo adressiert |
|---|---|---|
| Stack-Pfad `label-printer-hub` | ✅ Sektion "Production Live-State" + Migration-Sektion |
| Container `label-printer-hub-backend` / `-frontend` | ✅ Architektur-Diagramm Round-5 unten + Migration |
| Domain `labels.example.test` | ✅ Architektur-Diagramm + Authentifizierung |
| `printers.yaml` Pfad `/etc/hub/printers.yaml` | ✅ Migration Phase 2 |
| Pangolin Resource 123 bereits konfiguriert | ✅ Phase 6.1 wird Verifikation statt Anlage; Phase 6.2 ergänzt nur fehlende Labels |
| Backend bleibt JSON-only | ✅ HTML-Routes-Sektion aus Round-4 wird in Round-5 ins Frontend verschoben |
| Frontend (Go) bekommt `admin_printers.go` + 3 Templates | ✅ Neue Sektion "Frontend (Go) Round-5" |
| Backend CSRF-Middleware ENTFÄLLT | ✅ CSRF-Tasks aus Plan-Phase 3 in Plan-Phase 3-Frontend verschieben |
| Watchtower-Pause für beide Container | ✅ Migration Phase A.2 |
| Branch-Strategie | ✅ Working-Branch von `origin/main` (Production) statt `main`-Fork |

### Round-5 Konzept-Korrektur — Architektur-Diagramm

```
                  ┌──────────────────────────────────────┐
                  │ Operator (Browser)                   │
                  │   labels.example.test            │
                  └──────────────┬───────────────────────┘
                                 │ HTTPS
                  ┌──────────────▼───────────────────────┐
                  │ Pangolin Edge (resourceId 123)       │
                  │   SSO: Remote-User                   │
                  │   X-Pangolin-Token Trust-Header      │
                  │   Header-Auth-Bypass: headerAuthId 8 │
                  └──────────────┬───────────────────────┘
                                 │
                  ┌──────────────▼───────────────────────┐
                  │ Frontend                             │
                  │   label-printer-hub-frontend:8080    │
                  │   Go 1.24 + chi v5 + html/template   │
                  │   + HTMX + Tailwind                  │
                  │                                      │
                  │   NEUE HTML-Routes (Issue #124):     │
                  │     GET  /admin/printers/            │
                  │     GET  /admin/printers/new         │
                  │     POST /admin/printers             │
                  │     GET  /admin/printers/{slug}/edit │
                  │     POST /admin/printers/{slug}      │
                  │     GET  /admin/printers/{slug}/disable │
                  │     POST /admin/printers/{slug}/disable │
                  │     POST /admin/printers/{slug}/enable  │
                  │                                      │
                  │   NEUE Templates (frontend/web/templates/): │
                  │     admin_printers.html              │
                  │     admin_printers_form.html         │
                  │     admin_printers_confirm_disable.html │
                  │                                      │
                  │   NEUE Go-Handler (frontend/internal/handlers/): │
                  │     admin_printers.go (analog admin_api_keys.go) │
                  │   CSRF: gorilla/csrf-Wrapper analog existing Admin-Routes │
                  └──────────────┬───────────────────────┘
                                 │ HTTP intern (BACKEND_URL=http://backend:8000)
                                 │ Authorization: Bearer <service-account-key>
                                 │ X-Remote-User: <browser-sso-user>
                  ┌──────────────▼───────────────────────┐
                  │ Backend                              │
                  │   label-printer-hub-backend:8000     │
                  │   Python 3.12 + FastAPI              │
                  │   JSON-ONLY (kein HTML, kein CSRF)   │
                  │                                      │
                  │   Existing Endpoints unverändert:    │
                  │     GET /api/printers (NEUER FILTER) │
                  │     /api/printers/{id}/{status,...}  │
                  │     /api/admin/api-keys/...          │
                  │                                      │
                  │   NEUE JSON-API (Issue #124):        │
                  │     GET    /api/v1/admin/printers    │
                  │     POST   /api/v1/admin/printers    │
                  │     GET    /api/v1/admin/printers/{slug}│
                  │     PUT    /api/v1/admin/printers/{slug}│
                  │     POST   /api/v1/admin/printers/{slug}/disable│
                  │     POST   /api/v1/admin/printers/{slug}/enable │
                  │                                      │
                  │   `updated_by`-Quelle: X-Remote-User │
                  │   (gesetzt vom Frontend), Fallback   │
                  │   auf Auth-Subject (API-Key Owner)   │
                  └──────────────┬───────────────────────┘
                                 │
                  ┌──────────────▼───────────────────────┐
                  │ SQLite /data/printer-hub.db (WAL)    │
                  │   printers       (erweitert)         │
                  │   printers_audit (neu)               │
                  └──────────────────────────────────────┘
```

### Was unverändert aus Round-4 bleibt

Der gesamte technische Kern bleibt valid:
- PrinterAdminService + CRUD + Soft-Delete
- Pydantic-Schemas mit verschachteltem SNMP
- Audit-Tabelle + Redaction (`audit_redaction.py`)
- `derive_printer_id` 4-arg mit timezone-aware created_at_utc
- PrinterDisabledError aus PrinterError abgeleitet, 409-Mapping
- Alembic-Migration: Schema-Erweiterung + Backfill
- SQLite SERIALIZABLE + WAL Engine-Setup
- Flattening-Helper `_payload_to_row` / `_apply_update_patch` / `_row_to_audit_view`
- `GET /api/printers` enabled-Filter
- 5 Test-Files Removal

### Was sich konkret ändert (Sub-Verweise auf Sektionen unten)

1. **Sektion "Authentifizierung":** Stack-Name + Domain + Container-Namen korrigiert, CSRF-Mechanismus verschoben ins Frontend.
2. **Sektion "Architektur":** ASCII-Diagramm wird durch obiges Round-5-Diagramm ersetzt (s.o.).
3. **Sektion "Web-Routes (HTML)" + "Templates":** verschoben in neuen Frontend-Abschnitt (siehe unten).
4. **Sektion "Migration für Bestand":** Stack-Name `label-printer-hub`, Container-Name `label-printer-hub-backend`, printers.yaml-Pfad `/etc/hub/printers.yaml`, Watchtower-Pause für beide Container.
5. **Sektion "Pangolin-Resource":** Phase 6.1 Vault-Item-Verifikation statt Neuanlage; Phase 6.2 ergänzt nur fehlende Labels (Healthcheck.hostname wenn nicht gesetzt).
6. **Sektion "Akzeptanzkriterien":** ergänzt um Frontend-Tasks, Backend-HTML-Tasks entfallen.

### Frontend (Go) Round-5 — Neue Komponenten

Pattern verifiziert anhand `frontend/internal/handlers/admin_api_keys.go` auf Branch `main`:

**Dateien (neu):**

- `frontend/internal/handlers/admin_printers.go` — 8 Handler analog AdminAPIKeysList/Create/Detail
- `frontend/web/templates/admin_printers.html` — Liste-Template (Pattern: `admin_api_keys.html`)
- `frontend/web/templates/admin_printers_form.html` — Create/Edit-Form (Pattern: `admin_api_keys_create.html`)
- `frontend/web/templates/admin_printers_confirm_disable.html` — Disable-Confirm-Page
- `frontend/internal/handlers/admin_printers_test.go` — Go-Tests mit `httptest`

**Routing in `cmd/server/main.go`:**

```go
r.Route("/admin/printers", func(r chi.Router) {
    r.Use(csrfMW)                                    // existing CSRF-Middleware
    r.Get("/", h.AdminPrintersList)
    r.Get("/new", h.AdminPrintersNewForm)
    r.Post("/", h.AdminPrintersCreate)
    r.Get("/{slug}/edit", h.AdminPrintersEditForm)
    r.Post("/{slug}", h.AdminPrintersUpdate)
    r.Get("/{slug}/disable", h.AdminPrintersDisableConfirm)
    r.Post("/{slug}/disable", h.AdminPrintersDisable)
    r.Post("/{slug}/enable", h.AdminPrintersEnable)
})
```

**oapi-codegen Re-Generation:**

Backend exportiert `openapi.json`. Nach Backend-Implementation der neuen `/api/v1/admin/printers` Endpoints muss Frontend `make gen-client` ausführen damit der typed Go-Client die neuen Methoden enthält. Implementer-Reihenfolge: **Backend zuerst**, dann Frontend.

**Frontend → Backend Auth:**

```go
// frontend/internal/handlers/admin_printers.go
req.Header.Set("Authorization", "Bearer " + h.config.BackendServiceAccountKey)
req.Header.Set("X-Remote-User", remoteUser) // aus Pangolin Remote-User Header
```

`BackendServiceAccountKey` ist eine neue Env-Variable im Frontend-Container — Wert ist ein Admin-Scope-API-Key aus dem Backend's `admin_api_keys` System. Setup in Phase 6.0.

### Branch-Strategie Round-5

- **Working-Branch von `origin/main`** ausgehend (nicht `feat/first-print` — das ist ein Skeleton-Branch ohne Bezug zu Production).
- **Branch-Name:** `feat/issue-124-printers-yaml-to-db` (von `main` aus geforked).
- **PR-Strategie:** Nach Round-5-Approval neuen PR gegen `main`. PR #125 (mit Spec/Plan-Commits) bleibt bestehen oder wird gemerged-into-main, je nach Workflow-Wunsch.

### Akzeptanzkriterien-Diff Round-5

**Backend-Bezug:**
- "Backend bleibt JSON-only" — keine HTML-Routes, keine Jinja2-Templates, keine CSRF-Middleware
- Backend exportiert aktualisiertes `openapi.json` mit den 6 neuen Admin-Endpoints

**Frontend-Bezug (NEU):**
- 3 Templates erstellt (`admin_printers.html`, `admin_printers_form.html`, `admin_printers_confirm_disable.html`)
- 8 Go-Handler in `admin_printers.go` (Pattern: `admin_api_keys.go`)
- Chi-Router-Routes für `/admin/printers/*` registriert mit existing CSRF-Middleware
- `make gen-client` aktualisiert oapi-codegen-Client nach Backend-Update
- Go-Tests: Handler + Template-Smoke-Tests, Coverage ≥80%

**Live-State-Bezug (NEU):**
- Working-Branch von `origin/main` (Branch-Verifikation Phase 0)
- Stack `label-printer-hub`, Container `label-printer-hub-backend` + `label-printer-hub-frontend`
- Domain `labels.example.test`
- `/etc/hub/printers.yaml` Pfad (NICHT `/etc/printer-hub/printers.yaml`)
- Pangolin Resource 123 (`niceId: label-printer-hub`) — Bestand-Verifikation, kein Neu-Anlegen
- `headerAuthId 8` — Vault-Item-Name verifizieren, ggf. zu `Pangolin Header Auth - Label Printer Hub` umbenennen
- Watchtower-Pause für BEIDE Container (backend + frontend) vor Deploy

### Auswirkung auf Plan

Der Plan (Round-4 final) muss in Round-5 angepasst werden:
- **Phase 3 (Backend HTML-Routes + Templates)** → **gestrichen**, ersetzt durch neue **Phase 3-Frontend (Go-Handler + Templates + Routing)**
- **Task 3.1 CSRF-Middleware** → **ins Frontend verschoben** (siehe Round-6-Sektion: CSRF muss aktiv im Frontend eingeführt werden, NICHT existing)
- **Phase 8** angepasst für Stack-Namen + beide Container Watchtower-Pause
- **Akzeptanzkriterien-Liste** auf 24+ Punkte erweitert (Backend bleibt; Frontend kommt dazu)

Plan-Round-5 wird nach Spec-Round-5-Approval geschrieben.

---

## Round-6 — Review-Findings adressiert (2026-06-19 abends)

Round-5-Reviews: ops APPROVE, network APPROVE, storage NEEDS_FIXES (2 HIGH + 1 LOW), code-quality NEEDS_FIXES (1 HIGH + 2 MED + 1 LOW).

### Round-6 Findings-Mapping

| # | Severity | Team | Finding | Status | Wo adressiert |
|---|---|---|---|---|---|
| H1 | HIGH | storage | Alte Sektionen (Phase 1a/2/3) nutzen `hangar-print-hub-print-hub-1` und Stack `hangar-print-hub` | ✅ Globalreplace + Round-6-Hinweise | Migration-Sektion |
| H2 | HIGH | storage | `sqlite3` CLI fehlt im Production-Container — Backup-Befehl bricht | ✅ Backup via `docker cp` vom Host | Migration Phase A.1 |
| H3 | HIGH | code-q | CSRF-Stack existiert NICHT im Frontend (`go.mod` hat keine CSRF-Library) — existing Admin-API-Keys-Routes sind ungeschützt | ✅ `gorilla/csrf` einführen + existing Admin-Routes nachrüsten | Neue Sektion "Frontend CSRF-Hardening" |
| M1 | MED | code-q | Round-4-Sektionen (Web-Routes, CSRF-Middleware, Coverage) nicht explizit invalidiert | ✅ Inline-⚠-Markierungen | Diverse Round-4-Sektionen |
| M2 | MED | code-q | `BackendServiceAccountKey` Bootstrap fehlt — Henne-Ei-Problem | ✅ Phase 6.0 Service-Account-Key-Bootstrap | Migration Phase 6.0 |
| L1 | LOW | network | Vault-Notes "Site 4" statt "Site 6" | ✅ als Fix-Hinweis | Anhang Round-6 |
| L2 | LOW | code-q | Coverage-Tabelle hat obsolete Backend-Python-Pfade | ✅ in Round-4-Sektion markiert + neue Coverage-Tabelle | Coverage-Tabelle Round-6 |
| L3 | LOW | storage | Host-Pfad der DB nicht explizit | ✅ ergänzt | Migration Phase A.1 |

### Round-6 Migration-Sektion (überschreibt Round-1 bis Round-4)

**Phase A.0 — Container-Namen-Reset (gegenüber Round-1 bis Round-4):**

Alle Container/Stack-Referenzen in den Round-1 bis Round-4-Sektionen sind ÜBERSCHRIEBEN:

| Round-1-4 (veraltet) | Round-5/6 aktuell |
|---|---|
| Stack `hangar-print-hub` | Stack `label-printer-hub` |
| Container `hangar-print-hub-print-hub-1` | Container `label-printer-hub-backend` |
| (implizit) Frontend-Container | `label-printer-hub-frontend` |
| Host-Pfad `/docker/stacks/hangar-print-hub/...` | Host-Pfad `/docker/stacks/label-printer-hub/...` |
| DB Host-Pfad | `/docker/stacks/label/label-printer-hub/data/printer-hub.db` |
| `mcp__dockhand__set_container_auto_update(env, "hangar-print-hub-print-hub-1", ...)` | `mcp__dockhand__set_container_auto_update(env, "label-printer-hub-backend", policy="never")` + ein weiterer Aufruf für `label-printer-hub-frontend` |

Implementer-Verantwortung: bei JEDEM `docker exec` / `docker cp` / `mcp__dockhand__*`-Aufruf den Round-5/6-Container-Namen verwenden, NICHT die Round-1-4-Namen.

**Phase A.1 — Pre-Deploy DB-Backup via docker cp (H2-Round-5-Fix):**

Der Production-Container hat **kein `sqlite3` CLI**. Backup muss via `docker cp` direkt vom Host laufen — das ist WAL-safe wenn die DB-Datei im konsistenten Snapshot-Zustand gelesen wird (SQLite WAL-Mode garantiert das wenn keine Schreibvorgänge mitten in der Kopie laufen):

```bash
# Schritt 1: kurze App-Pause für saubere Kopie (Container down stoppt Schreibvorgänge)
mcp__dockhand__stop_container(environmentId=10, name="label-printer-hub-backend")

# Schritt 2: WAL-Checkpoint via Python (falls sqlite3-Modul im Container vorhanden)
# Alternativ: Container ist gestoppt → kein WAL-Replay nötig

# Schritt 3: DB-Datei + WAL + SHM auf Host kopieren (alle 3 für sauberen Restore)
⚠ **OBSOLET in Round-6:** dieser Backup-Block nutzt den falschen Pfad `/docker/stacks/label/...` aus Round-1-4. Aktueller Live-Pfad ist `/docker/stacks/hangar-print-hub/data/hub/` (siehe Round-6 Migration Phase A.1 + Known-Issues-Tabelle). NICHT diesen Block kopieren!
ssh -i ~/.ssh/id_ed25519_placeholder root@prod-node.example.test \
  "cp /docker/stacks/label/label-printer-hub/data/printer-hub.db \
      /docker/stacks/label/label-printer-hub/backups/printer-hub.db.bak-pre-124 && \
   cp /docker/stacks/label/label-printer-hub/data/printer-hub.db-wal \
      /docker/stacks/label/label-printer-hub/backups/printer-hub.db-wal.bak-pre-124 2>/dev/null || true && \
   cp /docker/stacks/label/label-printer-hub/data/printer-hub.db-shm \
      /docker/stacks/label/label-printer-hub/backups/printer-hub.db-shm.bak-pre-124 2>/dev/null || true"

# Schritt 4: Container wieder starten
mcp__dockhand__start_container(environmentId=10, name="label-printer-hub-backend")
```

Restore-Pfad analog: WAL/SHM löschen, .db-Datei restore, Container neu starten.

**Phase A.2 — Watchtower-Pause für BEIDE Container (Round-5):**

```python
for container in ["label-printer-hub-backend", "label-printer-hub-frontend"]:
    mcp__dockhand__set_container_auto_update(
        environmentId=10, containerName=container, policy="never",
    )
```

### Round-6 Frontend CSRF-Hardening (H3 — eingerollt in Issue #124)

**Befund (Round-5 code-quality, verifiziert):** Das Frontend hat **keine CSRF-Library** in `frontend/go.mod` (kein `gorilla/csrf`, kein `justinas/nosurf`). Die existing Admin-Routes (`/admin/api-keys/*`) sind **ungeschützt für CSRF**. Das ist eine Security-Lücke unabhängig von Issue #124, wird aber im selben Issue mit-adressiert (User-Entscheidung 2026-06-19).

**Lösung:**

1. **Library:** `github.com/gorilla/csrf` (Standard Go-Lib, weit verbreitet, gut gewartet)
2. **go.mod-Update:** `go get github.com/gorilla/csrf` ergänzt Dependency
3. **CSRF-Middleware-Setup in `cmd/server/main.go`:**

```go
import "github.com/gorilla/csrf"

// In main():
csrfKey := []byte(os.Getenv("CSRF_KEY"))  // 32-byte hex-string, neu in Frontend-ENV
if len(csrfKey) != 64 { // 32 raw bytes = 64 hex chars
    log.Fatal("CSRF_KEY env-var must be 32 bytes")
}
csrfMW := csrf.Protect(
    csrfKey,
    csrf.Secure(true),         // HTTPS-only
    csrf.SameSite(csrf.SameSiteStrictMode),
    csrf.CookieName("__Host-csrf"),
    csrf.RequestHeader("X-CSRF-Token"),
    csrf.FieldName("csrf_token"),
)

// Anwenden auf Admin-Routes (NEU + EXISTING):
r.Route("/admin", func(r chi.Router) {
    r.Use(csrfMW)
    // EXISTING (Round-6 nachgerüstet):
    r.Get("/api-keys", h.AdminAPIKeysList)
    r.Post("/api-keys", h.AdminAPIKeysCreate)
    r.Post("/api-keys/{id}/revoke", h.AdminAPIKeysRevoke)
    // ... weitere existing admin-routes mit Mutations
    // NEU für Issue #124:
    r.Route("/printers", func(r chi.Router) {
        r.Get("/", h.AdminPrintersList)
        r.Get("/new", h.AdminPrintersNewForm)
        r.Post("/", h.AdminPrintersCreate)
        // ... weitere
    })
})
```

4. **Template-Update:** ALLE existing Admin-Templates (`admin_api_keys*.html`) bekommen `{{ .csrfField }}` in ihre POST-Forms. Das ist ein 1-Zeilen-Update pro Template.

5. **CSRF_KEY-Bootstrap:** Phase 6.0 (siehe nächste Sektion) generiert + verteilt das Secret.

### Phase 6.0 — Service-Account-Key + CSRF_KEY Bootstrap (M2-Round-5 + H3-Round-5)

**Henne-Ei-Problem:** Frontend braucht Backend-API-Key um `/api/v1/admin/printers` aufzurufen. Backend-API-Key wird im Backend's existing `admin_api_keys`-System verwaltet — das wiederum braucht Admin-UI zum Erstellen. Lösung: einmaliger Bootstrap via Backend-CLI / direkten Backend-Aufruf.

**Schritte:**

1. **API-Key im Backend erstellen** (existing `/api/v1/admin/api-keys` POST):

```bash
# Per Pangolin Header-Auth-Bypass (claude-automation)
curl -X POST https://labels.example.test/api/v1/admin/api-keys \
  -u "claude-automation:$(mcp__vaultwarden__get object=password id='Pangolin Header Auth - Label Printer Hub')" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "frontend-service-account",
    "scopes": ["admin:printers", "admin:read"],
    "rate_limit_per_minute": 600
  }'
# → Response enthält plaintext-Key (einmal sichtbar)
```

2. **Plaintext-Key in Vaultwarden speichern:**

```
mcp__vaultwarden__create_item(
  name="Hub Frontend Service-Account API-Key",
  type=1,
  login={
    "username": "frontend-service-account",
    "password": "<plaintext-aus-step-1>"
  },
  notes="Backend-API-Key für Hub-Frontend → Backend Service-Account-Auth (Issue #124). Scope: admin:printers"
)
```

3. **CSRF-Key generieren + speichern:**

```bash
openssl rand -hex 32
# → 64-hex-Zeichen-Secret
```

```
mcp__vaultwarden__create_item(
  name="Hub Frontend CSRF Key",
  type=1,
  login={ "password": "<secret-aus-rand>" },
  notes="32-byte CSRF-Secret für Frontend gorilla/csrf (Issue #124)"
)
```

4. **Stack-Env-Variablen ergänzen (Round-5/6 Stack-Env-Merge):**

```python
existing = mcp__dockhand__get_stack_env(environmentId=10, name="label-printer-hub")
existing_vars = list(existing["variables"])
existing_vars.append({
    "key": "BACKEND_SERVICE_ACCOUNT_KEY",
    "value": "<plaintext-aus-step-1>",
    "isSecret": True,
})
existing_vars.append({
    "key": "CSRF_KEY",
    "value": "<secret-aus-step-3>",
    "isSecret": True,
})
mcp__dockhand__update_stack_env(
    environmentId=10, name="label-printer-hub", variables=existing_vars,
)
```

5. **Compose-Update:** Frontend-Container bekommt `BACKEND_SERVICE_ACCOUNT_KEY` + `CSRF_KEY` in seine `env_file`. Compose nutzt schon `env_file: .env` → die neuen Env-Vars werden vererbt sobald sie in der Stack-Env-Tabelle sind.

### Round-4-Sektion-Invalidierungen (M1)

Folgende Round-4-Sektionen sind in Round-5/6 OBSOLET und werden durch die Round-5/6-Sektionen oben überschrieben:

⚠ **OBSOLET in Round-6:** "Web-Routes (HTML)" — HTML-Routes leben im Frontend (Go), nicht im Backend (Python).
⚠ **OBSOLET in Round-6:** "CSRF-Middleware H3 (Backend)" — Backend hat kein HTML, braucht keine CSRF. Frontend bekommt `gorilla/csrf`.
⚠ **OBSOLET in Round-6:** Coverage-Schwellen für `app/api/routes/admin_printers_web.py`, `app/middleware/csrf.py`, `app/templates/admin_printers/*` — diese Module entstehen nicht im Backend.
⚠ **OBSOLET in Round-6:** Akzeptanzkriterien betreffend Backend-HTML-Routes, Backend-CSRF, Backend-Templates.

Implementer liest die Round-1-4-Sektionen NUR als Referenz für den Service-Layer (PrinterAdminService, audit_redaction, Pydantic-Schemas, Alembic-Migration, derive_printer_id) — diese Teile bleiben unverändert valid.

### Coverage-Tabelle Round-6 (ersetzt Round-4-Coverage-Tabelle)

| Modul | Schwelle | Bemerkung |
|---|---|---|
| **Backend:** `app/services/printer_admin_service.py` | 85 % | Mutation-Logic |
| **Backend:** `app/services/printer_model_registry.py` | 75 % | Pure-Helper |
| **Backend:** `app/services/printer_identity.py` | 85 % | Mutation (UUIDv5-Derivation) |
| **Backend:** `app/services/audit_redaction.py` | 80 % | Secret-Handling |
| **Backend:** `app/api/routes/admin_printers_api.py` | 80 % | JSON-API-Endpunkte |
| **Backend:** `app/repositories/printers.py` (enabled-Filter) | 85 % | Mutation/Filter |
| **Frontend:** `frontend/internal/handlers/admin_printers.go` | 80 % | Handler + Template-Smoke (Pattern: admin_api_keys.go) |
| **Frontend:** `frontend/cmd/server/main.go` (CSRF-Wire-Up) | 70 % | Integration + Middleware-Test |
| Global Backend `fail_under=80` | 80 % | pytest-cov gate |
| Global Frontend (Go test -race + cover) | ≥80 % | go test -coverprofile + gocov |

### Anhang — Known Issues für Plan-Live-Verifikation (2026-06-19)

Nach 6 Spec-Review-Runden wurde entschieden die Iteration zu beenden und stattdessen den **Plan robust gegen Spec-Annahmen-Fehler** zu machen. Folgende Werte sind live verifiziert und überschreiben falsche Spec-Stellen:

| Spec-Annahme (möglicherweise falsch) | Live-verifizierte Wahrheit (2026-06-19) | Verifizierung |
|---|---|---|
| DB-Host-Pfad `/docker/stacks/label/label-printer-hub/data/printer-hub.db` | **`/docker/stacks/hangar-print-hub/data/hub/printer-hub.db`** | `docker inspect label-printer-hub-backend --format '{{range .Mounts}}{{.Source}}→{{.Destination}}{{println}}{{end}}'` |
| printers.yaml-Host-Pfad | **`/docker/stacks/hangar-print-hub/config/printers.yaml`** | dito |
| Mount-Map | `/docker/stacks/hangar-print-hub/data/hub → /data` + `/docker/stacks/hangar-print-hub/config/printers.yaml → /etc/hub/printers.yaml` | dito |
| Backend-API-Prefix `/api/v1/admin/api-keys` | **`/api/admin/api-keys`** (KEIN v1-Prefix) | `git show origin/main:backend/app/api/routes/admin_api_keys.py \| grep prefix=` |
| CSRF_KEY-Format "32-byte hex-string" | **Korrekt: `openssl rand -hex 32` gibt 64-Hex-Zeichen-String = 64 UTF-8-Bytes.** Validation muss `len(key) == 64` (Hex-Form) ODER `len(hex.Decode(key)) == 32` (Raw-Bytes-Form) prüfen. | siehe Plan-Phase 6.0 |
| Bootstrap-curl via Pangolin Header-Auth-Bypass | **Funktioniert evtl nicht durch:** Backend's `/api/admin/api-keys` Auth-Pfad muss live verifiziert werden bevor curl-Bootstrap. Alternative: SSH-Direktaufruf auf prod-node.example.test ins Backend-Container | siehe Plan-Phase 6.0 |
| Stack-Name "label-printer-hub" als Watchtower-Scope | **Watchtower-Scope-Label ist `hangar-print-hub`** (vermutlich historisch) — Watchtower-Pause muss nach `containerName` filtern, nicht nach Scope | `docker inspect ... Config.Labels.com.centurylinklabs.watchtower.scope` |
| Vault-Item-Collection für Phase 6.0 Items | **`Automation/Claude-Team`** (analog Pangolin-Resource-Standard) | pangolin-resource-standard.md |
| Vault-Notes für headerAuthId 8 zeigt "Site 4" | **Soll "Site 6" (HHDOCKER03)** sein | network-Review Round-5 |
| `env_file: .env` + Dockhand Stack-Env | Stack-Env-Variablen kommen via Docker-ENV in Container an, **NICHT** automatisch in .env-Datei. Implementer muss mit `down_stack`/`start_stack` nach Env-Änderung neu starten | network-Review Round-6 |

### Anhang Round-6 — LOWs

**L1 (network):** Vault-Item "Pangolin Header Auth - Label Printer Hub" Notes-Feld zeigt "Site 4 (HHDOCKER02)" statt korrekt "Site 6 (HHDOCKER03)". Datenpunkt-Korrektur über Vaultwarden — kein Issue-#124-Block. Fix-Hinweis als Implementer-Sub-Task in Phase 0.

**L2 (code-q):** Coverage-Tabelle Round-4 enthält obsolete Backend-Python-Pfade. Wurde mit neuer Coverage-Tabelle Round-6 oben ersetzt.

**L3 (storage):** Host-Pfad der DB jetzt explizit dokumentiert: `/docker/stacks/hangar-print-hub/data/hub/printer-hub.db` (live-verifiziert via docker inspect; das per `${STACKS_BASE_HOMEDIR}` abgeleitete `/docker/stacks/label/...` aus der `.env` stimmt NICHT mit dem aktuellen Volume-Mount überein).

---

## Original Spec Round-1 bis Round-4 (Kern bleibt valid, HTML/CSRF-Sektionen OBSOLET)

---

## Original Spec Round-1 bis Round-4 (Kern bleibt valid)



## Round-2-Findings Verarbeitung (NEU)

| Finding | Severity | Status | Wo adressiert |
|---|---|---|---|
| H7 Healthcheck-Labels im Blueprint fehlen | HIGH | ✅ ergänzt | Sektion "Authentifizierung" Blueprint-Snippet |
| H8a SNMP-Schema flach vs verschachtelt | HIGH | ✅ entschieden: **verschachtelt** | Sektion "Pydantic-Schemas" |
| H8b Bestand-DB fehlen SNMP/queue/cut_defaults | HIGH | ✅ entschieden: **Alembic-Backfill** | Sektion "Migration für Bestand" Phase 1b |
| H9 2 weitere Test-Files übersehen | HIGH | ✅ ergänzt | Sektion "Migration für Bestand" + "ID-Generierung" |
| M7 BEGIN IMMEDIATE vs session.begin() | MED | ✅ konkrete Strategie | Sektion "Data Flow" |
| M8 PrintService.submit_print_job enabled-Check | MED | ✅ explizit | Sektion "Implikationen für Hangar+PrintService" |
| M9 redact_secrets Modul-Pfad | MED | ✅ `app/services/audit_redaction.py` | Sektion "Komponenten" |
| M10 Container-DNS-Name `print-hub` Live-Verifikation | MED | ✅ Smoke-Step | Sektion "Migration für Bestand" Phase 3 |
| L Pangolin-Resource-Standard Vault-Item-Naming | LOW | ✅ verlinkt | Sektion "Authentifizierung" |
| L Pangolin Bug #3099 (Basic-Auth-Dialog) | LOW | ✅ als bekanntes Phänomen | Sektion "Risiken" |
| L CSRF-Test-Strategie 4 Fälle | LOW | ✅ konkretisiert | Sektion "Testing" |
| L Trailing-Slash-Konvention | LOW | ✅ ohne Slash | Sektion "JSON-API" |

## Round-1-Findings Verarbeitung

| Finding | Severity | Status | Wo adressiert |
|---|---|---|---|
| C1 Pangolin Remote-User Header-Name | CRITICAL | ✅ fixed | Sektion "Authentifizierung" |
| C2 JSON-API Auth-Pfad | CRITICAL | ✅ entschieden: selbe Pangolin-Resource | Sektion "Authentifizierung" |
| C3 SQLite vs JSONB | CRITICAL | ✅ korrigiert: SQLite-only, `sa.JSON()` | Sektion "Audit-Tabelle" |
| C4 derive_printer_id Backwards-Compat | CRITICAL | ✅ klargestellt: kein Backwards-Compat | Sektion "Migration für Bestand" |
| C5 DELETE FK-Constraints | CRITICAL | ✅ entschieden: Soft-Delete (`enabled=false`) | Sektion "Delete-Flow" |
| H1 env-merge-Pflicht | HIGH | ✅ explizit | Sektion "Migration für Bestand" |
| H2 down_stack statt restart | HIGH | ✅ explizit | Sektion "Migration für Bestand" |
| H3 CSRF-Schutz | HIGH | ✅ Mechanismus benannt | Sektion "Web-Routes (HTML)" |
| H4 SNMP community redacted im Audit | HIGH | ✅ Redaction-Liste | Sektion "Audit-Tabelle" |
| H5 SELECT FOR UPDATE nicht SQLite | HIGH | ✅ BEGIN IMMEDIATE | Sektion "Data Flow" |
| H6 Pydantic-Payload-Felder + Validatoren | HIGH | ✅ explizit | Sektion "Pydantic-Schemas" |
| M1 Pre-Deploy-Snapshot konkreter Befehl | MED | ✅ `sqlite3 .backup` | Sektion "Migration für Bestand" |
| M2 Immutable-Fields-Durchsetzung | MED | ✅ Service ignoriert silent | Sektion "Komponenten" |
| M3 Coverage-Schwellen | MED | ✅ explizit | Sektion "Testing" |
| M4 created_at TZ | MED | ✅ UTC | Sektion "Komponenten" |
| M5 Plugin-Registry-Kopplung | MED | ✅ als Risiko akzeptiert | Sektion "Risiken" |
| M6 Transaktion explizit | MED | ✅ `async with session.begin()` | Sektion "Data Flow" |
| L Watchtower-Pause | LOW | ✅ | Sektion "Migration für Bestand" |
| L Healthcheck post-Deploy | LOW | ✅ | Sektion "Testing" |
| L Audit-Retention | LOW | ✅ "keine, <50KB/10J" | Sektion "Risiken" |
| L LAN-Routing | LOW | ✅ als Annahme dokumentiert | Sektion "Risiken" |
| L Hangar→Hub URL | LOW | ✅ intern via Container-Netz | Sektion "Architektur" |
| L FK auf printers_audit.printer_id | LOW | ✅ kein FK (Soft-Delete behält Row sowieso) | Sektion "Audit-Tabelle" |
| L i18n Pydantic-Error-Messages | LOW | ✅ deutsch only | Sektion "Error Handling" |

## Ziel

`printers.yaml` und `upsert_runtime_printers()` werden ersatzlos entfernt. Die DB-Tabelle `printers` (existiert seit Migration `b1a0b028aabb`) wird alleinige Source of Truth. Drucker werden ausschließlich über eine neue Admin-UI `/admin/printers/` (analog Hangar `/admin/layouts/`) angelegt, bearbeitet, deaktiviert und gelöscht (soft).

**Nicht-Ziele:**

- Plugin-Architektur ändern (`ptouch`, `brother_ql` bleiben Compile-Time-Plugins — nur die *Drucker-Instanzen* wandern in DB).
- Auto-Discovery (mDNS, ARP, SNMP-Scan) — Operator gibt Hardware-Daten manuell ein.
- Hardware-Verifikation beim Anlegen (User-Wunsch: CSV-Fallback bleibt für Brother P-touch Software).
- Hangar-seitige Änderungen — Hangar konsumiert weiter `GET /api/printers` (5min PrinterSync).
- Env-Bootstrap (`HUB_PRINTERS_JSON`) — explizit verworfen, nur Admin-UI.
- Postgres-Support — Hub ist SQLite-only (`sqlite+aiosqlite:////data/printer-hub.db`).

## Ausgangslage

| Komponente | Aktuell | Nach #124 |
|---|---|---|
| `printers.yaml` | Source of Truth, beim Start in DB gesynct | **entfernt** |
| `PrinterConfigLoader` (`app/services/printer_config_loader.py`) | YAML lesen + Cache | **entfernt** |
| `upsert_runtime_printers()` in `app/db/lifespan.py:176` | YAML → DB Sync | **entfernt** |
| `derive_printer_id(model, host, port)` in `app/services/printer_identity.py` | Deterministische UUIDv5 (3-arg) | **erweitert:** `derive_printer_id(model, host, port, created_at_utc)` (4-arg). Keine Backwards-Compat — alte Aufrufer entfallen mit `upsert_runtime_printers`. |
| DB-Tabelle `printers` | existiert, wird beim Start überschrieben | **alleinige Source of Truth** |
| `printers.enabled` | beim YAML-Sync auf true/false gesetzt | **Soft-Delete-Flag** — false = "gelöscht" für Endnutzer |
| `GET /api/printers` | liest aus DB (alle) | filtert `enabled=true` (unverändert für Hangar) |
| Admin-UI | Keine Web-UI im Hub | **NEU:** `/admin/printers/` (Liste + CRUD + Disable) |

### Existing Schema (Migration `b1a0b028aabb` + `da865401716d`)

SQLite-Realität (nicht Postgres):

```python
# Bereits in DB — KEINE Schema-Migration für printers nötig
sa.Column("id", sa.UUID(), primary_key=True),       # SQLite: TEXT
sa.Column("name", sa.String(255), unique=True),
sa.Column("slug", sa.String(255), unique=True),
sa.Column("model", sa.String(255)),
sa.Column("backend", sa.String(50)),
sa.Column("connection", sa.JSON(), nullable=True),  # SQLite: TEXT mit JSON-Validation
sa.Column("enabled", sa.Boolean(), default=True),
sa.Column("created_at", sa.DateTime(timezone=True)),
sa.Column("updated_at", sa.DateTime(timezone=True)),
```

Eine **neue Migration** für Audit-Tabelle `printers_audit`. Sonst nichts an Schema.

## Authentifizierung (NEU — adressiert C1 + C2 + H3)

### Pangolin SSO für Browser

Hub nutzt bereits `app/auth/dependencies.py` mit konfigurierbaren Headers:

| Setting | Default | Quelle |
|---|---|---|
| `sso_user_header` | `Remote-User` | Pangolin Standard |
| `sso_trust_header` | `X-Pangolin-Token` | Pangolin Standard |
| `sso_trust_token` | (leer = SSO off) | Vault: `homelab-print-hub-sso-trust-token` |
| Legacy-Fallback | `X-Pangolin-User` | Backwards-Compat aus Phase 7c |

`updated_by` im Audit kommt aus dem `Remote-User`-Header. Wenn `sso_trust_token` leer ist und Browser-Auth fehlt → 403. Legacy `X-Pangolin-User` wird akzeptiert (read-only Endpunkte).

### JSON-API Auth-Pfad (C2-Entscheidung: selbe Pangolin-Resource)

Die JSON-API `/api/v1/admin/printers` läuft **hinter derselben Pangolin-Resource** wie die HTML-UI (`print-hub.example.test`).

Drei Auth-Pfade durch dieselbe Resource:

1. **Browser-User → SSO** (Remote-User + X-Pangolin-Token-Trust)
2. **Tooling/Ansible → Header-Auth-Bypass** (`claude-automation` + 64-hex-Secret)
3. **API-Key (legacy)** — `app/api/routes/admin_api_keys.py` bleibt verfügbar für interne Skripte

Header-Auth-Bypass wird **per Compose-Label** auf der Hub-Resource gesetzt (Pangolin Blueprint, NIEMALS per API — siehe `feedback_pangolin_labels_source_of_truth`).

**Vollständiges Blueprint-Set** (H7-Ergänzung, alle Pflichtfelder per `pangolin-resource-standard.md`):

```yaml
labels:
  # Identität
  - "pangolin.public-resources.print-hub.name=Print Hub"
  - "pangolin.public-resources.print-hub.full-domain=print-hub.example.test"
  # Routing
  - "pangolin.public-resources.print-hub.protocol=http"
  - "pangolin.public-resources.print-hub.ssl=true"
  - "pangolin.public-resources.print-hub.targets[0].method=http"
  - "pangolin.public-resources.print-hub.targets[0].port=8000"
  - "pangolin.public-resources.print-hub.targets[0].path-match=prefix"
  # Healthcheck (Pflicht seit Newt v1.18.4)
  - "pangolin.public-resources.print-hub.targets[0].healthcheck.enabled=true"
  - "pangolin.public-resources.print-hub.targets[0].healthcheck.hostname=print-hub"
  - "pangolin.public-resources.print-hub.targets[0].healthcheck.path=/healthz"
  - "pangolin.public-resources.print-hub.targets[0].healthcheck.port=8000"
  - "pangolin.public-resources.print-hub.targets[0].healthcheck.interval=30"
  # Auth: SSO + Header-Auth-Bypass
  - "pangolin.public-resources.print-hub.auth.sso-enabled=true"
  - "pangolin.public-resources.print-hub.auth.basic-auth.user=claude-automation"
  - "pangolin.public-resources.print-hub.auth.basic-auth.password=<64-hex-secret>"
```

**Vault-Item (per `pangolin-resource-standard.md` Konvention):**
- Name: `Pangolin Header Auth - Print Hub`
- Username: `claude-automation`
- Password: das 64-hex Secret (gleicher Wert wie im Compose-Label)
- Collection: `Automation/Claude-Team`

**Migration-Schritt:** Bestandsresource `print-hub.example.test` muss vor Implementation auf diesen Standard gebracht werden — siehe `pangolin-resource-standard.md`. Bei der Implementierung ist zu prüfen, ob die Labels bereits gesetzt sind:

```python
# Phase-0-Live-Check
resource = mcp__pangolin-api__resource_by_resourceId(resourceId=<print-hub-id>)
# Erwartet: response.headerAuth ist nicht None, response.targets[0].healthCheck.enabled=true
```

### CSRF-Schutz (H3)

HTML-Forms (`POST /admin/printers`, `POST /admin/printers/{slug}`, `POST /admin/printers/{slug}/disable`, `POST /admin/printers/{slug}/enable`) brauchen CSRF-Schutz. Pangolin-SSO authentifiziert die Session, schützt aber nicht vor CSRF.

Mechanismus: **Starlette CSRF Middleware** (`starlette-csrf` package) mit Cookie-Token + Hidden-Form-Field-Verifikation. Token-Cookie ist `SameSite=Strict`. JSON-API `/api/v1/admin/printers` ist CSRF-frei wenn der Request via Basic-Auth (claude-automation) oder API-Key authentifiziert ist — diese Pfade können nicht aus dem Browser-Origin missbraucht werden.

## Architektur

```
                       ┌────────────────────────────┐
                       │  /admin/printers/ (HTML)   │
                       │  Liste · New · Edit · Disable│
                       └─────────────┬──────────────┘
                                     │ Form-Submit (SSO + CSRF)
                                     ▼
              ┌──────────────────────────────────────────┐
              │  Hub Backend (FastAPI)                   │
              │                                          │
              │  HTML-Routes (CSRF-protected):           │
              │   GET  /admin/printers          (Liste) │
              │   GET  /admin/printers/new      (Form)  │
              │   POST /admin/printers          (Create)│
              │   GET  /admin/printers/{slug}/edit      │
              │   POST /admin/printers/{slug}   (Update)│
              │   POST /admin/printers/{slug}/disable   │
              │   POST /admin/printers/{slug}/enable    │
              │                                          │
              │  JSON-API (Basic-Auth oder API-Key):     │
              │   GET    /api/printers          unchanged│
              │   GET    /api/v1/admin/printers   neu    │
              │   POST   /api/v1/admin/printers   neu    │
              │   GET    /api/v1/admin/printers/{slug}   │
              │   PUT    /api/v1/admin/printers/{slug}   │
              │   POST   /api/v1/admin/printers/{slug}/disable │
              │   POST   /api/v1/admin/printers/{slug}/enable  │
              │                                          │
              │  Service-Layer (app/services/):          │
              │   printer_admin_service.py               │
              │     · create_printer(...)                │
              │     · update_printer(slug, patch)        │
              │     · disable_printer(slug)              │
              │     · enable_printer(slug)               │
              │     · list_printers(include_disabled)    │
              │     · audit_record(...)                  │
              │   printer_identity.py (existing)         │
              │     · derive_printer_id(...,created_at)  │
              │   printer_model_registry.py (NEU)        │
              │     · list_available_models()            │
              └─────────────┬────────────────────────────┘
                            │
                            ▼
              ┌──────────────────────────────────────────┐
              │  SQLite (/data/printer-hub.db)           │
              │   printers       (existing — enabled=T/F)│
              │   printers_audit (neu)                   │
              │   hangar_meta    (existing, Diagnose-Marker)│
              └──────────────────────────────────────────┘
                            ▲
                            │ GET http://print-hub:8000/api/printers
                            │ (interner Container-Netz-Aufruf, KEIN Pangolin)
                            │
              ┌─────────────┴────────────────────────────┐
              │  Hangar PrinterSync (unverändert)        │
              │  läuft alle 5min, filtert enabled=true   │
              └──────────────────────────────────────────┘
```

**Hangar→Hub-Routing (L-Finding):** Hangar ruft `http://print-hub:8000/api/printers` **intern via Container-Netz** auf — kein Pangolin-Pfad, kein Header-Auth-Bypass nötig für Hangar. Die Pangolin-Resource gilt nur für externe Browser/Tooling.

**Entfernt aus Hub:**

- `app/services/printer_config_loader.py`
- `app/db/lifespan.py::upsert_runtime_printers()` und alle Aufrufe
- `app/schemas/printer_config.py` (PrintersFile, PrinterYAMLConfig)
- `/etc/printer-hub/printers.yaml` Volume-Mount im Compose
- `PRINTER_CONFIG_PATH` Env-Variable in Stack-Env
- `printers.yaml` aus `/docker/stacks/hangar-print-hub/config/`
- 3 Test-Files die `derive_printer_id` mit 3-arg-Signatur testen → migriert auf 4-arg

**Neu im Hub:**

- `app/services/printer_admin_service.py`
- `app/services/printer_model_registry.py`
- `app/services/audit_redaction.py` (M9 — redact_secrets als eigenes Modul)
- `app/api/routes/admin_printers.py` (JSON-API unter `/api/v1/admin/printers`)
- `app/web/routes/admin_printers.py` (HTML-UI unter `/admin/printers`)
- `app/templates/admin_printers/` (Jinja2: `list.html`, `form.html`, `confirm_disable.html`)
- `app/templates/_base.html` (Layout, falls noch keins existiert)
- `app/middleware/csrf.py` (Starlette-CSRF-Wrapper)
- `app/exceptions.py`: neue Exception `PrinterDisabledError` (M8)
- `app/services/print_service.py`: enabled-Check in `submit_print_job` (M8 — keine neue Datei, Modifikation)
- `app/db/engine.py`: SQLite-Connect-Listener für `journal_mode=WAL` + `isolation_level=SERIALIZABLE` (M7)
- Alembic-Migration `<timestamp>_add_printers_audit_and_backfill_connection.py` (M7 + H8b kombiniert: Schema-Erweiterung `queue_timeout_s`/`cut_defaults_half_cut` + Audit-Tabelle + Bestand-Backfill)

## Komponenten

### 1. `PrinterAdminService`

Geschäftslogik isoliert vom Routing. Eine Klasse, klare API:

```python
class PrinterAdminService:
    def __init__(self, session: AsyncSession, audit_user: str):
        self._session = session
        self._audit_user = audit_user

    async def list_printers(self, *, include_disabled: bool = False) -> list[Printer]: ...
    async def get_printer(self, slug: str) -> Printer | None: ...
    async def create_printer(self, payload: PrinterCreatePayload) -> Printer: ...
    async def update_printer(self, slug: str, patch: PrinterUpdatePayload) -> Printer: ...
    async def disable_printer(self, slug: str) -> Printer: ...
    async def enable_printer(self, slug: str) -> Printer: ...
```

**Immutable Fields (M2):** `update_printer` ignoriert silent jeden Versuch slug/model/backend/id zu setzen — analog Hangar Layout-Edit-Pattern. Wenn jemand via API einen anderen `slug` sendet, antwortet die Methode mit 200 OK aber der DB-Wert bleibt unverändert. (Begründung: Web-UI disabled diese Felder schon, API-Pfad soll robust sein, keine 422-Wand für ein "Test-Anfänger ändert versehentlich slug"-Szenario.)

### 2. ID-Generierung (`derive_printer_id`)

```python
def derive_printer_id(
    model: str,
    host: str,
    port: int,
    created_at_utc: datetime,
) -> uuid.UUID:
    """UUIDv5 aus Model+Host+Port+Created-At (UTC, ISO-8601 mit Microseconds).

    Bestandsdrucker (vor #124): created_at war nicht im Salt.
    Diese behalten ihre alte UUID — keine Migration.

    Neue Drucker (nach #124): created_at sorgt für Kollisionsfreiheit
    bei IP/Port-Wiederverwendung.

    M4 — TZ-Pflicht: created_at_utc MUSS timezone-aware sein
    (datetime.now(timezone.utc)), sonst raise ValueError. Salt ist
    TZ-sensitiv — ein naive datetime würde UUID-Drift erzeugen.
    """
    if created_at_utc.tzinfo is None:
        raise ValueError("created_at_utc must be timezone-aware (UTC)")
    salt = f"{model}|{host}|{port}|{created_at_utc.isoformat()}"
    return uuid.uuid5(uuid.NAMESPACE_URL, salt)
```

**C4-Klarstellung:** Bestandsdrucker werden NICHT neu generiert. `upsert_runtime_printers` wird komplett entfernt — kein Aufrufer der alten 3-arg-Variante bleibt im Code. Die **5 betroffenen Test-Files** (H9-Ergänzung Round-2) werden:

- `tests/services/test_printer_identity.py`: auf 4-arg-Signatur migriert, neuer Test für `naive datetime → ValueError`.
- `tests/db/test_lifespan.py`: `upsert_runtime_printers`-Tests gelöscht (Funktion existiert nicht mehr).
- `tests/services/test_printer_config_loader.py`: komplett gelöscht (PrinterConfigLoader existiert nicht mehr).
- `tests/db/test_lifespan_seeds_and_upserts.py` (H9): komplett gelöscht — testet `upsert_runtime_printers` Sub-Pfade.
- `tests/db/test_lifespan_printer_upsert.py` (H9): komplett gelöscht — testet `derive_printer_id` mit 3-arg-Signatur direkt.

**Verifikationsschritt im Plan:** `grep -rn "upsert_runtime_printers\|PrinterConfigLoader" backend/tests/` MUSS leer sein nach den Löschungen. `grep -rn "derive_printer_id(" backend/` darf nur 4-arg-Aufrufe finden.

### 3. Pydantic-Schemas (H6)

```python
# app/schemas/printer_admin.py (NEU)

SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$"

class SNMPConfig(BaseModel):
    """Verschachtelte Sub-Struktur — bewusst gleiches Schema wie das alte YAML
    (snmp.discover, snmp.community), damit YAML-Backups und Live-DB
    strukturell vergleichbar bleiben (H8a-Entscheidung)."""
    discover: bool = False
    community: str | None = Field(default="public", max_length=64)

    @model_validator(mode="after")
    def _community_consistency(self) -> "SNMPConfig":
        if self.discover and not self.community:
            raise ValueError("snmp.community ist Pflicht wenn snmp.discover=True ist")
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

### DB-JSON-Form

Was konkret in `printers.connection` und in den Audit-Snapshots steht:

```json
{
  "host": "192.0.2.10",
  "port": 9100,
  "snmp": {
    "discover": true,
    "community": "***REDACTED***"
  }
}
```

`queue.timeout_s`, `cut_defaults.half_cut` werden in der `printers`-Tabelle **als separate Spalten** geführt (siehe Phase 1b der Migration unten — bestehendes Schema wird erweitert). Begründung: stabile Spalten erleichtern SQL-Filter ("alle Drucker mit half_cut") und vermeiden JSON-Path-Queries in SQLite.

### M12 — Flattening zwischen Pydantic-Verschachtelung und flachen DB-Spalten

`payload.model_dump()` liefert verschachtelte Dicts (`{"queue": {"timeout_s": 30}, "cut_defaults": {"half_cut": true}}`). Die DB-Spalten sind aber flach (`queue_timeout_s`, `cut_defaults_half_cut`). Das Mapping erledigt ein expliziter Helper im Service:

```python
# app/services/printer_admin_service.py (internal)
def _payload_to_row(
    payload: PrinterCreatePayload,
    printer_id: UUID,
    created_at_utc: datetime,
) -> dict[str, Any]:
    """Mappt Pydantic-Payload auf flache DB-Spalten-dict."""
    return {
        "id": printer_id,
        "name": payload.name,
        "slug": payload.slug,
        "model": payload.model,
        "backend": payload.backend,
        "connection": payload.connection.model_dump(mode="json"),  # bleibt verschachtelt im JSON-Feld
        "queue_timeout_s": payload.queue.timeout_s,
        "cut_defaults_half_cut": payload.cut_defaults.half_cut,
        "enabled": payload.enabled,
        "created_at": created_at_utc,
        "updated_at": created_at_utc,
    }

def _apply_update_patch(row: Printer, patch: PrinterUpdatePayload) -> dict[str, Any]:
    """Wendet PATCH-Felder auf row an. Slug/model/backend/id werden silent
    ignoriert. Returnt dict mit nur den geänderten Spalten für SQL-UPDATE."""
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
    """Audit-JSON-Sicht: connection bleibt verschachtelt, queue/cut_defaults
    werden wieder verschachtelt damit Audit-Snapshots lesbar bleiben."""
    return {
        "id": str(row["id"]),
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

**Test-Cases für Flattening (in `tests/services/test_printer_admin_service.py`):**
- `_payload_to_row` setzt `queue_timeout_s=30` aus `payload.queue.timeout_s`
- `_apply_update_patch` mit nur `queue=PrinterQueueSettings(timeout_s=60)` returnt `{"queue_timeout_s": 60}` und keine anderen Felder
- `_row_to_audit_view` rekonstruiert die verschachtelte Form für `redact_secrets`-Input

Error-Messages: **deutsch** (i18n-Policy L-Finding). Pydantic-Custom-Error-Map nutzt `pydantic.v1.errors.PydanticValueError`-Pattern oder `model_validator`-Returns.

### 4. Web-Routes (HTML)

`/admin/printers/` zeigt Tabelle (Name, Slug, Model, Host:Port, enabled, Audit-User, updated_at). Standardmäßig nur enabled, Toggle "Auch deaktivierte zeigen" via Query-Param `?include_disabled=1`.

`/admin/printers/new` HTML-Form für neuen Drucker:

| Feld | Typ | Editierbar nach Create? |
|---|---|---|
| name | Text (required) | Ja |
| slug | Text (required, regex `^[a-z0-9-]+$`) | **Nein** |
| model | Dropdown (gefüllt aus Plugin-Registry) | **Nein** |
| backend | Dropdown (`ptouch`, `brother_ql`) | **Nein** |
| connection.host | Text | Ja |
| connection.port | Number | Ja |
| connection.snmp_discover | Checkbox | Ja |
| connection.snmp_community | Text (default `public`) | Ja |
| queue.timeout_s | Number (default `30`) | Ja |
| cut_defaults.half_cut | Checkbox | Ja |
| enabled | Checkbox (default true) | Ja |

`/admin/printers/{slug}/edit` zeigt Form, vorausgefüllt. `slug`, `model`, `backend`, `id` sind im HTML `disabled` und werden bei `POST` ignoriert.

**Disable** statt Delete: `POST /admin/printers/{slug}/disable` zeigt Confirm-Page; bei zweitem Click setzt `enabled=false` + Audit-Eintrag mit `action='disable'`. Reaktivieren via `POST /admin/printers/{slug}/enable` aus der "deaktivierten"-Liste.

### 5. JSON-API

| Endpoint | Auth | Zweck |
|---|---|---|
| `GET /api/v1/admin/printers?include_disabled=…` | Basic-Auth `claude-automation` ODER API-Key | Liste |
| `POST /api/v1/admin/printers` | dito | Create |
| `GET /api/v1/admin/printers/{slug}` | dito | Detail |
| `PUT /api/v1/admin/printers/{slug}` | dito | Update |
| `POST /api/v1/admin/printers/{slug}/disable` | dito | Soft-Delete |
| `POST /api/v1/admin/printers/{slug}/enable` | dito | Reaktivieren |

Public `GET /api/printers` bleibt unverändert, filtert `enabled=true` (Hangar sieht keine deaktivierten Drucker).

**Trailing-Slash-Konvention (L-Round-2):** **ohne Trailing-Slash**. FastAPI-Standard: `/api/v1/admin/printers` (Liste), nicht `/api/v1/admin/printers/`. Konsistent mit den existing Hub-Endpoints (`/api/printers`, `/api/admin/api-keys`).

### 6. Plugin-Registry für Model-Dropdown

```python
# app/services/printer_model_registry.py (NEU)
@dataclass(frozen=True)
class PrinterModel:
    backend: str           # "ptouch" | "brother_ql"
    model: str             # "PT-P750W" | "QL-820NWB" | ...
    display_name: str      # "Brother PT-P750W (Compact-Tape)"

def list_available_models() -> list[PrinterModel]:
    """Lese aus ptouch.PRINTERS + brother_ql.MODELS — was unterstützen die Plugins?"""
    ...
```

**M5 — akzeptiertes Risiko:** Direktimport von `ptouch.PRINTERS` und `brother_ql.MODELS` ist eng gekoppelt. Wenn diese Pakete in Zukunft die Modell-Liste umbenennen, bricht die Registry. Ausweg wäre Plugin-Architektur (Adapter pro Plugin der `list_models()` exportiert). Für #124 explizit nicht angegangen — YAGNI für aktuell 2 unterstützte Plugins. Falls beim Implementieren das Import-Pattern bricht: Hardcoded-Fallback-Liste als Notnagel.

### 7. Audit-Tabelle `printers_audit`

Neue Alembic-Migration `<timestamp>_add_printers_audit.py`:

```python
op.create_table(
    "printers_audit",
    sa.Column("id", sa.UUID(), primary_key=True),
    sa.Column("printer_id", sa.UUID(), nullable=False),  # KEIN FK — printers-Row bleibt sowieso (Soft-Delete)
    sa.Column("slug", sa.String(255), nullable=False),
    sa.Column("action", sa.String(50), nullable=False),  # 'create' | 'update' | 'disable' | 'enable'
    sa.Column("before_json", sa.JSON(), nullable=True),  # NULL bei 'create'
    sa.Column("after_json",  sa.JSON(), nullable=True),  # NULL nicht erlaubt für enable/disable/update
    sa.Column("updated_by",  sa.String(255), nullable=False),
    sa.Column("created_at",  sa.DateTime(timezone=True),
              server_default=sa.func.current_timestamp(), nullable=False),
)
op.create_index("idx_printers_audit_printer_id", "printers_audit", ["printer_id"])
op.create_index("idx_printers_audit_created_at_desc", "printers_audit", [sa.text("created_at DESC")])
```

**Dialect (C3):** `sa.JSON()` statt JSONB — SQLAlchemy serialisiert auf SQLite zu TEXT, kompatibel mit `app/db/engine.py` (`sqlite+aiosqlite:///`).

**FK auf printers_audit.printer_id (L-Finding):** **Bewusst kein FK** weil Soft-Delete die Parent-Row sowieso behält. Ein FK würde nichts verhindern (printers wird nie hard-deleted), aber Alembic-Migrations-Reihenfolge unnötig komplex machen.

**SNMP-Community-Redaction (H4 + M9):** `connection.snmp.community` wird vor dem Schreiben in `before_json`/`after_json` durch `***REDACTED***` ersetzt.

Helper lebt in **eigenem Modul** `app/services/audit_redaction.py` (M9-Ergänzung):

```python
# app/services/audit_redaction.py
SECRET_PATHS: frozenset[tuple[str, ...]] = frozenset({
    ("connection", "snmp", "community"),
    # Künftige Secret-Felder hier ergänzen
})

def redact_secrets(payload: dict[str, Any]) -> dict[str, Any]:
    """Erzeugt eine Deepcopy mit allen bekannten Secret-Pfaden durch
    '***REDACTED***' ersetzt.

    Edge-Case: wenn das Feld None oder leer ist, bleibt der Wert
    unverändert (kein versehentliches Verschleiern eines fehlenden Wertes).
    """
    ...
```

Coverage-Schwelle für `audit_redaction.py`: **80 %** (Pure-Helper mit
mehreren Branches). Tests:
- Drucker mit SNMP-Community → wird redacted
- Drucker ohne SNMP-Block (Bestandsdrucker vor Backfill) → unverändert
- Drucker mit `snmp.community=None` → unverändert (kein Redact von None)
- Weitere Felder im Payload bleiben unangetastet

**Audit-Retention (L-Finding):** Keine Retention. Worst-Case: 10 Drucker × 30 Edits/Jahr × 10 Jahre = 3000 Rows ≈ 30KB. Unwesentlich.

## Data Flow

### Create-Flow

```
1. Operator → GET /admin/printers/new (Pangolin SSO)
2. Hub serviert HTML-Form (Models aus Plugin-Registry + CSRF-Token)
3. Operator fills + submits → POST /admin/printers (mit CSRF-Header)
4. Web-Route validiert CSRF + Pydantic (PrinterCreatePayload)
5. PrinterAdminService.create_printer (async with session.begin() — atomare Transaktion):
   a. created_at_utc = datetime.now(timezone.utc)
   b. printer_id = derive_printer_id(model, host, port, created_at_utc)
   c. row_dict = _payload_to_row(payload, printer_id, created_at_utc)  # siehe Flattening-Helper M12
   d. INSERT INTO printers (...)
   e. INSERT INTO printers_audit (action='create', before=NULL, after=redact_secrets(_row_to_audit_view(row_dict)))
   (Transaktion COMMIT bei session.begin()-Exit)
6. Redirect 303 → /admin/printers?info=created&slug=<new-slug>
7. Hangar nächste Sync-Runde (≤5min) zieht neuen Drucker via GET /api/printers
```

### Update-Flow

```
1. Operator → /admin/printers/{slug}/edit
2. PrinterAdminService.get_printer(slug) → Row
3. HTML-Form mit aktuellen Werten (slug/model/backend disabled)
4. POST /admin/printers/{slug} (mit CSRF)
5. PrinterAdminService.update_printer (Transaktion — siehe M7 unten):
   a. SELECT … WHERE slug=? — SQLite hat kein FOR UPDATE, BEGIN IMMEDIATE
      gibt uns exklusive Schreib-Sperre auf der DB-Datei (H5).
   b. before_view = _row_to_audit_view(row)
   c. changes = _apply_update_patch(row, patch)  # silent ignore von slug/model/backend/id (M12)
   d. UPDATE printers SET <changes>, updated_at=? WHERE id=?
   e. after_view = _row_to_audit_view(merged_row)
   f. INSERT INTO printers_audit (action='update',
        before=redact_secrets(before_view), after=redact_secrets(after_view))
6. Redirect 303 → /admin/printers?info=updated&slug=<slug>
```

### M7 — Transaktions-Strategie (BEGIN IMMEDIATE × session.begin())

Storage-Round-2 hat einen Konflikt aufgezeigt: `async with session.begin():`
öffnet bereits eine Transaktion via SQLAlchemy. Ein zusätzliches manuelles
`BEGIN IMMEDIATE` würde mit `OperationalError: cannot start a transaction
within a transaction` brechen.

**Entscheidung (M7):** Nicht beide nutzen — sondern die Engine-Defaults der
aiosqlite-Connection auf IMMEDIATE setzen, damit jede Transaktion (auch die
implizite aus `session.begin()`) als IMMEDIATE startet:

```python
# app/db/engine.py — Pseudo-Code, korrekte Reihenfolge:
# 1) Engine zuerst erstellen, 2) DANN Listener registrieren.
# Vorhandener engine.py-Aufbau wird minimal erweitert um isolation_level + Listener.

from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine

# Schritt 1: Engine erstellen (existing — isolation_level NEU hinzufügen)
engine = create_async_engine(
    DATABASE_URL,
    isolation_level="SERIALIZABLE",  # aiosqlite mappt SERIALIZABLE auf BEGIN IMMEDIATE
    # ... existing kwargs (echo, pool_pre_ping, etc.) bleiben
)

# Schritt 2: Connect-Listener auf engine.sync_engine NACH Engine-Creation
@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record):
    """Setzt SQLite-Pragmas bei jedem neuen Connection-Open.

    - journal_mode=WAL: erlaubt parallele Reader während Writer aktiv ist,
      reduziert Lock-Konflikte im Single-Replica-Setup.
    - foreign_keys=ON: SQLite default ist OFF — wir wollen Constraints aktiv.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
```

**Was sich konkret an `engine.py` ändert (Delta-Hinweis L-Round-3):**
- NEU: `isolation_level="SERIALIZABLE"` als `create_async_engine`-Argument
- NEU: `@event.listens_for`-Decorated Listener-Funktion direkt nach Engine-Creation
- Existing: alles andere unverändert (`DATABASE_URL`-Auflösung, `_ensure_data_dir`, etc.)

**Innerhalb des Services** verwendet jeder Mutations-Pfad dann nur noch
`async with session.begin():` ohne expliziten `BEGIN IMMEDIATE`-Aufruf —
SQLAlchemy startet die Transaktion automatisch im IMMEDIATE-Modus.

**Atomicity-Garantie:** Die Transaktion umschließt INSERT printers +
INSERT printers_audit gemeinsam. Bei Audit-INSERT-Fehler wird der
printers-INSERT vollständig zurückgerollt (SQLAlchemy-Rollback-Verhalten
im Context-Manager).

### Disable-Flow (vorher Delete-Flow — C5-Entscheidung Soft-Delete)

```
1. Operator → /admin/printers/{slug}/disable (GET) zeigt Confirm-Page
2. POST /admin/printers/{slug}/disable (mit CSRF)
3. PrinterAdminService.disable_printer (async with session.begin()):
   a. SELECT … WHERE slug=? + BEGIN IMMEDIATE
   b. Wenn nicht existent → 404
   c. Wenn schon disabled → 409 "bereits deaktiviert"
   d. UPDATE printers SET enabled=false, updated_at=now() WHERE id=?
   e. INSERT INTO printers_audit (action='disable', before=row_dict, after=row_dict_with_enabled_false)
4. Redirect 303 → /admin/printers?info=disabled&slug=<slug>
```

**Implikationen für Hangar + PrintService (Soft-Delete, M8-Ergänzung):**

- Nächster `GET /api/printers` filtert deaktivierte Drucker raus → Hangar PrinterSync entfernt sie aus seinem Cache.
- FK-Referenzen in `jobs`, `print_batches`, `presets`, `printer_state` bleiben intakt — der Drucker existiert weiter.
- **PrintService.submit_print_job MUSS angepasst werden (M8):**

```python
# app/services/print_service.py:submit_print_job — neuer Pre-Check
async def submit_print_job(self, request: PrintRequest) -> UUID:
    printer = await self._printers.get_by_id(request.printer_id)
    if printer is None:
        raise PrinterNotFoundError(request.printer_id)
    if not printer.enabled:
        raise PrinterDisabledError(request.printer_id, printer.slug)
    # ... existing logic
```

Neue Exception `PrinterDisabledError` in der existierenden Hierarchie
`app/printer_backends/exceptions.py` (M11 — `PrinterError` ist die Root-
Basisklasse, `LabelHubException` existiert nicht):

```python
# app/printer_backends/exceptions.py
class PrinterDisabledError(PrinterError):
    """Drucker existiert in DB, ist aber deaktiviert (Soft-Delete-Status).

    Mappt in der HTTP-Schicht auf 409 (nicht 404), weil der Drucker
    semantisch existiert — er ist nur vorübergehend nicht verwendbar.
    """
    def __init__(self, printer_id: UUID, slug: str) -> None:
        self.printer_id = printer_id
        self.slug = slug
        super().__init__(f"Printer {slug} ({printer_id}) is disabled")
```

Error-Handler in `app/api/routes/print.py` (analog `TapeMismatchError`-
Pattern) mappt auf 409 mit Body
`{"error": "printer_disabled", "slug": "<slug>"}`.

- Re-Enable über `/admin/printers/{slug}/enable` macht den Drucker sofort wieder verfügbar.

**Test-Cases für M8** (in `tests/services/test_print_service.py`):
- `submit_print_job` mit existierendem aber `enabled=false` Drucker → raises `PrinterDisabledError`
- HTTP-Integration: `POST /api/v1/print` mit disabled-Drucker-UUID → 409 mit `printer_disabled`-Body

### Startup-Flow (neu)

`lifespan.py::startup()` macht **keinen** Drucker-Sync mehr. Nur:

1. Alembic-Migrationen anwenden (inkl. neue `printers_audit`)
2. Konnektivitäts-Check zur DB (existing)
3. Markiere `hangar_meta.printers_v2_active = "true"` (Soft-Marker für Diagnose)

Bei **leerer `printers`-Tabelle** (Fresh-Install): keinerlei Action. Hub startet sauber, `GET /api/printers` liefert `[]`. Operator legt seine Drucker via Admin-UI an.

## Migration für Bestand (Round-2 erweitert)

### Phase 1a: Vor-Deploy — Snapshot + env-merge

```bash
# 1. SQLite-Backup (M1)
ssh root@prod-node.example.test \
  "docker exec hangar-print-hub-print-hub-1 sqlite3 /data/printer-hub.db \
     '.backup /data/printer-hub.db.bak-pre-124'"

# 2. Lokale Kopie ziehen (PBS sichert das verzeichnis sowieso, aber explizit)
ssh root@prod-node.example.test \
  "docker cp hangar-print-hub-print-hub-1:/data/printer-hub.db.bak-pre-124 \
     /docker/stacks/hangar-print-hub/backups/"

# 3. Watchtower pausieren (L-Finding — gleicher Race wie Phase 1k.1b)
mcp__dockhand__set_container_auto_update(
    environmentId=10, containerName="hangar-print-hub-print-hub-1",
    auto_update="never")
```

### Phase 1b: Alembic-Backfill für Bestands-Drucker (NEU H8b)

Die DB-Tabelle `printers` wurde bisher von `upsert_runtime_printers()` mit
`connection = {"host": ..., "port": ...}` befüllt — SNMP/queue/cut_defaults
existieren **gar nicht** in den Bestands-Rows. Wenn YAML wegfällt und die
Admin-UI diese Felder erwartet, hätten Bestandsdrucker leere/fehlende Werte.

**Alembic-Migration `<timestamp>_backfill_printer_connection_and_defaults.py`**
läuft im selben Schritt wie `add_printers_audit`:

```python
# Schema-Erweiterung: queue/cut_defaults als separate Spalten
op.add_column("printers", sa.Column("queue_timeout_s",
              sa.Integer(), nullable=False, server_default="30"))
op.add_column("printers", sa.Column("cut_defaults_half_cut",
              sa.Boolean(), nullable=False, server_default=sa.false()))

# Daten-Backfill: connection.snmp ergänzen, falls nicht vorhanden
# (verschachtelte Struktur — siehe Pydantic-Schema)
connection_table = sa.table(
    "printers",
    sa.column("id", sa.UUID()),
    sa.column("connection", sa.JSON()),
)
conn = op.get_bind()
for row in conn.execute(sa.select(connection_table.c.id, connection_table.c.connection)):
    conn_json = row.connection or {}
    # Idempotent: nur ergänzen wenn snmp fehlt
    if "snmp" not in conn_json:
        conn_json["snmp"] = {"discover": False, "community": "public"}
        conn.execute(
            connection_table.update()
            .where(connection_table.c.id == row.id)
            .values(connection=conn_json)
        )
```

**Verifikation nach Migration (per Spec-Akzeptanzkriterium):**

```sql
SELECT slug,
       json_extract(connection, '$.snmp.discover') AS snmp_discover,
       json_extract(connection, '$.snmp.community') AS snmp_community,
       queue_timeout_s,
       cut_defaults_half_cut
FROM printers
WHERE enabled = 1;
-- Erwartet: alle Bestandsdrucker haben snmp.discover=0, community='public', timeout=30, half_cut=0
```

### Phase 2: Deploy

**WICHTIG (H1):** Stack-Env-Update folgt `dockhand-stack-env-merge.md` — `PRINTER_CONFIG_PATH` entfernen MUSS via Merge-Pattern erfolgen:

```python
existing = mcp__dockhand__get_stack_env(environmentId=10, name="hangar-print-hub")
merged = {v["key"]: v for v in existing["variables"] if v["key"] != "PRINTER_CONFIG_PATH"}
mcp__dockhand__update_stack_env(
    environmentId=10, name="hangar-print-hub",
    variables=list(merged.values()))
```

Compose-Update entfernt:
- `volumes` Eintrag mit `printers.yaml:/etc/printer-hub/printers.yaml:ro`
- `environment` Eintrag `PRINTER_CONFIG_PATH` (falls dort statt in Stack-Env)

**Restart-Pfad (H2):** `down_stack` + `start_stack` (NICHT `restart_stack`), weil Volume-Mounts und Compose-Topology geändert werden:

```python
mcp__dockhand__down_stack(environmentId=10, name="hangar-print-hub")
mcp__dockhand__update_stack_compose(environmentId=10, name="hangar-print-hub", content=NEW_COMPOSE)
mcp__dockhand__start_stack(environmentId=10, name="hangar-print-hub")
```

Anschließend `printers.yaml` aus `/docker/stacks/hangar-print-hub/config/` löschen.

### Phase 3: Verifikation (Round-2-Smoke + M10)

```
✓ Container-DNS verifizieren (M10):
  docker exec hangar-print-hub-hangar-1 \
    getent hosts print-hub
  → muss IP des print-hub-Containers zurückgeben
  (falls Service-Name abweicht: Compose-Service-Definition prüfen)

✓ Hub-Container kommt healthy hoch (Healthcheck /healthz HTTP 200)

✓ Bestand-Backfill-Verifikation (H8b):
  docker exec hangar-print-hub-print-hub-1 sqlite3 /data/printer-hub.db \
    "SELECT slug, json_extract(connection, '\$.snmp.discover') AS d,
            queue_timeout_s, cut_defaults_half_cut FROM printers"
  → alle Bestandsdrucker zeigen d=0, timeout=30, half_cut=0

✓ GET /api/printers liefert alle Bestandsdrucker (mit ergänzten Defaults)

✓ Hangar PrinterSync log zeigt keinen Fehler

✓ /admin/printers/ zeigt Liste mit allen Bestandsdruckern

✓ Edit auf Bestandsdrucker speichert + Audit-Row erscheint mit
  redaktiertem snmp.community

✓ Test-Drucker anlegen + sofort wieder disablen → Audit zeigt
  2 Rows (create, disable), GET /api/printers filtert ihn raus

✓ POST /api/v1/print mit disabled-Drucker-UUID → 409 printer_disabled (M8)

✓ Hangar Print-Button für Bestandskategorien funktioniert (Smoke 1 Label)

✓ Watchtower wieder auf "any" setzen
```

### Rollback-Pfad

```bash
# 1. SQLite Restore aus Backup
ssh root@prod-node.example.test \
  "docker cp /docker/stacks/hangar-print-hub/backups/printer-hub.db.bak-pre-124 \
     hangar-print-hub-print-hub-1:/data/printer-hub.db"

# 2. Compose auf vorherige Version + printers.yaml wieder einfügen
# 3. Stack-Env: PRINTER_CONFIG_PATH zurück merge_in
# 4. down_stack + start_stack
```

## Error Handling

| Fehler | HTTP | UI-Verhalten |
|---|---|---|
| Duplicate slug bei Create | 409 | Form re-rendert mit Fehler "Slug bereits vergeben" |
| Duplicate name bei Create | 409 | Form re-rendert mit Fehler "Name bereits vergeben" |
| Pydantic-ValidationError | 422 | Form re-rendert mit Feld-Fehlern (deutsch) |
| CSRF-Token-Fehler | 403 | Toast "Sitzung abgelaufen, Seite neu laden" |
| `slug` nicht gefunden | 404 | Redirect zu Liste mit Info "Drucker nicht gefunden" |
| Drucker schon disabled | 409 | Toast "Bereits deaktiviert" |
| Drucker schon enabled | 409 | Toast "Bereits aktiv" |
| DB-Constraint-Violation | 500 | Sentry-Log + generic Error-Page |
| Pangolin ohne Remote-User | 403 | Pangolin Login-Redirect |
| Plugin-Registry leer | 500 | Service-Fehler, UI zeigt "Keine Drucker-Plugins kompiliert" |

## Testing

### Coverage-Schwellen (M3, per test-coverage-pflicht.md)

| Modul | Min-Coverage | Begründung |
|---|---|---|
| `printer_admin_service.py` | **85 %** | Mutation-Logic |
| `printer_model_registry.py` | 75 % | Pure-Helper |
| `printer_identity.py` | 85 % | Mutation (UUIDv5-Derivation) |
| `api/routes/admin_printers.py` | 80 % | Business-Endpunkte |
| `web/routes/admin_printers.py` | 70 % | Template-Routing |
| `middleware/csrf.py` | 80 % | Auth-Layer |

CI-Gate per `pyproject.toml` Section `[tool.coverage.report]`:
- `fail_under = 80` als globale Schwelle
- Per-File-Threshold via `pytest-cov --cov-fail-under` für die kritischen Module

### Unit-Tests

- `PrinterAdminService.create_printer` Happy + Duplicate-Slug + Duplicate-Name + DB-Error
- `PrinterAdminService.update_printer` Happy + nicht-existent + Versuch slug/model/backend zu ändern → wird ignoriert (kein 422) + DB-Error
- `PrinterAdminService.disable_printer` Happy + nicht-existent + schon-disabled + DB-Error
- `PrinterAdminService.enable_printer` Happy + nicht-existent + schon-enabled + DB-Error
- `derive_printer_id` Determinismus (gleicher Input → gleiche UUID) + naive datetime → ValueError + verschiedene UTC-Timestamps → verschiedene UUIDs
- Plugin-Registry: Mock-Plugins → korrekte Liste, leere Plugin-Liste → 500
- `redact_secrets`: SNMP-Community wird ersetzt, andere Felder unverändert

### Integration-Tests (TestClient)

- `GET /admin/printers` → HTML mit allen enabled Druckern, `?include_disabled=1` zeigt auch disabled
- `POST /admin/printers` → 303 + DB-Row + Audit-Row (mit redacted community)
- `POST /admin/printers` ohne CSRF-Token → 403
- `POST /admin/printers/{slug}` Update → DB-Row aktualisiert + Audit-Row (before/after redacted)
- `POST /admin/printers/{slug}/disable` → enabled=false in DB + Audit-Row, `GET /api/printers` filtert raus
- `POST /admin/printers/{slug}/enable` → enabled=true + Audit-Row
- `GET /api/printers` nach Create/Update/Disable → reflektiert Änderungen
- 403 wenn kein Remote-User-Header
- 409 bei Duplicate slug

### CSRF-Test-Strategie (4 explizite Fälle, L-Round-2)

```python
# tests/middleware/test_csrf.py
# 1. POST mit gültigem Cookie + Hidden-Field-Token-Match → 303 (Erfolg)
# 2. POST mit Cookie aber FEHLENDEM Hidden-Field → 403
# 3. POST mit Cookie aber FALSCHEM Hidden-Field → 403
# 4. POST mit Authorization-Header (Basic/Bearer) und KEINEM Cookie → CSRF skipped, 303/200
```

### E2E-Test

- Frische DB (keine printers.yaml, leere printers-Tabelle, leere Audit-Tabelle)
- Hub startet → keine Errors, `GET /api/printers` → `[]`, `GET /admin/printers/` → leere Tabelle
- Via TestClient `POST /api/v1/admin/printers` (Basic-Auth claude-automation) → Drucker erscheint in `GET /api/printers`
- Restart Hub → Drucker noch da (kein Re-Sync nötig)
- Disable → Reload → enabled=false + nicht in `GET /api/printers`

### Production-Smoke-Test (L-Finding: Healthcheck post-Deploy)

1. PR merge → CI green
2. Phase-1+2 Migration (siehe oben)
3. `curl -fsS https://print-hub.example.test/healthz` → 200
4. Browser: `/admin/printers` → Liste der 2 Bestandsdrucker (brother-p750w, brother-ql820nwb)
5. Edit `brother-p750w` Name testweise → Save → Reload → Wert übernommen
6. Rollback Name-Edit
7. Hangar `/admin/layouts/` → unverändert, Print-Buttons funktionieren
8. Watchtower wieder auf `any` setzen

## Risiken & offene Punkte

| # | Risiko | Mitigation |
|---|---|---|
| R1 | Hangar PrinterSync schlägt fehl wenn Drucker disabled der noch in Hangar-Layouts referenziert ist | UI in Hangar: Layouts mit disabled Druckern zeigen Warnsymbol. (Out-of-Scope #124, Hangar-Side-Issue) |
| R2 | Pangolin-Resource-Bestand: Header-Auth-Bypass evtl nicht gesetzt | Phase-0-Live-Check vor Implementation. Falls fehlt: Compose-Blueprint-Labels nachziehen + Vault-Item anlegen. |
| R3 | Plugin-Registry: `ptouch.PRINTERS` evtl nicht öffentliche API (M5 akzeptiert) | Hardcoded-Fallback-Liste falls Import bricht. Pin auf konkrete ptouch-py-Version in pyproject.toml. |
| R4 | Bei `disable` eines aktuell-druckenden Druckers könnte ein Job abbrechen | Akzeptabel — Operator-Verantwortung. Falls problematisch: Pre-Check `printer_state.queue_length>0` + 409 (out-of-scope #124) |
| R5 | LAN-Routing Hub→Drucker-IPs gilt als gegeben | Hub-Container ist im traefik-public + LAN-Bridge — Routing existiert. Live-Check beim Deploy. |
| R6 | Audit-Retention: Tabelle wächst nie über 30KB → keine Cleanup-Pflicht | dokumentiert, kein Code nötig |
| R7 | DB-Backup enthält Audit-JSON — SNMP-Community NICHT in before/after dank Redaction | H4 mitigiert |
| R8 | Pangolin Bug #3099 (Basic-Auth-Dialog statt SSO-Redirect bei SSO+BasicAuth Resourcen) | Bekanntes Phänomen — beim Browser-Test ggf. Basic-Auth-Dialog statt SSO-Page sichtbar. Cancel im Dialog führt auf SSO-Login. **Nicht** als Bug reporten. Siehe `pangolin-resource-standard.md` Abschnitt "Bekannte Pangolin-Issues" und [fosrl/pangolin#3099](https://github.com/fosrl/pangolin/issues/3099). |

## Out of Scope (für Issue #124)

- Drucker-Connection-Test-Button in der UI ("Ping printer")
- Bulk-Import (CSV-Upload)
- Drucker-Klonen ("Copy from existing")
- Hangar-Side: Layouts-Refs auf disabled Drucker proaktiv warnen → Hangar-Issue separat
- Mehrsprachigkeit der Admin-UI (deutsch only)
- Hard-Delete-Pfad (nur Soft-Delete in dieser Iteration)
- Pre-Check auf laufende Print-Jobs bei `disable` (R4)

## Akzeptanzkriterien

- [ ] `printers.yaml` ist nirgendwo mehr referenziert (Code + Compose + Stack-Env + Docs + /docker/stacks/hangar-print-hub/config/)
- [ ] `PrinterConfigLoader` + `upsert_runtime_printers` sind entfernt + **5 Test-Files** entfernt/migriert (siehe ID-Generierung-Sektion)
- [ ] `derive_printer_id` ist 4-arg (timezone-aware created_at_utc); naive datetime → ValueError; 3-arg-Aufrufer im Code = 0 (`grep` verifiziert)
- [ ] `/admin/printers/` erreichbar, SSO-protected via Pangolin, CSRF-protected (4 Test-Fälle grün)
- [ ] Create/Edit/Disable/Enable funktionieren via Browser (HTML-Forms) + JSON-API (`/api/v1/admin/printers`, Basic-Auth `claude-automation`)
- [ ] Pangolin-Resource `print-hub.example.test` hat **alle Pflicht-Blueprint-Labels** (name, full-domain, protocol, ssl, target+healthcheck, auth.sso-enabled, auth.basic-auth) und Vault-Item `Pangolin Header Auth - Print Hub` mit `claude-automation`-Credentials
- [ ] **Bestand-Backfill verifiziert (H8b):** alle Bestandsdrucker haben `snmp.discover=false`, `snmp.community="public"`, `queue_timeout_s=30`, `cut_defaults_half_cut=0`
- [ ] **PrintService enabled-Check (M8):** `submit_print_job` mit disabled-Drucker → `PrinterDisabledError`/409 + Test-Cases grün
- [ ] **redact_secrets im eigenen Modul `app/services/audit_redaction.py`** (M9) mit ≥80% Coverage und 4 Test-Fällen
- [ ] **SQLite-Engine SERIALIZABLE + WAL** (M7) in `app/db/engine.py` via Connect-Listener
- [ ] Audit-Trail `printers_audit` wird gefüllt, **`connection.snmp.community` redacted** (`***REDACTED***`)
- [ ] `GET /api/printers` unverändert für Hangar, filtert `enabled=true`
- [ ] Fresh-Install-Test: Hub startet ohne YAML mit leerer printers-Tabelle, Operator legt Drucker via UI/API an
- [ ] Production-Smoke: Bestandsdrucker funktional, Container-DNS `print-hub` aus Hangar-Container erreichbar (M10), Print-Buttons in Hangar funktionieren, Healthcheck 200
- [ ] Rollback-Pfad dokumentiert (SQLite-Restore + Compose-Revert + Stack-Env-Merge)
- [ ] Coverage-Schwellen (siehe Testing-Sektion) erreicht, CI-Gate hart (kein `|| true`)
- [ ] Doku: README `printers.yaml` Sektion entfernt, Admin-UI Section ergänzt, deutsch
