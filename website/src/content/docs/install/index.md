---
title: Install with Docker Compose
description: Run Labelyard as one container, set the two required values and sign in for the first time.
sidebar:
  label: Docker Compose
---

Labelyard ships as one image, `ghcr.io/strausmann/labelyard` (also on Docker Hub as `docker.io/strausmann/labelyard`), for `linux/amd64` and `linux/arm64`. One process serves the REST API, the live event stream and the web UI.

## What you need

- Docker Engine 24 or newer (or Docker Desktop, or Podman with the compose plugin).
- Your printers on the same network as the host, with their addresses noted. See [connecting printers](/install/printers/).
- For use from outside your LAN: a reverse proxy and a domain name. See [reverse proxy](/install/reverse-proxy/).

## The compose file

This is the standalone variant without a reverse proxy, for a trusted LAN, cut down to what a first start needs. `examples/compose.standalone.yml` in the repository is the fuller version with more variables (port, trusted proxies, database, log level); the proxy variants are next to it.

```yaml
services:
  labelyard:
    image: ghcr.io/strausmann/labelyard:${HUB_VERSION:-1.6.0}
    container_name: labelyard
    user: "1000:1000"
    ports:
      - "${HUB_PORT:-8000}:8000"
    environment:
      - "LABELYARD_SECRET_KEY=${LABELYARD_SECRET_KEY:?set LABELYARD_SECRET_KEY}"
      - "LABELYARD_PUBLIC_URL=${LABELYARD_PUBLIC_URL:?set LABELYARD_PUBLIC_URL}"
      - LABELYARD_WEBHOOK_API_KEY=${LABELYARD_WEBHOOK_API_KEY:-}
    volumes:
      - ./data:/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8000/healthz"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s
```

## The two required values

Put them in a `.env` file next to the compose file:

```bash
# base64url of 32 random bytes; keep it, without it stored secrets cannot be read
LABELYARD_SECRET_KEY=   # openssl rand -base64 32 | tr '+/' '-_'
# the address you open the hub at; a local one such as http://localhost:8000 is fine
LABELYARD_PUBLIC_URL=http://localhost:8000
```

Create the data directory first and give it to the user the container runs as; a directory that Docker creates by itself belongs to root, and the hub cannot write to it:

```bash
mkdir -p data && sudo chown 1000:1000 data
```

Then start it and check that it answers:

```bash
docker compose up -d
curl http://localhost:8000/healthz
```

Every other setting is optional and listed in the [configuration reference](/reference/configuration/).

## First sign-in

A fresh install has no API key, and the web UI signs in with one. Choose one of two ways:

- **In the browser.** Set `LABELYARD_BOOTSTRAP_ADMIN_KEY` to a one-time key of at least 32 characters (`openssl rand -hex 32`) and restart. Sign in with it; the bootstrap session can only create the first real admin key. Then sign in with the new key and remove the variable.
- **In the container.** Create the key on the command line; it is printed once:

  ```bash
  docker compose exec labelyard labelyard admin create-key --scope admin --name first-admin
  ```

Then add your printers under **Settings > Printers**. No restart is needed.

## Data and updates

All state lives in the `./data` volume: the database, sheets and settings. Back it up together with `LABELYARD_SECRET_KEY` (see [backups](/admin/backups/)). To update, change the image tag, then `docker compose pull && docker compose up -d`. The tags are explained under [upgrades](/admin/upgrades/).
