# label-printer-hub — frontend

Go web server for the [Label Printer Hub](https://github.com/strausmann/label-printer-hub). Serves the user-facing UI and proxies API + SSE requests to the Python backend (see [ADR 0001](../docs/decisions/0001-two-container-architecture.md)).

Stack: Go + chi router. Tailwind CSS, HTMX, PWA assets, and the OpenAPI-generated backend client land in follow-up commits — this skeleton is the buildable container baseline.

## Local development

```bash
go mod download
go test ./...
go run ./cmd/server
```

The server listens on `:8080` by default (override with `PORT=…`). `/healthz` returns the same JSON shape as the backend's `/healthz` so orchestrator probe configs work for both.

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

The `Dockerfile` produces `ghcr.io/strausmann/label-printer-hub-frontend` — see the [tag scheme ADR](../docs/decisions/0007-docker-image-tag-scheme.md) for which tags every release publishes.

## License

MIT — see [LICENSE](../LICENSE) in the repository root.
