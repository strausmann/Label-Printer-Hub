# label-printer-hub — frontend

Go web server for the [Label Printer Hub](https://github.com/strausmann/label-printer-hub). Serves the user-facing UI and proxies API + SSE requests to the Python backend (see [ADR 0001](../docs/decisions/0001-two-container-architecture.md)).

Stack: Go 1.24 + chi v5 router · Tailwind v4 CSS (compiled at Docker build time) · HTMX 2.0.4 + htmx-ext-sse · oapi-codegen-generated typed backend client · `html/template` server-side rendering.

## Pages

| Route | Description |
|---|---|
| `GET /` | Dashboard — printer grid with 30 s HTMX polling |
| `GET /printers/{id}` | Printer detail with live SSE status updates |
| `GET /jobs` | Jobs list with state/printer filter and cursor pagination |
| `GET /jobs/{id}` | Job detail with 10 s auto-refresh for in-flight jobs |
| `POST /jobs/{id}/retry` | Retry a failed/cancelled job (303 See Other to new job) |
| `GET /templates` | Templates grid with app filter and 60 s polling |
| `GET /templates/{id}` | Template detail with YAML source and PNG preview (2 s timeout) |
| `GET /lookup/{app}/{id}` | Entity lookup display for QR-code scanner flows |
| `GET /healthz` | Health check — returns `backend_reachable` probe result |
| `GET /static/*` | Compiled CSS, HTMX JS, and static assets |
| `/api/*` | Reverse proxy to backend (REST + SSE) |
| `/loc/* /asset/* /spool/* /product/*` | QR-landing paths proxied to backend |

## Local development

### Prerequisites

- Go 1.24+
- [Tailwind v4 Standalone CLI](https://tailwindcss.com/blog/standalone-cli) (optional — needed for CSS changes only)
- A running backend on `http://localhost:8000` (or override `BACKEND_URL`)

### Workflow

```bash
# Install dependencies
go mod download

# Regenerate the typed backend client (when backend/openapi.json changes)
make gen-client

# Watch and compile Tailwind CSS (in a separate terminal)
make dev-css           # requires ./tailwindcss binary in frontend/

# Run the dev server
make dev-go            # or: BACKEND_URL=http://localhost:8000 go run ./cmd/server

# Run all tests (with race detector)
make test              # or: go test -race ./...

# Lint
make lint              # or: go vet ./...
```

The server listens on `:8080` by default (override with `PORT=…`).

`/healthz` returns JSON with `backend_reachable` so container orchestrators and monitoring can distinguish "frontend up, backend down" from "everything healthy":

```json
{
  "status": "ok",
  "version": "1.2.3",
  "repository": "https://github.com/strausmann/label-printer-hub",
  "backend_reachable": true,
  "backend_latency_ms": 4
}
```

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `PORT` | `8080` | Internal HTTP port |
| `BACKEND_URL` | `http://backend:8000` | Base URL of the Python backend |
| `HUB_VERSION` | `0.0.0-dev` | Baked in by the Dockerfile from the release tag |
| `HUB_REVISION` | `unknown` | Baked in by the Dockerfile from the git SHA |
| `HUB_BUILD_DATE` | `1970-01-01T00:00:00Z` | Baked in by the Dockerfile at build time |
| `HUB_REPO_URL` | `https://github.com/strausmann/label-printer-hub` | Baked in by the Dockerfile |

## Container

The `Dockerfile` uses a multi-stage build:

1. **tailwind-builder** (`debian:bookworm-slim`) — downloads the Tailwind v4 Standalone CLI and compiles `web/styles/app.css → web/static/app.css`. Uses Debian rather than Alpine because the Tailwind binary is a glibc ELF (musl incompatible).
2. **builder** (`golang:1.24-alpine`) — downloads Go modules and compiles the static binary with version ldflags.
3. **runtime** (`alpine:3.20`) — minimal image with tini + curl, non-root UID 1000.

Published to `ghcr.io/strausmann/label-printer-hub-frontend` — see the [tag scheme ADR](../docs/decisions/0007-docker-image-tag-scheme.md) for which tags every release publishes.

```bash
# Build locally
docker build --platform linux/amd64 -f frontend/Dockerfile -t lph-frontend:local frontend/

# Run with a local backend
docker run --rm -p 8080:8080 -e BACKEND_URL=http://host.docker.internal:8000 lph-frontend:local

# Check health
curl -sf http://localhost:8080/healthz
```

## License

MIT — see [LICENSE](../LICENSE) in the repository root.
