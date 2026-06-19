# Hub Printers ENV → DB + Admin-UI Design (Live-State-Reset)

> **Status:** DRAFT Round-1 — Spec-Reset basierend auf Live-State
> **Issue:** [#124 — printers.yaml entfernen, Drucker in DB + Admin-UI](https://github.com/strausmann/Label-Printer-Hub/issues/124)
> **Vorgänger:** [2026-06-14-printers-yaml-to-db-design.md](2026-06-14-printers-yaml-to-db-design.md) — **obsolet** (auf toter Architektur-Annahme basierend)
> **PR:** [#125](https://github.com/strausmann/Label-Printer-Hub/pull/125)
> **Datum:** 2026-06-19
> **ADR-Referenz:** [docs/decisions/0001-two-container-architecture.md](../../decisions/0001-two-container-architecture.md)

## Warum diese Spec neu ist

Die ursprüngliche Spec (2026-06-14) ist ohne Production-Live-Check geschrieben worden. Phase 0 des dazugehörigen Plans hat fundamentale Diskrepanzen aufgedeckt:

| Spec-Annahme (alt) | Production-Realität (Live-Check 2026-06-19) |
|---|---|
| Single-Container `print-hub` | **Two-Container** Backend (Python) + Frontend (Go) — siehe ADR 0001 |
| Stack `hangar-print-hub` | Stack `label-printer-hub` (Pfad: `/docker/stacks/label-printer-hub/`) |
| Domain `print-hub.strausmann.cloud` | `labels.strausmann.cloud` (Pangolin Resource-ID 123) |
| `printers.yaml` lebt im Backend | `printers.yaml` existiert nur in verwaistem `/docker/stacks/hangar-print-hub/config/` — **nicht** im aktuellen Stack gemounted |
| `PrinterConfigLoader` ist aktiv | Production-Image `feat-first-print` hat keinen `PrinterConfigLoader` — Drucker werden aus ENV-Settings gelesen |
| Backend serviert HTML | Backend ist **JSON-only**; Frontend (Go + chi + html/template + HTMX) macht HTML |
| Pangolin-Resource muss neu konfiguriert werden | `resourceId: 123`, `headerAuthId: 8`, SSO+Header-Auth bereits aktiv |

**Konsequenz:** Die Aufgabe ist nicht "YAML → DB", sondern "**ENV-VARS → DB + Admin-UI auf beiden Containern**".

## Ziel

1. **Backend:** Drucker werden aus einer DB-Tabelle `printers` gelesen (statt aus 2 hardcoded Settings-Feldern `pt750w_host` / `ql820_host`). ENV-VARS bleiben als **Bootstrap-Pfad** für Fresh-Installs.
2. **Backend:** Neue JSON-Admin-API `/api/v1/admin/printers` mit Create/Update/Disable/Enable + Audit.
3. **Frontend:** Neue Admin-UI `/admin/printers/` mit Go-Templates + HTMX (analog `/admin/api-keys/`).
4. **Backend:** Public `GET /api/printers` filtert disabled raus (Spec-Forderung).
5. **Soft-Delete** via `enabled=false` — never hard-delete.

**Nicht-Ziele:**

- `printers.yaml` entfernen — die Datei ist bereits irrelevant. Cleanup als optionaler Schritt am Ende.
- `PrinterConfigLoader` entfernen — existiert auf `feat/first-print` Branch ohnehin nicht mehr (lokales `spec/printers-yaml-to-db` ist veralteter Stand).
- Auto-Discovery / Hardware-Verifikation.
- Hangar-seitige Änderungen.
- Domain-Wechsel — `labels.strausmann.cloud` bleibt.

## Live-State (Production hhdocker03)

### Pangolin-Resource (verifiziert via `mcp__pangolin-api__resource_by_resourceId(123)`)

```yaml
resourceId: 123
name: "Label Printer Hub"
niceId: label-printer-hub
fullDomain: labels.strausmann.cloud
subdomain: labels
ssl: true
sso: true
headerAuthId: 8  # Header-Auth bereits konfiguriert
headers:
  - name: x-pangolin-token
    value: 5ad7458b...    # X-Pangolin-Token-Trust-Header
targets:
  - port: 8080
    ip: label-printer-hub-frontend
    hcEnabled: true
    healthStatus: healthy
```

### Stack `label-printer-hub` (Path: `/docker/stacks/label-printer-hub/`)

```yaml
services:
  backend:
    image: ghcr.io/strausmann/label-printer-hub-backend:${HUB_VERSION}
    container_name: label-printer-hub-backend
    ports: ["8095:8000"]   # Host 8095 → Container 8000
    volumes: ["${STACKS_BASE_HOMEDIR}/label-printer-hub/data:/data"]
    healthcheck: curl http://localhost:8000/healthz
```

**HUB_VERSION:** `feat-first-print` (Feature-Branch in Production).

### `.env` (relevante Drucker-Settings)

```bash
PRINTER_HUB_PT750W_HOST=172.16.50.212
PRINTER_HUB_PT750W_PORT=9100
PRINTER_HUB_QL820_HOST=             # leer — QL820 hardware fehlt aktuell
PRINTER_HUB_QL820_PORT=9100
PRINTER_HUB_PRINTER_BACKEND=ptouch
PRINTER_HUB_PRINTER_MODEL=PT-P750W
PRINTER_HUB_PRINTER_DISCOVER_VIA_SNMP=true
PRINTER_HUB_PRINTER_SNMP_COMMUNITY=public
PRINTER_HUB_PRINTER_QUEUE_TIMEOUT_S=30
PRINTER_HUB_DATABASE_URL=sqlite:////data/printer-hub.db
```

### Backend feat/first-print Code-Struktur (relevante Files)

```
backend/
  app/
    config.py              # Settings class — pt750w_host, ql820_host als Felder
    db/
      engine.py            # SQLAlchemy 2 async + aiosqlite
      lifespan.py          # startup/shutdown
    models/
      printer.py           # Printer ORM (id, name, slug, model, backend, connection JSON, enabled, created_at, updated_at)
    repositories/
      printers.py          # async def list_all(session) — kein enabled-Filter aktuell
    api/routes/
      printers.py          # GET /api/printers, /printers/{id}/status, /pause, /resume, /queue/clear
      admin_api_keys.py    # Vorbild für Admin-API-Pattern: /api/admin/api-keys/...
    services/
      print_service.py     # submit_print_job — kein enabled-Check
      printer_identity.py  # derive_printer_id(model, host, port) — 3-arg
    printer_backends/
      exceptions.py        # PrinterError, TapeMismatchError, ...
```

### Frontend feat/first-print Code-Struktur (Go + chi + html/template + HTMX)

```
frontend/
  cmd/server/main.go
  internal/
    api/             # oapi-codegen typed backend client
    handlers/        # chi handlers (dashboard, printers, jobs, templates, lookup)
    proxy/           # /api/* reverse proxy zum Backend
  web/
    templates/
      layout.html             # Base layout
      dashboard.html          # Printer-Grid
      printer.html            # Printer-Detail
      jobs.html / job.html
      templates.html / template.html
      admin_api_keys.html             # ← Vorbild-Pattern für Admin-UI
      admin_api_keys_create.html
      admin_api_keys_detail.html
    static/          # Tailwind-compiled CSS + HTMX JS
```

## Architektur

```
                  ┌─────────────────────────────────────┐
                  │ Operator (Browser)                  │
                  │   labels.strausmann.cloud           │
                  └──────────────┬──────────────────────┘
                                 │ HTTPS, SSO via Pangolin
                  ┌──────────────▼──────────────────────┐
                  │ Pangolin Edge (resourceId 123)      │
                  │ SSO: Remote-User + X-Pangolin-Token │
                  │ Header-Auth-Bypass für claude-      │
                  │   automation (headerAuthId 8)       │
                  └──────────────┬──────────────────────┘
                                 │
                  ┌──────────────▼──────────────────────┐
                  │ Frontend (Go 1.24 + chi + html/    │
                  │ template + HTMX) :8080              │
                  │                                     │
                  │ NEUE Handlers (Issue #124):         │
                  │   GET  /admin/printers/             │
                  │   GET  /admin/printers/new          │
                  │   POST /admin/printers              │
                  │   GET  /admin/printers/{slug}/edit  │
                  │   POST /admin/printers/{slug}       │
                  │   GET  /admin/printers/{slug}/disable │
                  │   POST /admin/printers/{slug}/disable │
                  │   POST /admin/printers/{slug}/enable  │
                  │                                     │
                  │ NEUE Templates (Issue #124):        │
                  │   admin_printers.html               │
                  │   admin_printers_form.html          │
                  │   admin_printers_confirm_disable.html │
                  └──────────────┬──────────────────────┘
                                 │ HTTP intern (BACKEND_URL=http://backend:8000)
                                 │ oapi-codegen typed client
                  ┌──────────────▼──────────────────────┐
                  │ Backend (Python/FastAPI) :8000      │
                  │                                     │
                  │ Existing Endpoints unverändert:     │
                  │   GET /api/printers (NEUER FILTER)  │
                  │   GET /api/printers/{id}/{status,...}│
                  │                                     │
                  │ NEUE JSON-API (Issue #124):         │
                  │   GET    /api/v1/admin/printers     │
                  │   POST   /api/v1/admin/printers     │
                  │   GET    /api/v1/admin/printers/{slug}│
                  │   PUT    /api/v1/admin/printers/{slug}│
                  │   POST   /api/v1/admin/printers/{slug}/disable │
                  │   POST   /api/v1/admin/printers/{slug}/enable  │
                  │                                     │
                  │ Service-Layer:                      │
                  │   PrinterAdminService               │
                  │   printer_admin_bootstrap.py        │
                  │   audit_redaction.py                │
                  └──────────────┬──────────────────────┘
                                 │
                  ┌──────────────▼──────────────────────┐
                  │ SQLite /data/printer-hub.db (WAL)   │
                  │   printers       (existing — erweitert) │
                  │   printers_audit (neu)              │
                  └─────────────────────────────────────┘
```

## Backend-Änderungen

### 1. ENV-Bootstrap statt YAML-Sync

**Phase Startup:**

```
1. Alembic-Migrationen anwenden
2. printer_admin_bootstrap.bootstrap_from_env():
   - Lies pt750w_host, pt750w_port, printer_backend, printer_model,
     printer_snmp_community, printer_queue_timeout_s aus Settings
   - Wenn pt750w_host gesetzt UND noch keine printers-Row mit
     slug="brother-pt750w" existiert: INSERT mit ENV-Werten
   - Dito für ql820_host (slug="brother-ql820nwb")
   - Wenn beide leer: nichts tun (Fresh-Install ohne Drucker)
3. lifespan-Init wie bisher
```

**Bootstrap-Schutz:** Marker `hub_meta.printers_bootstrap_done = 'true'` verhindert dass spätere ENV-Änderungen Bestands-DB-Rows überschreiben. Operator nutzt danach Admin-UI.

### 2. printers-Tabelle erweitern (Alembic-Migration)

Bestehende Spalten:
```python
id (UUID PK), name (unique), slug (unique), model, backend,
connection (JSON), enabled (bool), created_at, updated_at
```

Neue Spalten (Issue #124):
```python
queue_timeout_s (Integer, server_default="30"),
cut_defaults_half_cut (Boolean, server_default=false)
```

Backfill: für jede existing Row ohne `connection.snmp` → setzt `connection.snmp = {discover: false, community: "public"}`.

### 3. printers_audit-Tabelle (neu)

```sql
CREATE TABLE printers_audit (
    id UUID PRIMARY KEY,
    printer_id UUID NOT NULL,       -- kein FK (Soft-Delete behält Row sowieso)
    slug VARCHAR(255) NOT NULL,
    action VARCHAR(50) NOT NULL,    -- 'create'|'update'|'disable'|'enable'|'bootstrap'
    before_json JSON,
    after_json JSON,
    updated_by VARCHAR(255) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_printers_audit_printer_id ON printers_audit(printer_id);
CREATE INDEX idx_printers_audit_created_at_desc ON printers_audit(created_at DESC);
```

`connection.snmp.community` wird via `audit_redaction.py` durch `***REDACTED***` ersetzt.

### 4. derive_printer_id 4-arg

```python
def derive_printer_id(model: str, host: str, port: int, created_at_utc: datetime) -> UUID:
    if created_at_utc.tzinfo is None:
        raise ValueError("created_at_utc must be timezone-aware")
    salt = f"{model}|{host}|{port}|{created_at_utc.isoformat()}"
    return uuid.uuid5(uuid.NAMESPACE_URL, salt)
```

Bestandsdrucker (Bootstrap aus ENV-VARS) behalten die UUID die beim ersten Bootstrap deriviert wurde.

### 5. PrinterDisabledError + 409-Mapping

Analog `TapeMismatchError` in `printer_backends/exceptions.py`:

```python
class PrinterDisabledError(PrinterError):
    def __init__(self, printer_id: UUID, slug: str) -> None:
        self.printer_id = printer_id
        self.slug = slug
        super().__init__(f"Printer {slug} ({printer_id}) is disabled")
```

`PrintService.submit_print_job` prüft `enabled`-Flag und raised `PrinterDisabledError`. `api/routes/print.py` mappt auf HTTP 409.

### 6. JSON-API `/api/v1/admin/printers` (Pattern: `admin_api_keys.py`)

| Endpoint | Auth | Verhalten |
|---|---|---|
| `GET /api/v1/admin/printers?include_disabled=...` | API-Key + admin-Scope | Liste |
| `POST /api/v1/admin/printers` | dito | Create |
| `GET /api/v1/admin/printers/{slug}` | dito | Detail |
| `PUT /api/v1/admin/printers/{slug}` | dito | Update (slug/model/backend silent-ignore) |
| `POST /api/v1/admin/printers/{slug}/disable` | dito | Soft-Delete |
| `POST /api/v1/admin/printers/{slug}/enable` | dito | Reaktivieren |

Pydantic-Schemas mit verschachteltem SNMP (`connection.snmp.{discover,community}`).

### 7. `GET /api/printers` filtert enabled (Round-1 C2 aus alter Spec)

```python
async def list_all(session, *, include_disabled: bool = False) -> list[Printer]:
    stmt = select(Printer).order_by(col(Printer.created_at))
    if not include_disabled:
        stmt = stmt.where(col(Printer.enabled).is_(True))
    ...
```

### 8. OpenAPI-Schema-Update

Backend exportiert `openapi.json`. Frontend nutzt `oapi-codegen` um typed Go-Client zu generieren. Issue #124 fügt 6 neue Endpoints hinzu → Frontend muss `make gen-client` ausführen.

## Frontend-Änderungen (Go)

### 1. Neue Handlers in `frontend/internal/handlers/admin_printers.go`

Analog `admin_api_keys.go`-Pattern:

```go
func (h *Handler) AdminPrintersList(w http.ResponseWriter, r *http.Request) { ... }
func (h *Handler) AdminPrintersNewForm(w http.ResponseWriter, r *http.Request) { ... }
func (h *Handler) AdminPrintersCreate(w http.ResponseWriter, r *http.Request) { ... }
func (h *Handler) AdminPrintersEditForm(w http.ResponseWriter, r *http.Request) { ... }
func (h *Handler) AdminPrintersUpdate(w http.ResponseWriter, r *http.Request) { ... }
func (h *Handler) AdminPrintersDisableConfirm(w http.ResponseWriter, r *http.Request) { ... }
func (h *Handler) AdminPrintersDisable(w http.ResponseWriter, r *http.Request) { ... }
func (h *Handler) AdminPrintersEnable(w http.ResponseWriter, r *http.Request) { ... }
```

### 2. Neue Templates (Tailwind + HTMX)

| Template | Zweck |
|---|---|
| `admin_printers.html` | Tabelle: Name, Slug, Model, Host:Port, Status, Updated-At, Aktionen |
| `admin_printers_form.html` | Create/Edit-Form (slug/model/backend disabled bei Edit) |
| `admin_printers_confirm_disable.html` | Confirm-Page mit POST-Form |

CSRF: Go-Frontend hat eigenen CSRF-Middleware-Stack (`gorilla/csrf` oder eigene Impl). Implementer prüft existing Pattern in `admin_api_keys.html` als Vorbild.

### 3. Routing in `cmd/server/main.go`

```go
r.Route("/admin/printers", func(r chi.Router) {
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

### 4. Auth

Frontend liest `Remote-User` aus Request-Header (Pangolin reicht durch), nutzt das als `updated_by` beim Backend-Call. Backend prüft `Authorization`-Header (API-Key) für den eigentlichen Call (Frontend→Backend nutzt Service-Account-API-Key).

## SQLite-Engine-Setup

```python
# backend/app/db/engine.py
engine = create_async_engine(
    DATABASE_URL,
    isolation_level="SERIALIZABLE",
)

@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
```

WAL ist bereits aktiv in Production (`printer-hub.db-wal`, `-shm` existieren). Listener stellt sicher dass es nach Restart so bleibt.

## Migration für Bestand

### Phase A — Pre-Deploy

1. **DB-Backup:** `docker exec label-printer-hub-backend sqlite3 /data/printer-hub.db '.backup /data/printer-hub.db.bak-pre-124'` + `docker cp` auf Host.
2. **Watchtower-Pause:** `mcp__dockhand__set_container_auto_update(env, "label-printer-hub-backend", policy="never")`. Auch Frontend pausieren.
3. **Compose-Snapshot:** `mcp__dockhand__get_stack_compose("label-printer-hub")` in Phase-0-Doku speichern.

### Phase B — Deploy

1. Alembic-Migration läuft beim Container-Start (Schema-Erweiterung + Audit-Tabelle).
2. Bootstrap-Service liest ENV-VARS und seeded printers-Tabelle (mit `bootstrap`-Audit-Eintrag) falls noch keine Rows existieren.
3. Frontend: neues Image mit `/admin/printers/` Templates.

### Phase C — Smoke-Test

- Backend `GET /healthz` → 200
- `GET /api/printers` → liefert PT-750W aus Bootstrap
- `GET /api/v1/admin/printers` (Admin-API-Key) → liefert PT-750W
- Browser `https://labels.strausmann.cloud/admin/printers/` (SSO) → Liste mit PT-750W
- Create Test-Drucker via UI → erscheint in Liste
- Disable Test-Drucker → verschwindet aus `/api/printers`
- Delete Test-Drucker (Soft-Delete) → Audit-Trail zeigt 3 Rows

### Phase D — Optional Cleanup

- Verwaister `printers.yaml` aus `/docker/stacks/hangar-print-hub/config/` löschen (separater Schritt, kein Block).

### Rollback

DB-Restore + Compose-Revert + Watchtower wieder auf `any`. Details analog alter Spec Phase 8.5.

## Pangolin-Resource

**Wichtig:** Resource existiert bereits komplett konfiguriert.

| Feld | Live-Wert | Issue-#124-Aktion |
|---|---|---|
| `resourceId` | 123 | keine |
| `fullDomain` | labels.strausmann.cloud | keine |
| `headerAuthId` | 8 | keine — Vault-Item-Inhalt prüfen, kein Re-Setup |
| `targets[0].port` | 8080 (Frontend) | keine |
| `sso` | true | keine |
| Healthcheck | `enabled: true, healthy` | keine |

**Operator-Aufgabe in Phase 0:** Vault-Item-Name für `headerAuthId=8` verifizieren. Falls Konvention noch nicht eingehalten: in `Pangolin Header Auth - Label Printer Hub` umbenennen.

## Risiken

| # | Risiko | Mitigation |
|---|---|---|
| R1 | `feat-first-print` Branch in Production läuft auf Code der vom `main`-Branch divergiert. Issue-#124-Implementation muss auf `feat-first-print` aufsetzen, nicht auf `main`. | Branch-Strategie in Plan-Phase 0: working-branch von `origin/feat/first-print` aus erstellen. |
| R2 | Frontend ist Go, niemand im Team hat aktuell Go-Erfahrung dokumentiert | Existing `admin_api_keys.go` als Vorbild kopieren. Pattern ist `gorilla/csrf` + chi + html/template — Standard-Go. |
| R3 | ENV-Bootstrap überschreibt vom Operator gepflegten DB-Stand wenn ENV-VARS bestehen bleiben | Marker `hub_meta.printers_bootstrap_done` + Idempotenz: Bootstrap nur wenn DB leer ODER Marker fehlt. |
| R4 | `oapi-codegen` Re-Generation auf veraltete OpenAPI-Schema | Plan-Phase Backend-Tests vor Frontend-Implementation; `make gen-client` als expliziter Schritt. |
| R5 | Pangolin Header-Auth `headerAuthId=8` mit aktuell unbekanntem User/Password | Phase 0 Live-Check: `mcp__pangolin-api__resource_by_resourceId(123)` zeigt `headers` aber nicht den Basic-Auth-Account selbst. Phase 0 muss klären welcher User/Pass aktiv ist. |
| R6 | Watchtower mit `feat-first-print` Tag re-pullt + ersetzt Container während Migration | Watchtower pausieren Phase A vor Deploy. |

## Out of Scope

- `printers.yaml` aktiv entfernen (Datei ist bereits irrelevant — optional Phase D).
- `PrinterConfigLoader` Code entfernen (existiert auf `feat-first-print` Branch evtl nicht — Implementer prüft).
- Frontend-Authentifizierung (Pangolin macht SSO + Header-Auth).
- Hardware-Auto-Discovery.
- Multi-Tenant.
- Plugin-Discovery für Drucker-Modelle (bleibt Compile-Time wie bisher).
- Hangar-seitige Anpassungen.

## Akzeptanzkriterien

- [ ] Working-Branch ist von `origin/feat/first-print` aus erstellt (nicht von `main`)
- [ ] Alembic-Migration erweitert `printers` um `queue_timeout_s` + `cut_defaults_half_cut`, erstellt `printers_audit`, backfilled `connection.snmp` Defaults
- [ ] `derive_printer_id` ist 4-arg mit timezone-aware Pflicht
- [ ] `PrinterDisabledError` existiert, mapped auf 409 in API-Routes
- [ ] `printers_repo.list_all` hat `include_disabled` Parameter, Default `False`
- [ ] `GET /api/printers` filtert disabled raus (Public-API)
- [ ] `/api/v1/admin/printers` 6 Endpoints funktional, mit API-Key-Auth (admin-Scope)
- [ ] Audit-Trail wird gefüllt; `snmp.community` redacted
- [ ] Bootstrap-Service liest ENV-VARS und seeded DB beim Fresh-Install, Marker `printers_bootstrap_done` verhindert Re-Sync
- [ ] Frontend hat 3 Templates (`admin_printers.html`, `admin_printers_form.html`, `admin_printers_confirm_disable.html`) im Stil von `admin_api_keys.html`
- [ ] Frontend hat 8 Handlers (List, NewForm, Create, EditForm, Update, DisableConfirm, Disable, Enable)
- [ ] Frontend `/admin/printers/` Route registriert in `cmd/server/main.go`
- [ ] OpenAPI-Schema regeneriert, oapi-codegen Client aktualisiert (`make gen-client` grün)
- [ ] Backend-Coverage: `printer_admin_service` 85%, `audit_redaction` 80%, `printer_identity` 85%
- [ ] Frontend-Coverage: Handler-Tests + Template-Smoke-Tests
- [ ] Production-Smoke: Browser `https://labels.strausmann.cloud/admin/printers/` zeigt PT-750W aus ENV-Bootstrap
- [ ] Pangolin-Resource unverändert (resourceId 123, headerAuthId 8 bleiben)
- [ ] Watchtower-Pause vor Deploy, Wiedereinschaltung nach Smoke
- [ ] Rollback-Pfad dokumentiert (DB-Restore + Compose-Revert)
- [ ] Doku in `docs/` aktualisiert (README + ADR-Update zu printers-DB-Architektur)
