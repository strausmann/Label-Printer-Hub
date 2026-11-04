# Sample compose files

Pre-made deployment recipes for different reverse-proxy stacks. Pick the one that matches your setup.

> **Note:** the container image is not published yet — this project is in early development. These compose files describe the *intended* deployment. They will be functional once the first release lands. Track progress in the [project board](../../projects).

## One container

The hub ships as **one image**: `ghcr.io/strausmann/label-printer-hub-backend`. A single Python process serves the REST API, the live event stream (`/api/v1/events`) and the web UI (see [ADR 0015](../docs/decisions/0015-single-process-deployment.md)). There is no separate frontend image any more.

Reverse proxies point straight at `backend:8000`. Upgrading from the two-container release: [migration notes](../docs/migration/v-next-single-container.md).

## Which variant should I use?

| Your setup | Use |
|---|---|
| Just a LAN, no reverse proxy | [`compose.standalone.yml`](compose.standalone.yml) |
| You already run Traefik | [`compose.traefik.yml`](compose.traefik.yml) |
| You already run Pangolin | [`compose.pangolin.yml`](compose.pangolin.yml) |
| You already run Caddy | [`compose.caddy.yml`](compose.caddy.yml) |
| Anything else (nginx, HAProxy, ...) | Start with `compose.standalone.yml` and add your own front |

Each file is self-contained — copy the one you need plus `.env.example`.

## Using the hub from other services in the same stack

Other containers on the same Docker network call the hub directly at `http://<service>:8000` (for example `http://backend:8000`) and authenticate with an API key in the `X-Label-Hub-Key` header. No reverse proxy and no SSO are involved.

- **Keys.** Create one per client in Settings > Access and keys. A key has a scope (`read`, `print`, `admin`) and can be restricted to specific printers. Calls authenticated by a key header are exempt from CSRF protection (CSRF only guards browser-session cookies).
- **`PRINTER_HUB_PUBLIC_URL` is still required.** Set it to the address *people* use, not the internal name: it decides cookie security (`Secure` and `__Host-` prefix when it is `https`) and the allowed `Origin` for state-changing requests authenticated by proxy headers or the Basic bypass.
- **Browsers use the public URL.** With an `https` public URL the session cookies are `Secure` and `__Host-` prefixed, so a browser will not send them to the plain-`http` internal name. Open the UI through the public address.
- **Proxy headers.** `Remote-User` and similar headers count only together with `PRINTER_HUB_SSO_TRUST_TOKEN`, so a neighbouring container cannot pose as an SSO user. Leave the trust token unset if you use no SSO proxy.
- **No published port is needed** for internal-only use; omit `ports:` (see `compose.backend-only.yml` for an API-only variant).

```yaml
services:
  hub:
    image: ghcr.io/strausmann/label-printer-hub-backend:${HUB_VERSION:-latest}
    user: "1000:1000"
    environment:
      - "PRINTER_HUB_SECRET_KEY=${PRINTER_HUB_SECRET_KEY:?set PRINTER_HUB_SECRET_KEY}"
      - "PRINTER_HUB_PUBLIC_URL=${PRINTER_HUB_PUBLIC_URL:?set PRINTER_HUB_PUBLIC_URL}"
    volumes:
      - ./data:/data
    networks: [stack]

  client:
    image: example/client:latest
    environment:
      - LABEL_HUB_URL=http://hub:8000
      - LABEL_HUB_KEY=CHANGE_ME   # sent as the X-Label-Hub-Key header
    networks: [stack]

networks:
  stack:
```

## Prerequisites

1. **Brother printer** on your network: PT-Series (PT-E550W/P710BT/P750W) or QL-Series (QL-800/810W/820NWB). USB-only models are out of scope at this stage.
2. **Printer IP addresses** noted. You enter them in the UI after the first sign-in (Settings > Printers). Find them via your DHCP leases, the printer's web UI, or:
   ```bash
   nmap -p 9100,161 192.0.2.0/24 --open
   ```
