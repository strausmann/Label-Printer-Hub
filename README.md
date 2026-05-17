# Label Printer Hub

[![CI](https://github.com/strausmann/Label-Printer-Hub/actions/workflows/ci.yml/badge.svg)](https://github.com/strausmann/Label-Printer-Hub/actions/workflows/ci.yml)
[![CodeQL](https://github.com/strausmann/Label-Printer-Hub/actions/workflows/codeql.yml/badge.svg)](https://github.com/strausmann/Label-Printer-Hub/actions/workflows/codeql.yml)
[![codecov](https://codecov.io/github/strausmann/Label-Printer-Hub/graph/badge.svg?token=JRG4PDU2QX)](https://codecov.io/github/strausmann/Label-Printer-Hub)
[![CLA assistant](https://cla-assistant.io/readme/badge/strausmann/Label-Printer-Hub)](https://cla-assistant.io/strausmann/Label-Printer-Hub)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-yellow.svg)](https://conventionalcommits.org)
[![semantic-release](https://img.shields.io/badge/%20%20%F0%9F%93%A6%F0%9F%9A%80-semantic--release-e10079.svg)](https://github.com/semantic-release/semantic-release)
[![GitHub Issues](https://img.shields.io/github/issues/strausmann/label-printer-hub)](https://github.com/strausmann/label-printer-hub/issues)

> Self-hosted multi-printer hub for Brother PT-Series and QL-Series label printers. Pull-mode (user scans barcode) and push-mode (Spoolman/Grocy webhooks). Integrates with Snipe-IT, Grocy, Spoolman. Plugin-based architecture for additional printer models. PWA-ready for smartphone use.

## Status

**Early development.** See [open issues](https://github.com/strausmann/label-printer-hub/issues) for progress and the [master tracking issue #22](https://github.com/strausmann/label-printer-hub/issues/22) for the phase roadmap.

This project is being designed against the [Brother PT-E550W/P750W/P710BT Raster Command Reference v1.02](https://download.brother.com/welcome/docp100064/cv_pte550wp750wp710bt_eng_raster_102.pdf) and [QL-800/810W/820NWB Raster Command Reference](https://download.brother.com/welcome/docp100278/cv_ql800_eng_raster_101.pdf). Hardware tested: Brother PT-P750W (verified). Brother QL-820NWBc (in progress).

## Features (planned)

- **Multi-printer support** via plugin architecture (PT-Series and QL-Series, more on request)
- **Pull-mode**: Open the web UI on your phone, scan a barcode, hit print
- **Push-mode**: Spoolman/Grocy webhook → automatic label print
- **App integrations**: Snipe-IT (asset tags), Grocy (product labels), Spoolman (3D-print spool labels)
- **Print queue** with pause/resume/cancel/retry/priority operations
- **Live status pages** per printer via Server-Sent Events (no page reload)
- **Tape detection** via Brother native status block (no manual configuration)
- **PWA-installable** for smartphone use
- **Pluggable**: drop a new `printer_models/your_model.py` to add a new device

## Tech Stack

**Two-container split:** backend (printer protocols, queue, API) and frontend (UI, PWA) are separate containers. They release together at the same semver version, communicate over HTTP/JSON, and the frontend proxies SSE for live status updates.

- **Backend** (`label-printer-hub-backend`): Python 3.12+, FastAPI, SQLModel (SQLite), asyncio
- **Printer protocols**: `nbuchwitz/ptouch` (PT-Series), `pklaus/brother_ql` (QL-Series), `pysnmp` for status polling
- **Frontend** (`label-printer-hub-frontend`): Go web server, Tailwind CSS, HTMX, PWA (manifest + service worker + Web Notifications API)
- **Container**: Docker (multi-stage per service), GHCR + Docker Hub publishing, multi-arch (amd64 + arm64)
- **CI/CD**: GitHub Actions, semantic-release, Dependabot

## Container images and tags

Every stable release publishes to **GitHub Container Registry (GHCR)** and **Docker Hub** with this tag scheme:

| Tag | Example for `1.0.0` | Use when |
|---|---|---|
| `1.0.0` | exact version | You want full reproducibility |
| `1.0` | latest patch in 1.0.x | Auto-update bug fixes |
| `1` | latest minor.patch in 1.x.x | Stay on major version, get features |
| `latest` | most recent stable | You're fine with anything new |

Pre-releases (`1.0.0-rc.1` etc.) publish **only the full version tag** — never `latest`, `<major>`, or `<major>.<minor>` — so a pre-release can never silently become the default.

Both registries receive identical multi-arch images (`linux/amd64`, `linux/arm64`).

## Quick Start

See [`examples/README.md`](examples/README.md) for sample compose files (standalone / Traefik / Pangolin / Caddy). For early-development testing of the REST API alone — without the frontend — see [`examples/compose.backend-only.yml`](examples/compose.backend-only.yml):

```bash
# Backend-only (builds the image from source — no GHCR pull required):
git clone --branch main https://github.com/strausmann/label-printer-hub.git
cd label-printer-hub
cp backend/.env.example .env
$EDITOR .env                # set PRINTER_HUB_PT750W_HOST and friends
docker compose -f examples/compose.backend-only.yml up -d --build

# REST API smoke
curl http://localhost:8090/healthz
curl -X POST http://localhost:8090/print -H 'Content-Type: application/json' \
  -d '{"template_id":"qr-only-12mm","data":{"title":"Smoke","primary_id":"SMOKE-001","qr_payload":"https://example.test"}}'
```

To build and run the **full stack** (backend + frontend) from source without any real printer hardware, use the smoke-test compose file:

```bash
# Full-stack local smoke test (mock printer, no hardware required):
docker compose -f dev/docker-compose.smoke.yml up --build

# UI is served at http://localhost:8080
# Verify both services are healthy:
curl http://localhost:8080/healthz   # frontend → backend_reachable: true
```

## REST API surface

| Method | Path | Purpose | Body |
|---|---|---|---|
| `POST` | `/print` | Submit a print job | `PrintRequest` (see below) |
| `GET` | `/jobs/{job_id}` | Poll job status (includes live SNMP block while printing) | — |
| `POST` | `/jobs/{job_id}/resume` | Resume a job paused by tape mismatch (after the user changed the tape physically) | — |
| `POST` | `/printer/resume` | Resume the printer queue after a recoverable error halted it (tape empty / cover open / offline) | — |
| `GET` | `/healthz` | Liveness probe for orchestrators | — |
| `GET` | `/readiness` | Readiness probe — deep check for reverse-proxy routing | — |

### Health Probes

The backend exposes two HTTP probes with different semantics:

| Endpoint | Purpose | What it answers |
|----------|---------|-----------------|
| `GET /healthz` | Liveness — Docker / Kubernetes container restart signal | "the process and the event loop are alive" |
| `GET /readiness` | Readiness — reverse-proxy routing signal | "the process can serve traffic right now": database connectable, alembic at head, templates seeded, runtime printer matches DB, SNMP probe fresh, queue worker alive, SSE bus capacity ok |

`/readiness` returns HTTP 200 with `status` of `ready` (all checks ok) or `degraded` (non-critical checks failing — still routable), and HTTP 503 with `not-ready` when a critical check (database, alembic, template_seed) fails.

Pangolin's `targets[0].healthcheck.path` can use `/readiness` for deep checks instead of `/healthz`; Docker container healthchecks should stay on `/healthz` to avoid restart loops on transient DB failures.

See `docs/superpowers/specs/2026-05-17-phase-7b-foundation-design.md` for the full check list and rationale.

### `POST /print` request body

```jsonc
{
  "template_id": "qr-only-12mm",         // id from app/seed/templates/<id>.yaml
  // Exactly one of `lookup` or `data` is required.
  "lookup":  { "app": "snipeit", "identifier": "123" },
  "data":    { "title": "Asset 123",
               "primary_id": "ASSET-123",
               "qr_payload": "https://snipe.example/assets/123",
               "secondary": ["optional", "extra lines"] },
  "options": { "copies": 1,              // 1..10, default 1
               "auto_cut": true,
               "high_resolution": false },
  // Default "fail" → synchronous 409 + error_detail{expected_mm, loaded_mm}.
  // "queue"        → 202 + job_id; job lands in PAUSED until the user POSTs
  //                  /jobs/{id}/resume after physically swapping the tape.
  "on_tape_mismatch": "fail"
}
```

### Synchronous error codes (`POST /print`)

| HTTP | `error_code` | When |
|---|---|---|
| 404 | `template_not_found` | unknown `template_id` |
| 409 | `tape_mismatch` | loaded tape ≠ template tape, `on_tape_mismatch="fail"` |
| 409 | `tape_empty` | preflight detects no media |
| 409 | `printer_cover_open` | preflight detects cover open |
| 502 | `integration_lookup_failed` | integration plugin raised |
| 503 | `printer_offline` | SNMP preflight could not reach the printer |

`tape_mismatch` responses include `error_detail: {expected_mm, loaded_mm}` so the client can build a "swap the tape" dialog.

## Environment variables

Full reference lives in [`backend/.env.example`](backend/.env.example). The most-used variables grouped by purpose:

| Variable | Default | Purpose |
|---|---|---|
| `PRINTER_HUB_DATABASE_URL` | `sqlite:////data/printer-hub.db` | SQLite path (Phase-5 persistence; ignored today) |
| `PRINTER_HUB_PT750W_HOST` | _empty_ | Brother PT-P750W IP/hostname (required when `printer_backend=ptouch`) |
| `PRINTER_HUB_PT750W_PORT` | `9100` | TCP print port |
| `PRINTER_HUB_QL820_HOST` | _empty_ | Brother QL-820NWB IP (when QL backend lands) |
| `PRINTER_HUB_QL820_PORT` | `9100` | TCP print port |
| **`PRINTER_HUB_PRINTER_BACKEND`** | `ptouch` | Transport: `ptouch` \| `mock` \| third-party entry-point id |
| **`PRINTER_HUB_PRINTER_MODEL`** | `PT-P750W` | Fallback model id when SNMP discovery is off / unreachable |
| **`PRINTER_HUB_PRINTER_DISCOVER_VIA_SNMP`** | `true` | SNMP-first model discovery via Brother private OID, fall back to `PRINTER_HUB_PRINTER_MODEL` on failure |
| **`PRINTER_HUB_PRINTER_SNMP_COMMUNITY`** | `public` | SNMPv2c community (LAN-only — read-only) |
| **`PRINTER_HUB_PRINTER_QUEUE_TIMEOUT_S`** | `30` | Graceful shutdown timeout for the print queue |
| `PRINTER_HUB_WEBHOOK_API_KEY` | _empty_ | Bearer for inbound integration webhooks (≥ 32 chars; generate with `openssl rand -hex 32`) |
| `PRINTER_HUB_SNIPEIT_URL` | _empty_ | Snipe-IT base URL |
| `PRINTER_HUB_SNIPEIT_API_KEY` | _empty_ | Snipe-IT bearer token |
| `PRINTER_HUB_GROCY_URL` | _empty_ | Grocy base URL |
| `PRINTER_HUB_GROCY_API_KEY` | _empty_ | Grocy API key |
| `PRINTER_HUB_SPOOLMAN_URL` | _empty_ | Spoolman base URL (no auth) |
| `PRINTER_HUB_SERVER_PORT` | `8090` | Internal port (overridden to `8000` in the container — see Dockerfile) |
| `PRINTER_HUB_LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

All variables share the `PRINTER_HUB_` prefix and map 1:1 to the `Settings` model in `backend/app/config.py`.

## Documentation

**In this repository (engineering — change with code):**

- [Architecture overview](docs/architecture.md) — how the pieces fit
- [Decisions (ADRs)](docs/decisions/) — *why* each architectural choice was made
- [Plugin development](docs/plugin-development.md) (TBD) — adding new printer models
- [Privacy policy](docs/policies/privacy.md), [Trademark policy](docs/policies/trademarks.md)
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — Conventional Commits, TDD, PR workflow

**On the wiki (tutorials and platform recipes — community-friendly):**

- [Getting started](https://github.com/strausmann/label-printer-hub/wiki/Getting-Started)
- [Snipe-IT integration](https://github.com/strausmann/label-printer-hub/wiki/Snipe-IT-Integration)
- [Grocy integration](https://github.com/strausmann/label-printer-hub/wiki/Grocy-Integration)
- [Spoolman integration](https://github.com/strausmann/label-printer-hub/wiki/Spoolman-Integration)
- [Install as PWA](https://github.com/strausmann/label-printer-hub/wiki/Install-as-PWA) (TBD)
- [Troubleshooting](https://github.com/strausmann/label-printer-hub/wiki/Troubleshooting) (TBD)

**Live API reference** (when running): `/openapi.json`, `/docs` (Swagger UI), `/redoc` — see [ADR 0011](docs/decisions/0011-openapi-as-api-contract.md).

## Contributing

Contributions are welcome — especially **printer model plugins**. See [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow (Conventional Commits, TDD, semantic-release).

## Trademarks and disclaimer

> **Brother**, **P-touch**, **PT-Series**, and **QL-Series** are trademarks or registered trademarks of **Brother Industries, Ltd.** All other trademarks are the property of their respective owners.
>
> This project is **not affiliated with, endorsed by, or sponsored by Brother Industries, Ltd.** It is an independent open-source project that interoperates with Brother label printers via documented protocols (Brother Raster Command Reference, IEEE 802.3, RFC 3805 SNMP Printer-MIB, RFC 8011 IPP).
>
> "Brother" is used in this README solely for the purpose of describing the hardware that this software is compatible with. No commercial use of the Brother trademarks is intended.

## License

This project is licensed under the **MIT License** — see [LICENSE](LICENSE) for details.

The Brother Raster Command Reference PDFs distributed in this repository (under `docs/research/brother-spec/`, if present) remain the property of Brother Industries, Ltd. Their inclusion is a verbatim, unmodified copy redistributed under fair use for development reference. The Brother documentation license terms apply to those files.

## Acknowledgements

- [`pklaus/brother_ql`](https://github.com/pklaus/brother_ql) — QL-Series Python library
- [`nbuchwitz/ptouch`](https://github.com/nbuchwitz/ptouch) — PT-Series Python library
- [`donkie/Spoolman`](https://github.com/donkie/Spoolman), [Grocy](https://github.com/grocy/grocy), [Snipe-IT](https://github.com/snipe/snipe-it) — apps this hub integrates with
