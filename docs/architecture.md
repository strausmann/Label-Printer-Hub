# Architecture

Big-picture overview. For the **why** behind every decision, see [`decisions/`](decisions/).

## High-level

```
┌──────────────────────┐  HTTP/JSON  ┌──────────────────────┐  TCP/9100  ┌──────────┐
│  Browser / PWA       │ ──────────► │ Backend (Python)     │ ─────────► │ Printer  │
│  Tailwind, HTMX,     │             │ FastAPI, asyncio     │            │ Brother  │
│  Service Worker      │             │ ptouch / brother_ql  │            │ PT / QL  │
│  Notifications API   │             │ pysnmp, EventBus     │ ◄───────── │          │
└──────────┬───────────┘             │ Print Queue + state  │  passive   └──────────┘
           │                         │ machine              │  status
           │  HTTP/JSON              │                      │
           │  proxied SSE            │                      │  UDP/161 SNMP
           │                         │                      │
┌──────────▼───────────┐             │                      │
│  Frontend (Go)       │ ───────────►│                      │
│  chi/echo, html/     │   HTTP+SSE  │                      │
│  template,           │   passthru  │                      │
│  Tailwind static     │             │                      │
│  PWA assets          │             │                      │
│  oapi-codegen client │             │                      │
└──────────────────────┘             └──────────────────────┘
```

Two containers (ADR [0001](decisions/0001-two-container-architecture.md)):
- `label-printer-hub-backend` — Python/FastAPI; talks to printers, owns the print queue, exposes the JSON API and SSE
- `label-printer-hub-frontend` — Go web server; serves UI + PWA, proxies API and SSE to the backend

Both images version together. Only the frontend is exposed to the user via the deployer's reverse proxy (Traefik / Pangolin / Caddy / standalone — see [`../examples/`](../examples/)).

## Component map

### Backend ([ADR 0002](decisions/0002-python-fastapi-backend.md))

```
backend/app/
├── main.py                  # FastAPI app instantiation
├── api/                     # FastAPI routers (printers, jobs, lookup, webhooks, events)
├── printer_models/          # Plugin per model family (ADR 0004)
│   ├── base.py              # PrinterModel Protocol
│   ├── pt_series.py
│   ├── ql_series.py
│   └── registry.py          # Auto-discovery via SNMP PJL string
├── services/
│   ├── status_block.py      # 32-byte Brother status block parser
│   ├── tape_registry.py     # Brother tape spec lookup table
│   ├── status_probe.py      # Phase-aware status fetcher (ADR 0006)
│   ├── print_queue.py       # asyncio queue + worker per printer (ADR 0005)
│   ├── event_bus.py         # in-memory pub/sub for SSE (ADR 0009)
│   ├── label_renderer.py    # Pillow + qrcode → PIL.Image
│   ├── app_lookup.py        # Snipe-IT / Grocy / Spoolman clients
│   └── template_service.py  # CRUD for label templates
├── models/                  # SQLModel persistence (jobs, templates, printers, ...)
└── seed/                    # Default templates loaded at startup
```

### Frontend ([ADR 0003](decisions/0003-go-tailwind-htmx-pwa-frontend.md))

```
frontend/
├── cmd/server/main.go       # Entry point (chi/echo router)
├── internal/
│   ├── api/                 # oapi-codegen output: types + client (ADR 0011)
│   ├── handlers/            # HTTP handlers, SSE proxy
│   └── templates/           # html/template files
├── web/static/
│   ├── tailwind.css         # Tailwind build output
│   ├── htmx.min.js          # HTMX runtime + SSE extension
│   ├── icons/               # PWA icons
│   ├── manifest.webmanifest # PWA manifest
│   └── sw.js                # Service Worker
└── tests/
```

## Data flows

### Pull mode — user scans a barcode in the UI

1. User opens `https://printerhub.example.com/` (frontend container)
2. Selects a printer tab (e.g. `pt750w`) and an app (e.g. Snipe-IT)
3. Scans a barcode → frontend `GET /api/lookup/snipeit/<id>` (proxied to backend)
4. Backend fetches asset data from Snipe-IT, returns `LabelData`
5. Frontend shows preview via `POST /api/render/preview` → PNG
6. User clicks **Print** → frontend `POST /api/print/<printer>` → backend enqueues job, returns `202` + `job_id`
7. Frontend opens an SSE connection (proxied to backend `/api/events?printer_id=<printer>`)
8. Backend's PrintQueue worker picks up the job, opens TCP/9100 to the printer, sends raster bytes
9. Backend pushes `job` and `status` events on the EventBus → SSE → frontend → browser DOM updates
10. Job completes; SSE event triggers a browser notification (if enabled — [ADR 0010](decisions/0010-pwa-progressive-enhancement.md))

### Push mode — Grocy webhook (only Grocy)

