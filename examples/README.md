# Sample compose files

Pre-made deployment recipes for different reverse-proxy stacks. Pick the one that matches your setup.

> **Note:** the container image is not published yet — this project is in early development. These compose files describe the *intended* deployment. They will be functional once the first release lands. Track progress in the [project board](../../projects).

## One container

The hub ships as **one image**: `ghcr.io/strausmann/labelyard`. A single Python process serves the REST API, the live event stream (`/api/v1/events`) and the web UI (see [ADR 0015](../docs/decisions/0015-single-process-deployment.md)). There is no separate frontend image any more.

Reverse proxies point straight at `labelyard:8000`. Upgrading from the two-container release: [migration notes](../docs/migration/v-next-single-container.md).

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

Other containers on the same Docker network call the hub directly at `http://<service>:8000` (for example `http://labelyard:8000`) and authenticate with an API key in the `X-Label-Hub-Key` header. No reverse proxy and no SSO are involved.

- **Keys.** Create one per client in Settings > Access and keys. A key has a scope (`read`, `print`, `admin`) and can be restricted to specific printers. Calls authenticated by a key header are exempt from CSRF protection (CSRF only guards browser-session cookies).
- **`LABELYARD_PUBLIC_URL` is still required, but any `http(s)` URL is accepted**, including internal ones such as `http://labelyard:8000`, `http://localhost:8000` or a LAN IP. It decides cookie security (`Secure` and `__Host-` prefix when it is `https`) and the allowed `Origin` for state-changing requests authenticated by proxy headers or the Basic bypass. For API-only use inside a stack, a local address is fine.
- **Browsers: set it to the address you open.** If people use the browser UI, set the variable to the address they type in. With an `https` value the session cookies are `Secure` and `__Host-` prefixed, so a browser will not send them to a plain-`http` internal name; a mismatched value also breaks sign-in cookies and the `Origin` check.
- **Proxy headers.** `Remote-User` and similar headers count only together with `LABELYARD_SSO_TRUST_TOKEN`, so a neighbouring container cannot pose as an SSO user. Leave the trust token unset if you use no SSO proxy.
- **No published port is needed** for internal-only use; omit `ports:` (see `compose.backend-only.yml` for an API-only variant).

```yaml
services:
  hub:
    image: ghcr.io/strausmann/labelyard:${HUB_VERSION:-1.6.0}
    user: "1000:1000"
    environment:
      - "LABELYARD_SECRET_KEY=${LABELYARD_SECRET_KEY:?set LABELYARD_SECRET_KEY}"
      - "LABELYARD_PUBLIC_URL=${LABELYARD_PUBLIC_URL:?set LABELYARD_PUBLIC_URL}"
    volumes:
      - ./data:/data
    networks: [stack]

  client:
    image: example/client:latest
    environment:
      - LABELYARD_URL=http://hub:8000
      - LABELYARD_KEY=CHANGE_ME   # sent as the X-Label-Hub-Key header
    networks: [stack]

networks:
  stack:
```

## Reverse-proxy variants: set `PROXY_IP`

The Traefik, Caddy and Pangolin examples trust `X-Forwarded-For` from exactly one peer, your proxy, via `PROXY_IP`. Give the proxy a fixed address on the shared network (`ipv4_address` in the proxy's own stack) and put that address in `.env`. Without it every client looks like the proxy and the per-IP sign-in limit becomes one bucket for everybody. Do not use `*` or a subnet.

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
- `LABELYARD_SECRET_KEY` — master key for secrets stored in the database. Generate: `openssl rand -base64 32 | tr '+/' '-_'`. Keep it: without it stored secrets cannot be read.
- `LABELYARD_PUBLIC_URL` — required; any `http(s)` URL, including a local one such as `http://labelyard:8000`. For browser use, the address users open the hub at, e.g. `https://labelyard.example.com`
- `LABELYARD_HOST` — your domain (only for reverse-proxy variants), e.g. `labelyard.example.com`
- `LABELYARD_SSO_TRUST_TOKEN` — Pangolin variant only; the same value is injected by the proxy as `X-Pangolin-Token`

Recommended:
- `LABELYARD_WEBHOOK_API_KEY` — random 32-byte string for Spoolman/Grocy webhooks (generate with `openssl rand -hex 32`)

Printers are **not** configured here: add them in the UI under **Settings > Printers**.

First sign-in: a fresh install has no admin key. Set `LABELYARD_BOOTSTRAP_ADMIN_KEY` (32+ characters) for a one-time sign-in that leads to creating your first admin key, or create one inside the container:

```bash
docker exec labelyard labelyard admin create-key --scope admin --name first-admin
```

Optional:
- `LABELYARD_SNIPEIT_URL` + `LABELYARD_SNIPEIT_API_KEY` — Snipe-IT integration
- `LABELYARD_GROCY_URL` + `LABELYARD_GROCY_API_KEY` — Grocy integration
- `LABELYARD_SPOOLMAN_URL` — Spoolman integration

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
- **Webhooks return 401** — check `LABELYARD_WEBHOOK_API_KEY` matches between hub `.env` and Spoolman/Grocy settings.

For more, open a [Discussion](../../discussions) or check existing [issues](../../issues).

## Adding a new printer model

Want to support a model that isn't on the list? See [`docs/plugin-development.md`](../docs/plugin-development.md) and open a [plugin request](../../issues/new?template=plugin_request.yml).
