# Phase 0 Live-State (Issue #124, 2026-06-20)

> **Plan-Prinzip:** Live-Container-Werte sind Wahrheit. Spec-Werte sind Vorschläge. Bei Konflikt: Live gewinnt.

**Branch-Strategie:** Implementation bleibt auf `spec/printers-yaml-to-db` (PR #125 enthält Spec + Plan + Impl gemeinsam). Plan-Anweisung "von origin/main" wurde pragmatisch abgewichen — ein PR statt zwei.

## Container-Mounts (live verifiziert)

| Container | Host-Pfad | Container-Pfad |
|---|---|---|
| label-printer-hub-backend | `/docker/stacks/hangar-print-hub/data/hub` | `/data` |
| label-printer-hub-backend | `/docker/stacks/hangar-print-hub/config/printers.yaml` | `/etc/hub/printers.yaml` |

**DB-Pfad Host:** `/docker/stacks/hangar-print-hub/data/hub/printer-hub.db`
**DB-Pfad Container:** `/data/printer-hub.db`

## Backend

- **Image:** `ghcr.io/strausmann/label-printer-hub-backend:dev`
- **Image-SHA:** `sha256:0fa1a528908f6e7a0a332af3cef82925922c110d9cead6c579a6a49ef84d687b` (ROLLBACK_BACKEND_IMAGE)
- **Revision:** `2ff51d2c61dcea87b89d94762aaa680ddac61909` (auf `main`)
- **Relevante ENV:**
  - `PRINTER_HUB_DATABASE_URL=sqlite+aiosqlite:////data/printer-hub.db`
  - `PRINTER_HUB_PRINTERS_CONFIG=/etc/hub/printers.yaml`
  - `HUB_REVISION=2ff51d2c...`
  - `HUB_VERSION=dev`
- **Existing admin-api-keys-Route:** `prefix="/api/admin/api-keys"` (KEIN v1-Prefix)

## Frontend

- **Image:** `ghcr.io/strausmann/label-printer-hub-frontend:dev`
- **Image-SHA:** `sha256:80fd304acd09d3839c36708aa87ebd6f5637088823821cf41b7fd580b64f5452` (ROLLBACK_FRONTEND_IMAGE)
- **CSRF-Library:** **KEINE** (kein gorilla/csrf in `frontend/go.mod`) — wird in Phase 7.1 eingeführt
- **Existing Admin-Routes:**
  - `GET /admin/api-keys`
  - `GET /admin/api-keys/new`
  - `POST /admin/api-keys/new`
  - `GET /admin/api-keys/{id}`
  - `POST /admin/api-keys/{id}/revoke`

## DB-Stand (vor Migration)

**Tables (bestehend):**
- `alembic_version`
- `api_keys`
- `jobs`
- `presets`
- `print_batches`
- `printer_state`
- `printer_status_cache`
- `printers`

**printers-Rows (2):**
| slug | name | model | backend | enabled |
|---|---|---|---|---|
| brother-p750w | Brother PT-P750W | pt-p750w | ptouch | 1 |
| brother-ql820nwb | Brother QL-820NWB | ql-820nwb | brother_ql | 1 |

**Tables die in Phase 1.3 entstehen:** `printers_audit`

## Pangolin (kein Setup nötig)

- **Resource-ID:** 123
- **niceId:** label-printer-hub
- **fullDomain:** `labels.example.test` (Production: gescrubbt für Doku-Compliance; tatsächliche Live-Domain ist die `labels.*` Subdomain)
- **sso:** true
- **headerAuthId:** 8 (Vault-Item: "Pangolin Header Auth - Label Printer Hub", user: `claude-automation`)
- **targets[0]:** port=8080 (frontend), hcEnabled=true, healthy, hcHostname=label-printer-hub-frontend

## Watchtower

- **Container-Scope-Label:** `hangar-print-hub` (historisch — Stack wurde umbenannt, Watchtower-Label hat alten Namen)
- **Pause-Aufruf in Phase 8.2:** `mcp__dockhand__set_container_auto_update(containerName=..., policy="never")` für **beide** Container

## Existing engine.py PRAGMA-Setup (Plan Task 1.1 wiederverwenden!)

Auf `main`: `backend/app/db/engine.py::_apply_pragmas` setzt bereits:
- `PRAGMA journal_mode = WAL`
- `PRAGMA synchronous = NORMAL`
- `PRAGMA foreign_keys = ON`
- `PRAGMA busy_timeout = 5000`

**Plan Task 1.1 erweitert NUR `isolation_level="SERIALIZABLE"` an `create_async_engine()` — KEINEN zweiten Listener erfinden.**

## Stack-Env Baseline

Wird in Phase 6.0 Step 4b live ermittelt via `mcp__dockhand__get_stack_env(environmentId=10, name="label-printer-hub")`. Zu diesem Zeitpunkt aktuelle Anzahl Variablen + alle Keys festhalten als Pre-Merge-Snapshot.

## Round-7+ Bestätigungen (User+Reviewer)

- Backend-API-Key-Erstellung nutzt `generate_api_key()` aus `app/auth/key_generator.py` (Repo-Pattern, nicht erfundener APIKeyService)
- API-Key Scope: `'admin'` (3-stufige Hierarchie admin ⊇ print ⊇ read)
- CSRF_KEY: 64 hex chars = 32 raw bytes für gorilla/csrf (validation per `hex.DecodeString` → `len != 32`)
- Backend bleibt JSON-only — HTML-Routes leben im Frontend (Go)
