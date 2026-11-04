# Migrating to the single-container hub

This release (`feat!`, a major version) replaces the two-container deployment (Python backend plus Go frontend) with **one container** that serves the API, the live event stream and the new web UI. It also changes how printers, secrets and proxy authentication are configured. Read this page before you pull the new image.

Why: [ADR 0015](../decisions/0015-single-process-deployment.md) (single process), [ADR 0016](../decisions/0016-react-typescript-web-ui.md) (new web UI), [ADR 0017](../decisions/0017-settings-in-database-env-locks-encrypted-secrets.md) (settings and secrets), [ADR 0019](../decisions/0019-proxy-headers-need-trust-token.md) (proxy trust). Labels such as D1 are explained in the [decision register](../decisions/register.md).

## Checklist

1. Back up your data directory (`./data`, the SQLite database). The database is migrated in place on first start.
2. Replace your compose file with the matching file from [`examples/`](../../examples/) (see "Compose changes").
3. Set the two new required variables, `PRINTER_HUB_SECRET_KEY` and `PRINTER_HUB_PUBLIC_URL`.
4. Pangolin or other proxy SSO: set the trust token (see "Proxy header trust").
5. Start the hub, then get your first admin key (see "First admin access").
6. Re-add printers that came from `PRINTERS_CONFIG` / `printers.yaml` in Settings > Printers.
7. Point API clients that used the frontend's `/api/*` proxy at the backend address (see "What clients must change").

## Compose changes

| Before | After |
|---|---|
| Two services: `backend` and `frontend` | One service: `backend` |
| Images `label-printer-hub-backend` and `label-printer-hub-frontend` | Only `ghcr.io/strausmann/label-printer-hub-backend` (the frontend image is no longer published) |
| Users and reverse proxies reach the frontend on port `8080` | Users and reverse proxies reach the backend on port `8000` (`backend:8000`) |
| Proxy labels (Traefik, Caddy, Pangolin) sit on the `frontend` service | They sit on the `backend` service and target port `8000` |
| `depends_on` the backend's health | Not needed |
| Standalone example exposes the frontend port | Standalone example publishes `${HUB_PORT:-8000}:8000` |

The backend image is now built from the repository root (`docker build -f backend/Dockerfile .`) because the web app is built into it. The `examples/compose.backend-only.yml` file still builds an API-only image (no web UI) for driving the REST API directly.

If your proxy routed `/api/webhook/` separately (Traefik and Pangolin examples), keep that route and point it at the backend.

## New required variables

| Variable | Purpose |
|---|---|
| `PRINTER_HUB_SECRET_KEY` | Master key for secrets stored in the database (base64url of 32 random bytes). Generate: `openssl rand -base64 32 \| tr '+/' '-_'`. The hub refuses to start without it. Keep it safe: stored secrets cannot be read without it. |
| `PRINTER_HUB_PUBLIC_URL` | Required. Any `http(s)` URL is accepted, including internal ones such as `http://printer-hub:8000`, `http://localhost:8000` or a LAN IP; for API-only use inside a stack a local address is fine. If people use the browser UI, set it to the address they open, for example `https://printerhub.example.invalid`, otherwise sign-in cookies and `Origin` checks will not match. It decides cookie security (with an `https` address the session cookies are `Secure` and `__Host-` prefixed; an `http` address logs a warning) and the allowed `Origin` for state-changing requests authenticated by proxy headers or the Basic bypass. It is shown read-only in Settings. |

Several variables in the old examples were never read by the backend because they lacked the `PRINTER_HUB_` prefix (`DATABASE_URL`, `WEBHOOK_API_KEY`, `LOG_LEVEL`, `UI_BASE_URL`). The new examples use the prefixed names (`PRINTER_HUB_DATABASE_URL`, `PRINTER_HUB_WEBHOOK_API_KEY`, `PRINTER_HUB_LOG_LEVEL`). If you relied on the unprefixed names, set the prefixed ones.

## Removed variables

| Removed | Replacement |
|---|---|
| `PRINTERS_CONFIG`, `PRINTERS`, `printers.yaml`, `PRINTER_HUB_PRINTER_BACKEND`, `PRINTER_HUB_PRINTER_MODEL`, `PRINTER_HUB_PRINTER_DISCOVER_VIA_SNMP`, `PRINTER_HUB_PRINTER_SNMP_COMMUNITY`, `PRINTER_HUB_PT750W_HOST`, `PRINTER_HUB_PT750W_PORT` and the other per-model host variables | Printers are managed in the UI under Settings > Printers (D6) and live in the database. Printers you added through the old admin pages are already in the database; only printers defined purely by environment or file must be added again. |
| Frontend `PORT`, `BACKEND_URL`, `CSRF_KEY`, `FRONTEND_PORT` | None. There is no frontend process. CSRF protection for browser sessions is built into the backend. |

## Settings in the UI