Among the three integrations, only **Grocy** can post webhooks to the hub (and only when `FEATURE_FLAG_LABEL_PRINTING=true` is set in Grocy's `data/config.php`). Snipe-IT and Spoolman do not have webhook-out functionality at the time of this document, so they're pull-only via the hub UI.

1. Grocy posts to `https://printerhub.example.com/api/webhook/grocy`
2. Reverse proxy routes the webhook subroute **without SSO** to the frontend, which proxies to backend
3. Backend validates `X-API-Key`, picks the default layout for `(grocy, default_tape)` (or a `layout_id` override if the payload includes one), fetches label data, renders, enqueues job
4. Returns `202` with job ID; webhook caller doesn't wait for print completion
5. Backend prints; any active SSE consumer sees the live state changes

### Status by phase ([ADR 0006](decisions/0006-status-sources-by-phase.md))

| Phase | Source |
|---|---|
| Pre-print check | TCP/9100 `ESC i S` (32-byte block) |
| Active print | passive read of automatic Brother notifications on the open TCP socket |
| Idle / dashboard | SNMP Display-OID + page counter (every 30 s) |
| Wake-from-sleep | SNMP polled at 1 Hz for up to 30 s |
| Tape changed | SNMP-detected diff → fresh `ESC i S` for full details |

## Print queue ([ADR 0005](decisions/0005-print-queue-is-mandatory.md))

- One `asyncio.Queue` and one worker coroutine **per printer**
- Persisted in SQLite (jobs survive hub restarts)
- States: `queued | paused | printing | completed | failed | cancelled`
- Mid-print cancel **not possible** (Brother spec forbids commands during print)
- Operations: pause/resume/cancel/retry/priority on jobs; pause/resume/clear on the printer worker

## API contract ([ADR 0011](decisions/0011-openapi-as-api-contract.md))

The backend's OpenAPI 3.1 spec is canonical:

| Path | Audience |
|---|---|
| `GET /openapi.json` | Tooling (codegen, Postman, contract tests) |
| `GET /docs` | Swagger UI for interactive try-it-now |
| `GET /redoc` | ReDoc reference rendering |

The Go frontend's typed client is generated from `backend/openapi.json` via `oapi-codegen` at build time. Schema drift is impossible.

## Releases ([ADR 0008](decisions/0008-conventional-commits-and-semantic-release.md))

- Conventional Commits drive version bumps via semantic-release
- Push to `main` → release pipeline: tag → GitHub Release → Docker images on GHCR + Docker Hub
- Tag scheme ([ADR 0007](decisions/0007-docker-image-tag-scheme.md)): every stable release publishes `1.0.0`, `1.0`, `1`, and `latest` — pre-releases get only the full version
- Multi-arch: `linux/amd64` + `linux/arm64`

## SSE EventBus (Phase 6b)

The backend exposes `GET /api/events?printer_id=<uuid>` as a Server-Sent Events
stream. Each printer has three channels (`queue`, `state`, `tape`). The
`EventBus` singleton (on `app.state.event_bus`) fans out `BusEvent` instances
from three producers to all connected SSE subscribers:

| Producer | Channel | Event type |
|---|---|---|
| `PrintQueueProducer` | `printer:{id}:queue` | `job.state_changed` |
| `StatusProbeProducer` | `printer:{id}:state` | `printer.status` |
| `TapeChangeProducer` | `printer:{id}:tape` | `printer.tape_changed` |

HTMX on the QR landing pages connects to the stream and applies each event as
an HTML fragment via `sse-swap`. For reverse-proxy flush configuration required
to make SSE work through Traefik, Caddy, Nginx, and Pangolin, see
[`architecture/sse.md`](architecture/sse.md).

## Reverse-proxy expectations

The frontend container exposes port `8080`. SSE requires response buffering disabled at the reverse proxy (see [`architecture/sse.md`](architecture/sse.md) for Traefik/Caddy/Nginx/Pangolin configuration, and [`../examples/`](../examples/) for full compose examples).

For Pangolin specifically, the **Two-Resources pattern** is used:

1. Main UI: SSO-protected, full domain
2. Webhook subroute (`/api/webhook/`): SSO bypass, authenticated by `WEBHOOK_API_KEY`

## Where things live

| Need | Location |
|---|---|
| Why a decision was made | [`decisions/`](decisions/) ADRs |
| How to deploy the hub | [`getting-started.md`](getting-started.md) (TBD) |
| How to add a new printer model | [`plugin-development.md`](plugin-development.md) (TBD) |
| API reference | `/redoc` on a running backend |
| Brother protocol details | [`research/`](research/) (TBD — to be migrated from maintainer's mono-repo) |
| Privacy and trademark policy | [`policies/`](policies/) |
| Sample deployments | [`../examples/`](../examples/) |
