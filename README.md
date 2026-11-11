# Label Printer Hub

[![CI](https://github.com/strausmann/Label-Printer-Hub/actions/workflows/ci.yml/badge.svg)](https://github.com/strausmann/Label-Printer-Hub/actions/workflows/ci.yml)
[![CodeQL](https://github.com/strausmann/Label-Printer-Hub/actions/workflows/codeql.yml/badge.svg)](https://github.com/strausmann/Label-Printer-Hub/actions/workflows/codeql.yml)
[![codecov](https://codecov.io/github/strausmann/Label-Printer-Hub/graph/badge.svg)](https://codecov.io/github/strausmann/Label-Printer-Hub)
[![CLA assistant](https://cla-assistant.io/readme/badge/strausmann/Label-Printer-Hub)](https://cla-assistant.io/strausmann/Label-Printer-Hub)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-yellow.svg)](https://conventionalcommits.org)
[![semantic-release](https://img.shields.io/badge/%20%20%F0%9F%93%A6%F0%9F%9A%80-semantic--release-e10079.svg)](https://github.com/semantic-release/semantic-release)
[![GitHub Issues](https://img.shields.io/github/issues/strausmann/label-printer-hub)](https://github.com/strausmann/label-printer-hub/issues)

> Self-hosted multi-printer hub for Brother PT-Series and QL-Series label printers. Pull-mode (user scans barcode) and push-mode (Spoolman/Grocy webhooks). Integrates with Snipe-IT, Grocy, Spoolman. Plugin-based architecture for additional printer models. PWA-ready for smartphone use.

## Status

**Early development.** See [open issues](https://github.com/strausmann/label-printer-hub/issues) for progress and the [master tracking issue #22](https://github.com/strausmann/label-printer-hub/issues/22) for the phase roadmap.

This project is being designed against the [Brother PT-E550W/P750W/P710BT Raster Command Reference v1.02](https://download.brother.com/welcome/docp100064/cv_pte550wp750wp710bt_eng_raster_102.pdf) and [QL-800/810W/820NWB Raster Command Reference](https://download.brother.com/welcome/docp100278/cv_ql800_eng_raster_101.pdf). Hardware tested: Brother PT-P750W (verified). Brother QL-820NWBc (in progress).

## Features

- **Multi-printer support** via plugin architecture (PT-Series and QL-Series, more on request)
- **Printers added and changed at runtime** in the UI (Settings > Printers), no restart and no environment variables (#224)
- **Pull-mode**: Open the web UI on your phone, scan a barcode, hit print
- **Push-mode**: Spoolman/Grocy webhook → automatic label print
- **App integrations**: Snipe-IT (asset tags), Grocy (product labels), Spoolman (3D-print spool labels)
- **Print queue** with pause/resume/cancel/retry operations, per printer and per job; tape runs in sub-jobs that
  stop at an unknown outcome and offer continue or reprint (#277)
- **Live status pages** per printer via Server-Sent Events (no page reload)
- **Tape detection** via Brother native status block (no manual configuration)
- **PWA-installable** for smartphone use, also behind SSO (#225)
- **Versioned API** under `/api/v1/` (#226)
- **Pluggable**: drop a new `printer_models/your_model.py` to add a new device

Not built yet: job priorities in the queue.

## Tech Stack

**One container:** a single backend process serves the REST API, the live event stream and the web UI ([ADR 0015](docs/decisions/0015-single-process-deployment.md)). Printers are added in the UI (Settings > Printers), not through environment variables.

- **Backend** (`label-printer-hub-backend`, the only image): Python 3.12+, FastAPI, SQLModel (SQLite), asyncio
- **Printer protocols**: `nbuchwitz/ptouch` (PT-Series), `pklaus/brother_ql` (QL-Series), `pysnmp` for status polling; an own IPP client over `httpx` for page printers ([ADR 0020](docs/decisions/0020-backend-kinds-ipp-page-printers.md)), with `reportlab` drawing the PDF pages
- **Web UI** (built into the backend image from `frontend/`): React + TypeScript, Vite, PWA (manifest + service worker + camera scanning) — [ADR 0016](docs/decisions/0016-react-typescript-web-ui.md)
- **Container**: Docker (multi-stage, one image), GHCR + Docker Hub publishing, multi-arch (amd64 + arm64)
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

See [`examples/README.md`](examples/README.md) for sample compose files (standalone / Traefik / Pangolin / Caddy). Upgrading from the two-container release: [migration notes](docs/migration/v-next-single-container.md).

```bash
git clone https://github.com/strausmann/Label-Printer-Hub.git
cd Label-Printer-Hub/examples
cp .env.example .env
# Required: PRINTER_HUB_SECRET_KEY (openssl rand -base64 32 | tr '+/' '-_')
#           PRINTER_HUB_PUBLIC_URL (the address you open the hub at; a local
#           address such as http://localhost:8000 is fine)
$EDITOR .env
docker compose -f compose.standalone.yml up -d

curl http://localhost:8000/healthz
curl http://localhost:8000/api/v1/info
# Open http://localhost:8000/ and sign in. A fresh install has no admin key:
# either set PRINTER_HUB_BOOTSTRAP_ADMIN_KEY (one-time key, 32+ characters) or run
docker exec label-printer-hub-backend printer-hub admin create-key --scope admin --name first-admin
# then add your printers under Settings > Printers.
```

To build and run the hub from source without any printer hardware, use the smoke-test compose file (throw-away keys, one container, built from the local tree):

```bash
export PRINTER_HUB_SECRET_KEY="$(openssl rand -base64 32 | tr '+/' '-_')"
docker compose -f dev/docker-compose.smoke.yml up --build
# UI and API on http://localhost:8000
curl http://localhost:8000/healthz
```

Other containers in the same stack can call the hub directly with an API key: [using the hub from other services](examples/README.md#using-the-hub-from-other-services-in-the-same-stack).

For the REST API alone, without the web UI, see [`examples/compose.backend-only.yml`](examples/compose.backend-only.yml).

## REST API surface

| Method | Path | Purpose | Body |
|---|---|---|---|
| `POST` | `/api/v1/print` | Submit a print job | `PrintRequest` (see below) |
| `GET` | `/api/v1/jobs/{job_id}` | Poll job status | — |
| `POST` | `/api/v1/printer/resume` | Resume the printer queue after a recoverable error halted it (tape empty / cover open / offline) | — |
| `GET` | `/healthz` | Liveness probe for orchestrators | — |
| `GET` | `/readiness` | Readiness probe — deep check for reverse-proxy routing | — |

### Moved API paths (1.5.0)

Since 1.5.0 every API route lives under `/api/v1/`. There are no aliases and no redirects: update scripts, reverse-proxy rules (the webhook bypass in particular) and bookmarks.

| Before | Now |
|---|---|
| `/api/admin/api-keys…` | `/api/v1/admin/api-keys…` |
| `/api/printers…` (printers, calibration, capabilities) | `/api/v1/printers…` |
| `/api/jobs…` | `/api/v1/jobs…` |
| `/api/batches/{batch_id}` | `/api/v1/batches/{batch_id}` |
| `/api/print/{printer_key}/batch`, `…/sheet`, `…/sheet/preview` | `/api/v1/print/{printer_key}/…` |
| `/api/render/preview` | `/api/v1/render/preview` |
| `/api/lookup/{app}/{entity_id}` | `/api/v1/lookup/{app}/{entity_id}` |
| `/api/sheet-types…`, `/api/sheets…`, `/api/sheet-cells` | `/api/v1/sheet-types…`, `/api/v1/sheets…`, `/api/v1/sheet-cells` |
| `/api/webhook/spoolman`, `/api/webhook/grocy` | `/api/v1/webhook/spoolman`, `/api/v1/webhook/grocy` |
| `/api/info` | `/api/v1/info` |
| `POST /print` | `POST /api/v1/print` |
| `POST /printer/resume` | `POST /api/v1/printer/resume` |
| `GET /jobs/{job_id}` | removed: it duplicated `GET /api/v1/jobs/{job_id}`, which reads the stored job and applies the per-key printer ACL |
| `POST /jobs/{job_id}/resume` | removed: nothing produces a paused job any more (the tape-mismatch pause was removed with the layout engine) |

Unchanged: `/healthz`, `/readiness`, `/openapi.json`, `/docs`, the label links `/loc/…`, `/asset/…`, `/spool/…`, `/product/…`, and `/jobs/{id}`: that path is no longer an API route; where the web app is mounted a browser `GET` returns the web app, and in API-only mode it is a plain 404.

**Installed web app:** the service worker updates the app in the background and asks before switching. A client that has not accepted the update prompt yet keeps calling the old paths until the user accepts, so expect old-path 404s from such clients after the upgrade.

### Health Probes

The backend exposes two HTTP probes with different semantics:

| Endpoint | Purpose | What it answers |
|----------|---------|-----------------|
| `GET /healthz` | Liveness — Docker / Kubernetes container restart signal | "the process and the event loop are alive" |
| `GET /readiness` | Readiness — reverse-proxy routing signal | "the process can serve traffic right now": database connectable, alembic at head, templates seeded, runtime printer matches DB, SNMP probe fresh, queue worker alive, SSE bus capacity ok |

`/readiness` returns HTTP 200 with `status` of `ready` (all checks ok) or `degraded` (non-critical checks failing — still routable), and HTTP 503 with `not-ready` when a critical check (database, alembic, template_seed) fails.

Pangolin's `targets[0].healthcheck.path` can use `/readiness` for deep checks instead of `/healthz`; Docker container healthchecks should stay on `/healthz` to avoid restart loops on transient DB failures.

See `docs/superpowers/specs/2026-05-17-phase-7b-foundation-design.md` for the full check list and rationale.

### `POST /api/v1/print` request body

```jsonc
{
  // One of the ContentType values (app/schemas/content_type.py), e.g. "qr_two_lines".
  "content_type": "qr_two_lines",
  // Exactly one of `data` or `lookup` is required.
  "data":    { "title": "Asset 123",
               "primary_id": "ASSET-123",
               "qr_payload": "https://snipe.example/assets/123",
               "secondary": ["optional", "extra lines"] },
  // "lookup": { "app": "snipeit", "identifier": "123" },
  "options": { "copies": 1,              // 1..10, default 1
               "auto_cut": true,
               "high_resolution": false }
}
```

Unknown fields are rejected (`extra="forbid"`). The label is laid out for the loaded tape width.

### Synchronous error codes (`POST /api/v1/print`)

| HTTP | `error_code` | When |
|---|---|---|
| 409 | `tape_empty` | preflight detects no media |
| 409 | `no_tape_loaded` | no tape cassette is loaded |
| 409 | `printer_cover_open` | preflight detects cover open |
| 409 | `printer_disabled` | the printer is disabled |
| 409 | `unsupported_tape` | the loaded tape width is not supported by the layout engine |
| 422 | `content_type_data_mismatch` | `data` lacks fields the `content_type` needs (`error_detail.missing_fields`) |
| 422 | `integration_unknown_app` | `lookup.app` is not a configured integration |
| 502 | `integration_lookup_failed` | integration plugin raised |
| 503 | `printer_offline` | SNMP preflight could not reach the printer |

## Environment variables

Full reference lives in [`backend/.env.example`](backend/.env.example). The most-used variables grouped by purpose:

| Variable | Default | Purpose |
|---|---|---|
| **`PRINTER_HUB_SECRET_KEY`** | _required_ | Master key for secrets stored in the database (base64url of 32 random bytes; `openssl rand -base64 32 \| tr '+/' '-_'`) |
| **`PRINTER_HUB_PUBLIC_URL`** | _required_ | Any `http(s)` URL, local ones included (`http://localhost:8000`, `http://printer-hub:8000`, a LAN IP). Set it to the address people open the UI at if you use the browser UI; decides cookie security (`Secure` and `__Host-` prefix when `https`) and the allowed `Origin` |
| `PRINTER_HUB_BOOTSTRAP_ADMIN_KEY` | _empty_ | One-time key (32+ characters) that signs you in while no admin key exists; empty disables it |
| `PRINTER_HUB_DATABASE_URL` | `sqlite+aiosqlite:////data/printer-hub.db` | Database |
| `PRINTER_HUB_SSO_TRUST_TOKEN` | _empty_ | Shared secret the proxy sends as `X-Pangolin-Token`; without it `Remote-User` is ignored |
| `PRINTER_HUB_TRUST_LEGACY_PANGOLIN_USER` | `false` | Opt in to the legacy `X-Pangolin-User` header |
| `PRINTER_HUB_TRUST_PANGOLIN_BASIC_BYPASS` | `false` | Opt in to the `Authorization: Basic` bypass credential |
| `PRINTER_HUB_WEBHOOK_API_KEY` | _empty_ | Bearer for inbound integration webhooks (≥ 32 chars; generate with `openssl rand -hex 32`) |
| `PRINTER_HUB_SNIPEIT_URL` | _empty_ | Snipe-IT base URL |
| `PRINTER_HUB_SNIPEIT_API_KEY` | _empty_ | Snipe-IT bearer token |
| `PRINTER_HUB_GROCY_URL` | _empty_ | Grocy base URL |
| `PRINTER_HUB_GROCY_API_KEY` | _empty_ | Grocy API key |
| `PRINTER_HUB_SPOOLMAN_URL` | _empty_ | Spoolman base URL (no auth) |
| `PRINTER_HUB_SERVER_PORT` | `8090` | Internal port (overridden to `8000` in the container — see Dockerfile) |
| `PRINTER_HUB_LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

All variables share the `PRINTER_HUB_` prefix and map 1:1 to the `Settings` model in `backend/app/config.py`. A variable set in the environment wins over the stored value and locks the field in the UI (D4). Printers have no variables: they are managed in Settings > Printers.

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

**Live API reference** (when running): `/openapi.json` and `/docs` (interactive reference, Scalar, served by the hub itself) — see [ADR 0011](docs/decisions/0011-openapi-as-api-contract.md).

## Contributing

Contributions are welcome — especially **printer model plugins**. See [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow (Conventional Commits, TDD, semantic-release).

## Trademarks and disclaimer

> **Brother**, **P-touch**, **PT-Series**, and **QL-Series** are trademarks or registered trademarks of **Brother Industries, Ltd.** All other trademarks are the property of their respective owners.
>
> This project is **not affiliated with, endorsed by, or sponsored by Brother Industries, Ltd.** It is an independent open-source project that interoperates with Brother label printers via documented protocols (Brother Raster Command Reference, IEEE 802.3, RFC 3805 SNMP Printer-MIB, RFC 8011 IPP).
>
> "Brother" is used in this README solely for the purpose of describing the hardware that this software is compatible with. No commercial use of the Brother trademarks is intended.

## License

Label Printer Hub is licensed under the **GNU Affero General Public License, version 3 or later** (`AGPL-3.0-or-later`) — see [LICENSE](LICENSE).

Releases up to and including 1.0.3 are MIT; from 1.1.0 on AGPL-3.0-or-later. Anyone who received an earlier release keeps the MIT terms for that release.

Why the change:

- The hub depends on [`brother_ql`](https://github.com/pklaus/brother_ql), which is GPL-3.0-or-later, so the combined work is distributed under terms at least as strong as GPL-3.0.
- The hub is a network service. Section 13 of the AGPL gives the people who use a modified version over a network the right to its source.

If you run a modified version for others, set `HUB_REPO_URL` to where its source is published — the About page links there. Unmodified releases link to the exact tag of the running version.

## Acknowledgements

- [`pklaus/brother_ql`](https://github.com/pklaus/brother_ql) — QL-Series Python library
- [`nbuchwitz/ptouch`](https://github.com/nbuchwitz/ptouch) — PT-Series Python library
- [`donkie/Spoolman`](https://github.com/donkie/Spoolman), [Grocy](https://github.com/grocy/grocy), [Snipe-IT](https://github.com/snipe/snipe-it) — apps this hub integrates with
