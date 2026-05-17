# Local development helpers

This folder holds non-shipping dev artifacts: local smoke-test setups, helper
configs, and scratch utilities. Nothing in here is referenced by the production
container images — those are built from `backend/Dockerfile` and
`frontend/Dockerfile` directly.

## `docker-compose.smoke.yml`

Build and run the full stack (backend + frontend) from the local source tree
with a mock printer. No real hardware, no GHCR pull, no external services.

```bash
# From the repo root:
docker compose -f dev/docker-compose.smoke.yml up --build
```

After both containers report healthy:

| Endpoint | URL | Expected |
|----------|-----|----------|
| Frontend UI | http://localhost:8080/ | Dashboard rendered |
| Frontend healthz | http://localhost:8080/healthz | `backend_reachable: true` |
| Frontend pages | `/printers/<uuid>`, `/jobs`, `/templates`, `/lookup/<app>/<id>` | 200 + HTML |
| Backend (via proxy) | http://localhost:8080/api/printers | JSON array |

Stop and wipe the SQLite volume between runs:

```bash
docker compose -f dev/docker-compose.smoke.yml down -v
```

### What this smoke covers

- Backend startup including Alembic migrations from the runtime image
- Frontend → backend reverse proxy + SSE pass-through
- All Phase 7a pages (Dashboard, Printer Detail, Jobs, Templates, Lookup)
- Settings validation (try shortening `PRINTER_HUB_WEBHOOK_API_KEY` to see the
  EX_CONFIG-friendly error from F3)

### What this does NOT cover

- Real Brother PT/QL hardware — uses the mock printer backend
- Pangolin SSO — the smoke stack is plain HTTP on `:8080`
- Production tag scheme — both images build as `latest` locally

## Next step: deploy to a node

For a real hardware test (e.g. on `hhdocker02` with a PT-P750W on the LAN), use
the production compose files under `examples/` and the proper GHCR image tags.