3. **Container runtime**: Docker Engine 24+ (or Docker Desktop, Podman with compose plugin).
4. **For reverse-proxy variants**: an existing reverse proxy (Traefik/Caddy/Pangolin) and a domain name with DNS pointing at it.

## Configuration

Copy the example env file and adjust:

```bash
cp .env.example .env
$EDITOR .env
```

Required values:
- `PRINTER_HUB_SECRET_KEY` — master key for secrets stored in the database. Generate: `openssl rand -base64 32 | tr '+/' '-_'`. Keep it: without it stored secrets cannot be read.
- `PRINTER_HUB_PUBLIC_URL` — the address users open the hub at, e.g. `https://printerhub.example.com`
- `PRINTERHUB_HOST` — your domain (only for reverse-proxy variants), e.g. `printerhub.example.com`
- `PRINTER_HUB_SSO_TRUST_TOKEN` — Pangolin variant only; the same value is injected by the proxy as `X-Pangolin-Token`

Recommended:
- `PRINTER_HUB_WEBHOOK_API_KEY` — random 32-byte string for Spoolman/Grocy webhooks (generate with `openssl rand -hex 32`)

Printers are **not** configured here: add them in the UI under **Settings > Printers**.

First sign-in: a fresh install has no admin key. Set `PRINTER_HUB_BOOTSTRAP_ADMIN_KEY` (32+ characters) for a one-time sign-in that leads to creating your first admin key, or create one inside the container:

```bash
docker exec label-printer-hub-backend printer-hub admin create-key
```

Optional:
- `PRINTER_HUB_SNIPEIT_URL` + `PRINTER_HUB_SNIPEIT_API_KEY` — Snipe-IT integration
- `PRINTER_HUB_GROCY_URL` + `PRINTER_HUB_GROCY_API_KEY` — Grocy integration
- `PRINTER_HUB_SPOOLMAN_URL` — Spoolman integration

Integrations can also be set in the UI; a variable set here wins and locks the field.

## Deploy

```bash
docker compose -f compose.<variant>.yml up -d
```

Then open `https://<your-host>/` (or `http://<host-ip>:8000` for standalone) in a browser.

## Verify printer reachability

Before hitting "Print", confirm the hub can talk to the printer. Run on the host that runs the hub:

```bash
# TCP/9100 (raster print)
nc -zv <printer-ip> 9100

# SNMP — should respond with "MFG:Brother;CMD:...;MDL:<model>;CLS:PRINTER;..."
snmpwalk -v 2c -c public <printer-ip> 1.3.6.1.4.1.2435.2.3.9.1.1.7.0
```

If SNMP fails: open the printer's web UI, navigate to **Network → Protocols → SNMP**, enable SNMPv1/v2c with community `public`.

## PWA install (smartphone)

After the UI is up:

1. Open the URL in Chrome/Safari/Firefox on your phone
2. Browser will offer "Add to Home Screen" — accept
3. App icon appears on your home screen and behaves like a native app
4. Optional: enable browser notifications when prompted (toast on print complete/failed)

## Troubleshooting

- **Web UI loads but no printers shown** — add the printer under Settings > Printers and check that its IP is reachable from the container (network namespace).
- **Print job stuck in `printing` state** — usually means the printer never sent the "complete" notification. Check the printer LCD; cover may be open.
- **SSE/live updates not working through Traefik** — make sure the `responseforwarding.flushinterval` label is set (already in the sample); the stream is `/api/v1/events`.
- **Webhooks return 401** — check `PRINTER_HUB_WEBHOOK_API_KEY` matches between hub `.env` and Spoolman/Grocy settings.

For more, open a [Discussion](../../discussions) or check existing [issues](../../issues).

## Adding a new printer model

Want to support a model that isn't on the list? See [`docs/plugin-development.md`](../docs/plugin-development.md) and open a [plugin request](../../issues/new?template=plugin_request.yml).
