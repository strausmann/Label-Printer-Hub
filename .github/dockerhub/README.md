<p align="center">
  <img src="https://raw.githubusercontent.com/strausmann/labelyard/main/docs/brand/labelyard/icon-192.png" alt="Labelyard" width="96">
</p>

# Labelyard

**Labelyard — the self-hosted Label Printer Hub for all your labels.**

Labelyard is a print server for Brother PT-Series and QL-Series label printers and for page printers over IPP (label sheets). Scan a barcode and print, or let Spoolman and Grocy send print jobs by webhook. One container serves the REST API, the live event stream and the web UI, which installs as an app on a phone.

Labelyard was formerly called *Label Printer Hub*. The new name changes no data and no API path; see the [migration guide](https://github.com/strausmann/labelyard/blob/main/docs/migration/labelyard.md).

- Website and documentation: <https://labelyard.app>
- Source code and issues: <https://github.com/strausmann/labelyard>

## Pull

The same multi-arch image (`linux/amd64`, `linux/arm64`) is published to both registries:

```bash
docker pull ghcr.io/strausmann/labelyard:latest
docker pull docker.io/strausmann/labelyard:latest
```

## Tags

| Tag | Example | Use when |
|---|---|---|
| `x.y.z` | `1.6.0` | You want full reproducibility |
| `x.y` | `1.6` | Get bug fixes automatically |
| `x` | `1` | Stay on a major version, get features |
| `latest` | most recent release | You are fine with anything new |
| `dev` | built from `main` | Testing only; changes with every merge |
| `x.y.z-rc.N` | `1.7.0-rc.1` | Preview of an upcoming release; removed once the release exists |

Previews never get `latest`, `x.y` or `x`, so a preview can never become the default.

## Quick start

```bash
docker run -d --name labelyard \
  -p 8000:8000 \
  -v labelyard-data:/data \
  -e LABELYARD_SECRET_KEY="$(openssl rand -base64 32 | tr '+/' '-_')" \
  -e LABELYARD_PUBLIC_URL=http://localhost:8000 \
  docker.io/strausmann/labelyard:latest
```

Open <http://localhost:8000/> and sign in. A fresh install has no admin key; create one with

```bash
docker exec labelyard labelyard admin create-key --scope admin --name first-admin
```

then add your printers under **Settings → Printers**. Compose files for a reverse proxy (Traefik, Caddy, Pangolin) are in the [examples](https://github.com/strausmann/labelyard/tree/main/examples); the [installation guide](https://labelyard.app/install/) covers printers, HTTPS and upgrades.

## Licence

AGPL-3.0-or-later. Every image carries an SBOM and build provenance; the running app serves the licence lists of every bundled component at `/licenses/backend.json` and `/licenses/frontend.json`. Not affiliated with Brother Industries, Ltd.
