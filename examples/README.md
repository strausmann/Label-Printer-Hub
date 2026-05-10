# Sample compose files

Pre-made deployment recipes for different reverse-proxy stacks. Pick the one that matches your setup.

> **Note:** the container images are not published yet — this project is in early development. These compose files describe the *intended* deployment. They will be functional once the first release lands. Track progress in the [project board](../../projects).

## Two-container architecture

The hub ships as **two containers**:

- `ghcr.io/strausmann/label-printer-hub-backend` — Python/FastAPI, talks to printers, runs the queue
- `ghcr.io/strausmann/label-printer-hub-frontend` — Go web server, serves the UI + PWA assets, proxies API calls and SSE to the backend

Both images are versioned together. Pin both with the same `HUB_VERSION` env var in your `.env`. Mixing major.minor versions between backend and frontend is unsupported.

Only the frontend is exposed to the network. The backend stays on the internal `hub-internal` docker network.

## Which variant should I use?

| Your setup | Use |
|---|---|
| Just a LAN, no reverse proxy | [`compose.standalone.yml`](compose.standalone.yml) |
| You already run Traefik | [`compose.traefik.yml`](compose.traefik.yml) |
| You already run Pangolin | [`compose.pangolin.yml`](compose.pangolin.yml) |
| You already run Caddy | [`compose.caddy.yml`](compose.caddy.yml) |
| Anything else (nginx, HAProxy, ...) | Start with `compose.standalone.yml` and add your own front |

Each file is self-contained — copy the one you need plus `.env.example`.

## Prerequisites

1. **Brother printer** on your network: PT-Series (PT-E550W/P710BT/P750W) or QL-Series (QL-800/810W/820NWB). USB-only models are out of scope at this stage.
2. **Printer IP addresses** noted. Find them via your DHCP leases, the printer's web UI, or:
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
- `PRINTERS` — comma-separated `<slug>:<ip>` pairs, e.g. `pt750w:192.0.2.10,ql820:192.0.2.11`
- `WEBHOOK_API_KEY` — random 32-byte string for Spoolman/Grocy webhooks (generate with `openssl rand -hex 32`)
- `PRINTERHUB_HOST` — your domain (only for reverse-proxy variants), e.g. `printerhub.example.com`

Optional:
- `SNIPEIT_URL` + `SNIPEIT_API_TOKEN` — Snipe-IT integration
- `GROCY_URL` + `GROCY_API_KEY` — Grocy integration
- `SPOOLMAN_URL` — Spoolman integration

## Deploy

```bash
docker compose -f compose.<variant>.yml up -d
```

Then open `https://<your-host>/` (or `http://<host-ip>:8080` for standalone) in a browser.

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

- **Web UI loads but no printers shown** — check `PRINTERS` env var format and that printer IPs are reachable from the container (network namespace).
- **Print job stuck in `printing` state** — usually means the printer never sent the "complete" notification. Check the printer LCD; cover may be open.
- **SSE/live updates not working through Traefik** — make sure the `responseforwarding.flushinterval` label is set (already in the sample).
- **Webhooks return 401** — check `WEBHOOK_API_KEY` matches between hub `.env` and Spoolman/Grocy settings.

For more, open a [Discussion](../../discussions) or check existing [issues](../../issues).

## Adding a new printer model

Want to support a model that isn't on the list? See [`docs/plugin-development.md`](../docs/plugin-development.md) and open a [plugin request](../../issues/new?template=plugin_request.yml).
