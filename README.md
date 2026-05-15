# Label Printer Hub

[![CI](https://github.com/strausmann/Label-Printer-Hub/actions/workflows/ci.yml/badge.svg)](https://github.com/strausmann/Label-Printer-Hub/actions/workflows/ci.yml)
[![CodeQL](https://github.com/strausmann/Label-Printer-Hub/actions/workflows/codeql.yml/badge.svg)](https://github.com/strausmann/Label-Printer-Hub/actions/workflows/codeql.yml)
[![codecov](https://codecov.io/gh/strausmann/Label-Printer-Hub/branch/main/graph/badge.svg)](https://codecov.io/gh/strausmann/Label-Printer-Hub)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-yellow.svg)](https://conventionalcommits.org)
[![semantic-release](https://img.shields.io/badge/%20%20%F0%9F%93%A6%F0%9F%9A%80-semantic--release-e10079.svg)](https://github.com/semantic-release/semantic-release)
[![GitHub Issues](https://img.shields.io/github/issues/strausmann/label-printer-hub)](https://github.com/strausmann/label-printer-hub/issues)

> Self-hosted multi-printer hub for Brother PT-Series and QL-Series label printers. Pull-mode (user scans barcode) and push-mode (Spoolman/Grocy webhooks). Integrates with Snipe-IT, Grocy, Spoolman. Plugin-based architecture for additional printer models. PWA-ready for smartphone use.

## Status

**Early development.** See [project board](https://github.com/strausmann/label-printer-hub/projects) and [open issues](https://github.com/strausmann/label-printer-hub/issues) for progress.

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

See [`examples/README.md`](examples/README.md) for sample compose files (standalone / Traefik / Pangolin / Caddy).

```bash
# Minimal example (no reverse proxy):
curl -O https://raw.githubusercontent.com/strausmann/label-printer-hub/main/examples/compose.standalone.yml
curl -O https://raw.githubusercontent.com/strausmann/label-printer-hub/main/examples/.env.example
cp .env.example .env  # adjust PRINTERS=… to your printer IPs
docker compose -f compose.standalone.yml up -d
```

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
