# Architecture

Big-picture overview. For the **why** behind every decision, see [`decisions/`](decisions/).

## High-level

```
┌──────────────────────┐  HTTP/JSON  ┌──────────────────────────────┐  TCP/9100  ┌──────────┐
│  Browser / PWA       │ ──────────► │ Hub (one Python process)     │ ─────────► │ Printer  │
│  React + TypeScript  │   + SSE     │ FastAPI, asyncio             │            │ Brother  │
│  Service Worker      │ ◄────────── │ serves API, /api/v1/events   │ ◄───────── │ PT / QL  │
│  Camera scanning     │             │ and the built web UI         │  passive   └──────────┘
└──────────────────────┘             │ Print Queue + state machine  │  status
                                     │ SQLite, EventBus             │  UDP/161 SNMP
                                     └──────────────────────────────┘
```

One container (ADR [0015](decisions/0015-single-process-deployment.md), which supersedes ADR [0001](decisions/0001-two-container-architecture.md)):
- `label-printer-hub-backend` — Python/FastAPI; talks to printers, owns the print queue, exposes the JSON API, the JSON event stream and the static web UI (with a fallback to `index.html` for client routes)

The web UI is built from `frontend/` at image build time (multi-stage Dockerfile, build context = repository root) and copied into the image; there is no separate frontend process or image. The deployer's reverse proxy (Traefik / Pangolin / Caddy / standalone — see [`../examples/`](../examples/)) points straight at the hub on port 8000. Printers, integrations and keys are managed in the UI and stored in the database (ADR [0017](decisions/0017-settings-in-database-env-locks-encrypted-secrets.md)); secrets are encrypted with `PRINTER_HUB_SECRET_KEY`.

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

### Web UI ([ADR 0016](decisions/0016-react-typescript-web-ui.md), supersedes [0003](decisions/0003-go-tailwind-htmx-pwa-frontend.md))

```
frontend/
├── src/
│   ├── app/                 # router, session, query client, update prompt
│   ├── api/                 # client, event stream, types generated from the OpenAPI contract (ADR 0011)
│   ├── features/            # overview, printers, jobs, integrations, lookup, scan, search, settings
│   ├── shell/, pages/       # app shell (sidebar / tab bar) and page frames
│   ├── design/              # design tokens (spec 5.2)
│   └── i18n/                # message catalogues (English default)
├── public/                  # PWA icons, manifest
└── e2e/                     # Playwright specs against the real backend (mock printers)
```

Browsers sign in with an API key (or proxy SSO) and receive a session cookie with CSRF protection ([ADR 0019](decisions/0019-proxy-headers-need-trust-token.md) for the trust rules).

## Data flows

### Pull mode — user scans a barcode in the UI

1. User opens `https://printerhub.example.com/` (served by the hub)
2. Selects a printer tab (e.g. `pt750w`) and an app (e.g. Snipe-IT)
3. Scans a barcode or opens a label link (`/asset/<id>`) → the UI calls `GET /api/v1/lookup/snipeit/<id>`
4. Backend fetches asset data from Snipe-IT, returns `LabelData`
5. The UI shows a preview rendered by the backend
6. User clicks **Print** → `POST /api/v1/print` → backend enqueues job, returns `202` + `job_id`
7. The UI already holds one SSE connection to `/api/v1/events` for the whole tab
8. Backend's PrintQueue worker picks up the job, opens TCP/9100 to the printer, sends raster bytes
9. Backend pushes `job` and `status` events on the EventBus → SSE (JSON frames) → the UI updates its data in place
10. Job completes; SSE event triggers a browser notification (if enabled — [ADR 0010](decisions/0010-pwa-progressive-enhancement.md))

### Push mode — Grocy webhook (only Grocy)