Settings you used to set only through the environment can now be edited under Settings. A variable that is set in the environment still wins and locks the field in the UI (D4); secrets entered in the UI are encrypted with `PRINTER_HUB_SECRET_KEY` and are write-only (D5).

## Proxy header trust

Before, the hub trusted the identity headers of a reverse proxy because the backend was only reachable through the frontend and the proxy. With one process the backend is the first hop, so a client that can reach it could send `Remote-User` itself. Identity headers are therefore **ignored unless the request also carries the shared trust token** (D10, [ADR 0019](../decisions/0019-proxy-headers-need-trust-token.md)).

- Set `PRINTER_HUB_SSO_TRUST_TOKEN` (generate: `openssl rand -hex 32`) on the hub **and** make the proxy send the same value in the `X-Pangolin-Token` request header. In the Pangolin example this is the `request-headers[0]` blueprint label. Without the token every request is treated as unauthenticated and users see the sign-in page.
- Rotating the token ends all SSO sessions.
- Two older paths are **off by default** and opt-in. Enable them only if you depend on them:

| Variable (default `false`) | Enables |
|---|---|
| `PRINTER_HUB_TRUST_LEGACY_PANGOLIN_USER` | The legacy `X-Pangolin-User` header without a trust token |
| `PRINTER_HUB_TRUST_PANGOLIN_BASIC_BYPASS` | The Pangolin `Authorization: Basic` bypass credential (used by automation behind Pangolin). Requests that change state must also send an `Origin` header. |
| `PRINTER_HUB_PANGOLIN_BYPASS_SCOPE_DOWNGRADE` | Limits the Basic bypass to `read` scope. Without it, an enabled bypass grants the scope each endpoint asks for, including admin, so a leaked bypass secret is as powerful as an admin key. Opt-in; consider it whenever you enable the bypass. |

Behind a proxy that is not Pangolin, leave all of this unset and use API keys or the sign-in page.

## First admin access

A fresh install no longer creates an admin API key for you (the old database migration that seeded one is gone). Choose one:

- **Bootstrap key (D7):** set `PRINTER_HUB_BOOTSTRAP_ADMIN_KEY` (32 characters or more) before the first start. Sign in with it once; the UI leads straight to creating your first real admin key. The bootstrap key stops working as soon as an admin key exists. Remove the variable afterwards.
- **Recovery command:** inside the running container, `docker exec label-printer-hub-backend printer-hub admin create-key --scope admin --name first-admin` prints a new admin key once. Use it to bootstrap, or to regain access if every admin key is lost.

Existing installations keep their API keys; sign in with one of them.

## Behaviour changes

- **Pausing a printer over the API now really stops its queue**, and a manual pause survives a restart of the hub. Previously a paused printer could keep printing and was forgotten on restart. A printer that is paused for a reason the hub found itself (cover open, wrong tape) shows that reason.
- **The HTML event stream `/api/events` is removed.** It delivered HTML fragments for the HTMX frontend. Use the JSON stream `GET /api/v1/events` (optional `?printer_id=<uuid>`), which authenticates like any other read route. Frames are documented in [`architecture/sse.md`](../architecture/sse.md). Reverse-proxy buffering rules are unchanged: turn buffering off for the event path.
- **Removed pages:** `/templates` and `/templates/{id}` (they were already non-functional). The admin pages `/admin/api-keys` and `/admin/printers` are now Settings > Access and keys and Settings > Printers.
- **QR label paths keep working.** `/loc`, `/asset`, `/spool` and `/product` are served by the backend, so labels you printed earlier still open the right item.
- **Session sign-in:** browsers sign in with an API key (or SSO) and get a session cookie with CSRF protection. API clients keep using their key header. The sign-in route allows 10 attempts per minute per client address, keyed on the direct peer: behind a reverse proxy all clients share that one bucket.
- **`GET /api/lookup/{app}/{entity_id}` now needs a key or a signed-in session** (read scope). It used to be anonymous because server-rendered QR pages called it; those pages are gone, and the lookup returns data from your connected apps. Scanning a label therefore asks anonymous visitors to sign in first. Scripts that call the lookup without credentials must send a key.
- **Third-party integration plugins** must implement `bind(store)`, `is_configured()` and `async reconfigure()`; they are required members of the plugin protocol now (live configuration from the UI). A plugin without them is rejected at registration.

## What clients must change

| Client | Change |
|---|---|
| Browser bookmarks, PWA installs | The address is the same as before when your proxy still points at the hub; open it once to update the installed app. |
| Scripts that called `/api/*` through the frontend | Call the backend address instead (same paths). Hangar and Kept already talk to the backend directly and need no change. |
| Anything reading `/api/events` | Switch to `/api/v1/events` (JSON). |
| Pulling `label-printer-hub-frontend` | Remove it from your compose files and image update tooling. |

## Rollback

Restore the backed-up `./data` directory and the previous compose file and image tags. The first start of the new version migrates the database forward; there is no downgrade migration, so do not start the old version on migrated data.
