# 0001 — Two-container architecture (separate backend and frontend)

- **Status:** Accepted
- **Date:** 2026-05-10
- **Deciders:** maintainer

## Context

The hub needs a UI (browser-based, smartphone-friendly via PWA) and a service that talks to printers (TCP/9100 raster bytes, SNMP polling, queue management). These two responsibilities can be packaged as one container or two.

The maintainer explicitly preferred separating them despite the additional overhead, reasoning that UI and printer-protocol concerns belong to different language ecosystems and have independent evolution paths.

## Decision

We ship the hub as **two separately built and versioned container images**:
- `label-printer-hub-backend` — Python/FastAPI, talks to printers, owns the queue, exposes JSON API + SSE
- `label-printer-hub-frontend` — Go web server, serves UI + PWA assets, proxies API and SSE to the backend

Both images are released together at the same semantic version. They communicate over an internal docker network. Only the frontend is exposed to the user via the deployer's reverse proxy.

## Options considered

### Option A — Two containers (chosen)
- Pros: clear separation of concerns; UI replaceable without touching printer code; per-language CodeQL/security analysis; smaller single-purpose images; independent release cadence possible
- Cons: two containers to deploy; one extra HTTP hop (~1-2ms on docker network); two Dockerfiles; two CI matrix entries; two semantic-release outputs

### Option B — Single Python container with Jinja2/HTMX UI
- Pros: simplest deployment; no inter-service communication; fastest to MVP; one image
- Cons: doesn't match the maintainer's preferred layering; UI replacement requires backend changes; mixing language ecosystems for static asset pipeline (Tailwind via Node) inside a Python image is awkward

### Option C — Static frontend + Python backend (single container)
- Pros: minimal moving parts; no Go runtime
- Cons: less templating power; no compiled-binary advantage; doesn't get us to a Go frontend

## Consequences

- Two Dockerfiles (`backend/Dockerfile`, `frontend/Dockerfile`)
- CI matrix with `service: [backend, frontend]` for build/publish
- semantic-release publishes two GHCR repos and two Docker Hub repos at every release with identical tags (see ADR 0007)
- Compose files reference both with the same `HUB_VERSION`; mixing versions across a major.minor boundary is unsupported
- Frontend codebase consumes a Go-typed client generated from the backend's OpenAPI spec
- SSE travels backend → frontend (proxied) → browser; reverse-proxy buffering must be disabled (Traefik `flushinterval`, Caddy `flush_interval -1`)
- Privacy/trademark policies and CI checks apply equally to both images
- Image storage roughly doubles compared to a single-container alternative

## References

- Issue [#1](https://github.com/strausmann/label-printer-hub/issues/1) — frontend architecture clarification (closed by this ADR)
- Related: ADR 0002 (Python backend), ADR 0003 (Go frontend), ADR 0007 (Docker tag scheme), ADR 0009 (SSE)