Among the three integrations, only **Grocy** can post webhooks to the hub (and only when `FEATURE_FLAG_LABEL_PRINTING=true` is set in Grocy's `data/config.php`). Snipe-IT and Spoolman do not have webhook-out functionality at the time of this document, so they're pull-only via the hub UI.

1. Grocy posts to `https://printerhub.example.com/api/v1/webhook/grocy`
2. Reverse proxy routes the webhook subroute **without SSO** to the hub
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
- Mid-print cancel **not possible** for tape printers (Brother spec forbids commands during print). IPP page printers can cancel a printing job (Cancel-Job, [ADR 0020](decisions/0020-backend-kinds-ipp-page-printers.md))
- Page jobs (IPP printers) are tracked at the printer until a final state and are settled after a restart from what the printer reports; tape jobs in `printing` become `failed_restart`
- Operations: pause/resume/cancel/retry/priority on jobs; pause/resume/clear on the printer worker

## API contract ([ADR 0011](decisions/0011-openapi-as-api-contract.md))

The backend's OpenAPI 3.1 spec is canonical:

| Path | Audience |
|---|---|
| `GET /openapi.json` | Tooling (codegen, Postman, contract tests) |
| `GET /docs` | Interactive API reference (Scalar, served by the hub, no CDN) |

The web UI's API types are generated from the backend's OpenAPI document (`pnpm gen:api`), and CI fails when the generated client no longer matches the contract.

## Releases ([ADR 0008](decisions/0008-conventional-commits-and-semantic-release.md))

- Conventional Commits drive version bumps via semantic-release
- Push to `main` → release pipeline: tag → GitHub Release → Docker image on GHCR + Docker Hub
- Tag scheme ([ADR 0007](decisions/0007-docker-image-tag-scheme.md)): every stable release publishes `1.0.0`, `1.0`, `1`, and `latest` — pre-releases get only the full version
- Multi-arch: `linux/amd64` + `linux/arm64`

## SSE EventBus

The backend exposes `GET /api/v1/events[?printer_id=<uuid>]` as a Server-Sent Events
stream of JSON frames. The `EventBus` singleton (on `app.state.event_bus`) fans out
`BusEvent` instances from the producers to all connected subscribers:

| Producer | Channel | Event type |
|---|---|---|
| `PrintQueueProducer` | `printer:{id}:queue` | `job.state_changed` |
| `StatusProbeProducer` | `printer:{id}:state` | `printer.status` |
| `TapeChangeProducer` | `printer:{id}:tape` | `printer.tape_changed` |
| admin printer API | `hub` | `hub.printers_changed` |

The stream starts with a snapshot per visible printer, authenticates like every
`read` route, and ends with `auth.expired` when the credentials stop being valid.
Frame format and reverse-proxy flush configuration for Traefik, Caddy, Nginx and
Pangolin: [`architecture/sse.md`](architecture/sse.md). The earlier HTML-fragment
stream `/api/events` (for HTMX) no longer exists.

## Reverse-proxy expectations

The hub listens on port `8000` inside its container and serves the UI and the API on it. SSE requires response buffering disabled at the reverse proxy (see [`architecture/sse.md`](architecture/sse.md) for Traefik/Caddy/Nginx/Pangolin configuration, and [`../examples/`](../examples/) for full compose examples).

For Pangolin specifically, the **Two-Resources pattern** is used:

1. Main UI: SSO-protected, full domain; the resource injects the trust token header the hub requires (`PRINTER_HUB_SSO_TRUST_TOKEN`)
2. Webhook subroute (`/api/v1/webhook/`): SSO bypass, authenticated by `PRINTER_HUB_WEBHOOK_API_KEY`

Upgrading from the two-container release: [`migration/v-next-single-container.md`](migration/v-next-single-container.md).

## Where things live

| Need | Location |
|---|---|
| Why a decision was made | [`decisions/`](decisions/) ADRs |
| How to deploy the hub | [`getting-started.md`](getting-started.md) (TBD) |
| How to add a new printer model | [`plugin-development.md`](plugin-development.md) (TBD) |
| API reference | `/docs` on a running hub |
| Brother protocol details | [`research/`](research/) (TBD — to be migrated from maintainer's mono-repo) |
| Privacy and trademark policy | [`policies/`](policies/) |
| Sample deployments | [`../examples/`](../examples/) |
