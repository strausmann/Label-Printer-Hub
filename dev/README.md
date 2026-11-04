# Local development helpers

This folder holds non-shipping dev artifacts: local smoke-test setups, helper
configs, and scratch utilities. Nothing in here is referenced by the production
container image — it is built from `backend/Dockerfile` (build context: the
repository root; the web app in `frontend/` is built into it).

## `docker-compose.smoke.yml`

Build and run the hub (one container: API and web UI) from the local source
tree. No GHCR pull, no external services, no printer: add printers in the UI.

```bash
# From the repo root:
docker compose -f dev/docker-compose.smoke.yml up --build
```

After the container reports healthy:

| Endpoint | URL | Expected |
|----------|-----|----------|
| Web UI | http://localhost:8000/ | Sign-in page |
| Health | http://localhost:8000/healthz | `200` |
| API info | http://localhost:8000/api/info | JSON with version and feature flags |
| API docs | http://localhost:8000/docs | Swagger UI |

The smoke stack sets a fake `PRINTER_HUB_SECRET_KEY` and a fake one-time
`PRINTER_HUB_BOOTSTRAP_ADMIN_KEY` (see the compose file) — sign in with the
bootstrap key, create a real admin key, then add a printer under
Settings > Printers. Do not reuse these values anywhere else.

Stop and wipe the SQLite volume between runs:

```bash
docker compose -f dev/docker-compose.smoke.yml down -v
```

### What this smoke covers

- Backend startup including Alembic migrations from the runtime image
- The web UI built into the image and served by the backend
- Settings validation (try shortening `PRINTER_HUB_WEBHOOK_API_KEY` to see the
  EX_CONFIG-friendly error from F3)

### What this does NOT cover

- Real Brother PT/QL hardware
- Pangolin SSO — the smoke stack is plain HTTP on `:8000`
- Production tag scheme — the image builds as `latest` locally

## Next step: deploy to a node

For a real hardware test (e.g. on `<your-docker-node>` with a PT-P750W on the LAN), use
the production compose files under `examples/` and the proper GHCR image tags.
