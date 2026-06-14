# Hub Printers YAML → DB + Admin-UI Design

> **Status:** DRAFT — Spec-Review durch Fachteams ausstehend
> **Issue:** [#124 — printers.yaml entfernen, Drucker in DB + Admin-UI](https://github.com/strausmann/Label-Printer-Hub/issues/124)
> **Related:** Hangar #110 (hardcoded Drucker-/Möbel-Spezifika entfernen)
> **Datum:** 2026-06-14
> **Autor:** Brainstorming-Session mit @strausmann (2026-06-14)

## Ziel

`printers.yaml` und `upsert_runtime_printers()` werden ersatzlos entfernt. Die DB-Tabelle `printers` (existiert seit Migration `b1a0b028aabb`) wird alleinige Source of Truth. Drucker werden ausschließlich über eine neue Admin-UI `/admin/printers/` (analog Hangar `/admin/layouts/`) angelegt, bearbeitet, deaktiviert und gelöscht.

**Nicht-Ziele:**

- Plugin-Architektur ändern (`ptouch`, `brother_ql` bleiben Compile-Time-Plugins — nur die *Drucker-Instanzen* wandern in DB).
- Auto-Discovery (mDNS, ARP, SNMP-Scan) — Operator gibt Hardware-Daten manuell ein.
- Hardware-Verifikation beim Anlegen (User-Wunsch: CSV-Fallback bleibt für Brother P-touch Software).
- Hangar-seitige Änderungen — Hangar konsumiert weiter `GET /api/printers` (5min PrinterSync).
- Env-Bootstrap (`HUB_PRINTERS_JSON`) — explizit verworfen, nur Admin-UI (User 2026-06-14).

## Ausgangslage

| Komponente | Aktuell | Nach #124 |
|---|---|---|
| `printers.yaml` | Source of Truth, beim Start in DB gesynct | **entfernt** |
| `PrinterConfigLoader` | YAML lesen + Cache | **entfernt** |
| `upsert_runtime_printers()` in `lifespan.py:176` | YAML → DB Sync | **entfernt** |
| `derive_printer_id(model, host, port)` | Deterministische UUIDv5 | **erweitert:** `derive_printer_id(model, host, port, created_at)` für **neue** Drucker |
| DB-Tabelle `printers` | existiert, wird beim Start überschrieben | **alleinige Source of Truth** |
| `GET /api/printers` | liest aus DB | unverändert |
| Admin-UI | Keine Web-UI im Hub | **NEU:** `/admin/printers/` (Liste + CRUD) |

### Existing Schema (Migration `b1a0b028aabb` + `da865401716d`)

```sql
CREATE TABLE printers (
    id          UUID PRIMARY KEY,
    name        VARCHAR(255) NOT NULL UNIQUE,
    slug        VARCHAR(255) NOT NULL UNIQUE,
    model       VARCHAR(255) NOT NULL,
    backend     VARCHAR(50)  NOT NULL,
    connection  JSONB        NOT NULL,
    enabled     BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
```

Kein Schema-Migrations-Bedarf für die `printers`-Tabelle selbst. Lediglich eine neue Audit-Tabelle `printers_audit` analog `layouts_audit` (Hangar Phase 1k.1b).

## Architektur

```
                       ┌────────────────────────────┐
                       │  /admin/printers/ (HTML)   │
                       │  Liste · New · Edit · Del  │
                       └─────────────┬──────────────┘
                                     │ Form-Submit (SSO via Pangolin)
                                     ▼
              ┌──────────────────────────────────────────┐
              │  Hub Backend (FastAPI)                   │
              │                                          │
              │  Routes:                                 │
              │   /admin/printers          (HTML Liste) │
              │   /admin/printers/new      (HTML Form)  │
              │   /admin/printers/{slug}/edit           │
              │   POST /admin/printers           (create)│
              │   POST /admin/printers/{slug}    (update)│
              │   POST /admin/printers/{slug}/delete    │
              │                                          │
              │  JSON-API (existing + neu):              │
              │   GET    /api/printers          unchanged│
              │   POST   /api/v1/admin/printers   neu    │
              │   PUT    /api/v1/admin/printers/{slug}   │
              │   DELETE /api/v1/admin/printers/{slug}   │
              │                                          │
              │  Service-Layer:                          │
              │   PrinterAdminService                    │
              │     · create_printer(...)                │
              │     · update_printer(slug, patch)        │
              │     · delete_printer(slug)               │
              │     · list_printers()                    │
              │     · audit_record(...)                  │
              └─────────────┬────────────────────────────┘
                            │
                            ▼
              ┌──────────────────────────────────────────┐
              │  SQLite/Postgres                         │
              │   printers       (existing)              │
              │   printers_audit (neu)                   │
              │   hangar_meta    (existing, für Marker)  │
              └──────────────────────────────────────────┘
                            ▲
                            │ GET /api/printers (5min poll)
                            │
              ┌─────────────┴────────────────────────────┐
              │  Hangar PrinterSync (unverändert)        │
              └──────────────────────────────────────────┘
```

**Entfernt aus Hub:**

- `app/services/printer_config_loader.py`
- `app/db/lifespan.py::upsert_runtime_printers()`
- `app/schemas/printer_config.py` (PrintersFile, PrinterYAMLConfig)
- `/etc/printer-hub/printers.yaml` Volume-Mount im Compose
- `PRINTER_CONFIG_PATH` Env-Variable
- `printers.yaml` aus `/docker/stacks/hangar-print-hub/config/`

**Neu im Hub:**

- `app/services/printer_admin_service.py`
- `app/api/routes/admin_printers.py` (JSON-API)
- `app/web/routes/admin_printers.py` (HTML-UI)
- `app/templates/admin_printers/` (Jinja2-Templates für Liste, Form, Confirm-Delete)
- `app/templates/_base.html` (Layout, falls noch keins existiert)
- Alembic-Migration für `printers_audit` (analog Hangar `layouts_audit`)

## Komponenten

### 1. `PrinterAdminService`

Geschäftslogik isoliert vom Routing. Eine Klasse, klare API:

```python
class PrinterAdminService:
    def __init__(self, session: AsyncSession, audit_user: str):
        self._session = session
        self._audit_user = audit_user

    async def list_printers(self) -> list[Printer]: ...
    async def get_printer(self, slug: str) -> Printer | None: ...
    async def create_printer(self, payload: PrinterCreatePayload) -> Printer: ...
    async def update_printer(self, slug: str, patch: PrinterUpdatePayload) -> Printer: ...
    async def delete_printer(self, slug: str) -> None: ...
```

**ID-Generierung beim Create:**

```python
def derive_printer_id(
    model: str,
    host: str,
    port: int,
    created_at: datetime,
) -> uuid.UUID:
    """UUIDv5 aus Model+Host+Port+Created-At.

    Bestandsdrucker (vor dieser Änderung): created_at war nicht im Salt.
    Diese behalten ihre alte UUID — Migration berechnet sie NICHT neu.

    Neue Drucker (nach dieser Änderung): created_at sorgt dafür dass ein
    Drucker bei IP-Wechsel (DHCP) oder Port-Wechsel eine neue Hardware-
    Instanz mit derselben (model,host,port)-Kombination keine UUID-Kollision
    mit dem alten erzeugt — der alte hat ein anderes created_at.
    """
    salt = f"{model}|{host}|{port}|{created_at.isoformat()}"
    return uuid.uuid5(uuid.NAMESPACE_URL, salt)
```

### 2. Web-Routes (HTML)

`/admin/printers/` zeigt Tabelle aller Drucker (Name, Slug, Model, Host:Port, enabled, Audit-User, updated_at). Pro Zeile Aktionen: "Bearbeiten" und "Löschen".

`/admin/printers/new` zeigt Form für neuen Drucker:

| Feld | Typ | Editierbar nach Create? |
|---|---|---|
| name | Text (required) | Ja |
| slug | Text (required, regex `^[a-z0-9-]+$`) | **Nein** |
| model | Dropdown (gefüllt aus Plugin-Registry) | **Nein** |
| backend | Dropdown (`ptouch`, `brother_ql`) | **Nein** |
| connection.host | Text | Ja |
| connection.port | Number | Ja |
| connection.snmp.discover | Checkbox | Ja |
| connection.snmp.community | Text (default `public`) | Ja |
| queue.timeout_s | Number (default `30`) | Ja |
| cut_defaults.half_cut | Checkbox | Ja |
| enabled | Checkbox (default true) | Ja |

`/admin/printers/{slug}/edit` zeigt Form, vorausgefüllt mit aktuellen Werten. `slug`, `model`, `backend`, `id` sind read-only (analog Hangar Category-Edit-Pattern).

`POST /admin/printers/{slug}/delete` zeigt Confirm-Page; bei zweitem Click harte Löschung mit Audit-Eintrag (analog `/admin/layouts/{category}/delete` in Hangar MR !212).

### 3. JSON-API

Für Automatisierung (Ansible, künftige Tools):

| Endpoint | Auth | Zweck |
|---|---|---|
| `GET /api/v1/admin/printers` | API-Key (admin scope) | Liste |
| `POST /api/v1/admin/printers` | API-Key | Create |
| `GET /api/v1/admin/printers/{slug}` | API-Key | Detail |
| `PUT /api/v1/admin/printers/{slug}` | API-Key | Update |
| `DELETE /api/v1/admin/printers/{slug}` | API-Key | Delete |

Public `GET /api/printers` bleibt unverändert (gibt nur enabled-Drucker an Hangar).

### 4. Plugin-Registry für Model-Dropdown

Druckermodelle sind weiterhin Compile-Time-Plugins. Die Admin-UI braucht eine Liste verfügbarer Modelle für das Dropdown:

```python
# app/printer_backends/registry.py (neu)
@dataclass(frozen=True)
class PrinterModel:
    backend: str           # "ptouch" | "brother_ql"
    model: str             # "PT-P750W" | "QL-820NWB" | ...
    display_name: str      # "Brother PT-P750W (Compact-Tape)"

def list_available_models() -> list[PrinterModel]:
    """Lese aus den Plugin-Modulen — was kennt ptouch_backend, was brother_ql_backend?"""
    ...
```

Quelle: `ptouch.PRINTERS` (ptouch-py) und `brother_ql.MODELS` (brother_ql). Beim ersten Plugin-Load gecached.

### 5. Audit-Tabelle `printers_audit`

```sql
CREATE TABLE printers_audit (
    id          UUID PRIMARY KEY,
    printer_id  UUID NOT NULL,
    slug        VARCHAR(255) NOT NULL,
    action      VARCHAR(50)  NOT NULL,  -- 'create' | 'update' | 'delete'
    before_json JSONB,                   -- NULL bei 'create'
    after_json  JSONB,                   -- NULL bei 'delete'
    updated_by  VARCHAR(255) NOT NULL,   -- aus Pangolin Remote-User Header
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_printers_audit_printer_id ON printers_audit(printer_id);
CREATE INDEX idx_printers_audit_created_at ON printers_audit(created_at DESC);
```

## Data Flow

### Create-Flow

```
1. Operator → /admin/printers/new
2. Hub serviert HTML-Form (Models aus Plugin-Registry)
3. Operator fills + submits → POST /admin/printers
4. Web-Route validiert Pydantic (PrinterCreatePayload)
5. PrinterAdminService.create_printer:
   a. Generiere created_at = now()
   b. printer_id = derive_printer_id(model, host, port, created_at)
   c. INSERT INTO printers (...)
   d. INSERT INTO printers_audit (action='create', before=NULL, after=row_json)
   e. COMMIT
6. Redirect 303 → /admin/printers?info=created&slug=<new-slug>
7. Hangar nächste Sync-Runde (in ≤5min) zieht neuen Drucker via GET /api/printers
```

### Update-Flow

```
1. Operator → /admin/printers/{slug}/edit
2. PrinterAdminService.get_printer(slug) → Row
3. HTML-Form mit aktuellen Werten (slug/model/backend disabled)
4. POST /admin/printers/{slug}
5. PrinterAdminService.update_printer:
   a. SELECT … WHERE slug=? FOR UPDATE
   b. Diff alte vs neue Werte (für Audit)
   c. UPDATE printers SET name=?, connection=?, enabled=?, updated_at=now() WHERE id=?
   d. INSERT INTO printers_audit (action='update', before=old_json, after=new_json)
   e. COMMIT
6. Redirect 303 → /admin/printers?info=updated&slug=<slug>
```

### Delete-Flow

```
1. Operator → Klick "Löschen" in Liste oder Edit
2. /admin/printers/{slug}/delete (GET) zeigt Confirm-Page
3. POST /admin/printers/{slug}/delete
4. PrinterAdminService.delete_printer:
   a. SELECT … WHERE slug=? FOR UPDATE
   b. Wenn nicht existent → 404
   c. INSERT INTO printers_audit (action='delete', before=row_json, after=NULL)
   d. DELETE FROM printers WHERE id=?
   e. COMMIT
5. Redirect 303 → /admin/printers?info=deleted
```

**Implikation für Hangar:** Wenn ein Drucker gelöscht wird, verschwindet er beim nächsten Hangar-Sync aus dem Hangar-Cache. PrintRequests mit der gelöschten Drucker-UUID schlagen mit `404 printer not found` fehl. Operator-Verantwortung: vorher prüfen ob Layouts in Hangar `/admin/layouts/` auf diesen Drucker zeigen.

### Startup-Flow (neu)

`lifespan.py::startup()` macht **keinen** Sync mehr. Nur:

1. Alembic-Migrationen anwenden (inkl. neue `printers_audit`)
2. Konnektivitäts-Check zur DB
3. Markiere `hangar_meta.printers_v2_active = true` (Soft-Marker für Diagnose)

Bei **leerer `printers`-Tabelle** (Fresh-Install): keinerlei Action. Hub startet sauber, `GET /api/printers` liefert `[]`. Operator legt seine Drucker via Admin-UI an.

## Migration für Bestand

```
Phase 1 (vor Deploy): Bestandsdrucker konservieren
  → printers-Tabelle hat aktuelle Drucker mit derivierten UUIDs (Sync läuft heute)
  → Snapshot DB-Inhalt sichern

Phase 2 (Deploy): YAML-Pfad entfernen
  → PrinterConfigLoader-Code entfernen
  → upsert_runtime_printers() entfernen
  → printers.yaml-Mount aus Compose entfernen
  → printers.yaml aus /docker/stacks/hangar-print-hub/config/ löschen

Phase 3 (Verifikation):
  → Hub restartet, GET /api/printers liefert weiterhin alle Bestandsdrucker
  → Hangar PrinterSync läuft, hat keine Drift
  → Operator testet /admin/printers (Liste, Edit auf Bestandsdrucker, ggf. Test-Drucker anlegen+löschen)
```

**Keine Daten-Migration nötig** — die DB ist bereits gefüllt. Migrations-Risiko = Null, weil wir nur eine Schreibquelle entfernen.

## Error Handling

| Fehler | Reaktion |
|---|---|
| Duplicate slug bei Create | 409 mit User-Hinweis "Slug bereits vergeben" |
| Duplicate name bei Create | 409 mit User-Hinweis "Name bereits vergeben" |
| Pydantic-ValidationError | 422 mit Feld-Liste (HTML re-rendert Form mit Fehlern) |
| `slug` nicht gefunden bei Edit/Delete | 404 mit Redirect zu Liste |
| DB-Constraint-Violation | 500 + Sentry-Log |
| Pangolin ohne Remote-User-Header | 403 (Admin-UI verlangt SSO) |
| Plugin-Registry leer | Service-Fehler, Admin-UI zeigt Hinweis "Keine Drucker-Plugins kompiliert" |

## Testing

### Unit-Tests

- `PrinterAdminService.create_printer` Happy + Duplicate-Slug + Duplicate-Name
- `PrinterAdminService.update_printer` Happy + nicht-existent + Versuch slug/model/backend zu ändern → wird ignoriert
- `PrinterAdminService.delete_printer` Happy + nicht-existent
- `derive_printer_id` Determinismus (gleicher Input → gleiche UUID, anderer `created_at` → andere UUID)
- Plugin-Registry: Mock-Plugins → korrekte Liste

### Integration-Tests (TestClient)

- `GET /admin/printers` → HTML mit allen aktiven Druckern
- `POST /admin/printers` → 303 + DB-Row + Audit-Row
- `POST /admin/printers/{slug}` Update → DB-Row aktualisiert + Audit-Row mit before/after
- `POST /admin/printers/{slug}/delete` → DB-Row weg + Audit-Row mit before-Snapshot
- `GET /api/printers` nach Create/Update/Delete → reflektiert Änderungen
- 403 wenn kein Remote-User-Header
- 409 bei Duplicate slug

### E2E-Test (analog `fresh_install_e2e_test.go` in Hangar)

- Frische DB (keine printers.yaml, leere printers-Tabelle)
- Hub startet → keine Errors, `GET /api/printers` → `[]`
- Via TestClient `POST /admin/printers` → Drucker erscheint in `GET /api/printers`
- Restart Hub → Drucker noch da (kein Re-Sync nötig)

### Smoke-Test Production

1. PR merge → CI green
2. Dockhand: `down_stack(hangar-print-hub)` → Volume-Mount `printers.yaml` entfernen via `update_stack_compose` → `start_stack`
3. Browser: `https://print-hub.strausmann.cloud/admin/printers` → Liste der 2 Bestandsdrucker
4. Edit `brother-p750w` → ändere Hostname testweise auf `192.0.2.1` → Save → Reload → Wert übernommen
5. Edit zurück auf echten Hostnamen
6. Hangar `/admin/layouts/` → unverändert, `https://hangar.strausmann.cloud/` Print-Buttons funktionieren

## Risiken & offene Punkte

| # | Risiko | Mitigation |
|---|---|---|
| R1 | Hangar PrinterSync schlägt fehl wenn Drucker gelöscht der noch in Hangar-Layouts referenziert ist | Operator-Verantwortung (siehe Doku); künftig: PrinterAdminService.delete_printer macht HTTP-Check gegen Hangar `/api/admin/layouts?printer_slug=<slug>` (out-of-scope für #124) |
| R2 | API-Key-Auth für JSON-API: existiert schon (`admin_api_keys`)? Welche Scopes? | Im Plan-Schritt prüfen — wenn nicht: separate Admin-API für #124 mit Pangolin-Header-Auth analog Web-Routes |
| R3 | Plugin-Registry: `ptouch.PRINTERS` ist tatsächlich öffentliche API? | Verifikation im Plan-Schritt |
| R4 | Migration entfernt `printers.yaml` aber Stack-Volume bleibt im Backup von PBS | Akzeptabel, file ist klein, kein PII |
| R5 | Bei Multi-Replica-Hub (zukünftig) wäre Audit-User-Tracking pro Request kritisch | Aktuell single-replica, kein Problem |

## Out of Scope (für Issue #124)

- Drucker-Connection-Test-Button in der UI ("Ping printer")
- Bulk-Import (CSV-Upload)
- Drucker-Klonen ("Copy from existing")
- Plugin-Registry über Web-UI sichtbar machen (nur Dropdown)
- Hangar-Side: Layouts-Refs auf gelöschte Drucker proaktiv prüfen → Hangar-Issue separat
- Mehrsprachigkeit der Admin-UI (deutsch only)

## Akzeptanzkriterien

- [ ] `printers.yaml` ist nirgendwo mehr referenziert (Code + Compose + Docs)
- [ ] `PrinterConfigLoader` + `upsert_runtime_printers` sind entfernt + Tests entfernt
- [ ] `/admin/printers/` ist erreichbar (SSO-protected via Pangolin)
- [ ] Create/Edit/Delete funktioniert via Browser + JSON-API
- [ ] Audit-Trail `printers_audit` wird gefüllt
- [ ] `GET /api/printers` unverändert für Hangar
- [ ] Fresh-Install-Test: Hub startet ohne YAML mit leerer printers-Tabelle, Operator legt Drucker via UI an
- [ ] Production-Smoke: Bestandsdrucker bleiben funktional, Print-Buttons in Hangar funktionieren
- [ ] Doku: README `printers.yaml` Sektion entfernt + Admin-UI Section ergänzt
- [ ] Pangolin-Resource-Standard eingehalten (SSO + Header-Auth Bypass für API-Tools)
