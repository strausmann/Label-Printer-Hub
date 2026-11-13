# Getting started

This page takes you from nothing to a printed label: start the hub, sign in, add a printer, print, install the web app on a phone, and connect Spoolman or Grocy.

## 1. Start the hub

The hub is one container. Pick the compose file in [`examples/`](../examples/) that matches your setup (standalone, Traefik, Pangolin, Caddy; [`examples/README.md`](../examples/README.md) explains the variants) and copy it together with `.env.example`.

```bash
git clone https://github.com/strausmann/Label-Printer-Hub.git
cd Label-Printer-Hub/examples
cp .env.example .env
```

Set at least these two values in `.env`:

| Variable | Value |
|---|---|
| `PRINTER_HUB_SECRET_KEY` | encrypts the secrets stored in the database; generate with `openssl rand -base64 32 \| tr '+/' '-_'` |
| `PRINTER_HUB_PUBLIC_URL` | the address you open the hub at, for example `http://localhost:8000` or `https://printerhub.example.com` |

Keep the secret key: without it the stored secrets cannot be decrypted.

```bash
docker compose -f compose.standalone.yml up -d
curl http://localhost:8000/healthz
curl http://localhost:8000/api/v1/info
```

Both calls answer with `200`. To try the hub without any printer or reverse proxy, `docker compose -f ../dev/docker-compose.smoke.yml up --build` (from `examples/`) builds it from the local tree.

### Sign in

A fresh install has no API key. Create the first admin key inside the container:

```bash
docker exec label-printer-hub-backend printer-hub admin create-key --scope admin --name first-admin
```

Open the hub in a browser and sign in with that key. (Alternative: set `PRINTER_HUB_BOOTSTRAP_ADMIN_KEY` to a one-time key of 32 or more characters and use it for the first sign-in.) Further keys, with the scopes `read`, `print` or `admin` and an optional restriction to chosen printers, are made under **Settings > Access and keys**.

## 2. Add your first printer

Printers are not configured in `.env`. Open **Settings > Printers** and add one:

| Field | Meaning |
|---|---|
| Name | what people see |
| Slug | a short lower-case name for addresses and the API (3 to 64 letters, digits and dashes); it cannot be changed later |
| Driver | *P-touch (PT)* for a PT-Series tape printer, *Brother QL* for a QL-Series printer, *Page printer (IPP)* for a printer of sheets of labels (it takes the printer's address and is read once before saving) |
| Model | tape printers only, required; the form offers the model of the chosen driver |
| Host and Port | tape printers only: the printer's address and TCP port `9100`, for example `192.0.2.20` |
| IPP address | page printers only: the printer's IPP address, for example `ipp://printer.example.invalid:631/ipp/print`; **Read printer** reads it once before saving |
| Verify the printer certificate | page printers only, for an `ipps://` or `https://` address; leave it on unless the printer has no valid certificate |
| Trays | page printers only, after **Read printer**: turn off the trays you do not use and choose the default tray |
| Queue timeout (seconds) | how long the queue waits for the printer, 1 to 600 |

A page printer appears on the overview with its state and supplies, read over IPP. A tape printer added here shows **Not monitored** and **Tape not known** at first: the hub does not read its status until status discovery is on, see [Turn on status discovery](#turn-on-status-discovery). Once it is on and the printer still shows as offline, check that the hub's container can reach the printer's address on the port.

### Turn on status discovery

The hub reads a tape printer's status and tape over SNMP, but only when status discovery is on for that printer. A printer added under **Settings > Printers** has it off, and the form has no switch for it yet ([#296](https://github.com/strausmann/label-printer-hub/issues/296)). Until then, a test print on that printer is refused with "no current status". An admin turns discovery on through the admin API, with the printer's slug and its current host and port (the `connection` object is replaced as a whole):

```bash
curl -X PUT http://localhost:8000/api/v1/admin/printers/<slug> \
  -H "X-Label-Hub-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"connection": {"host": "192.0.2.20", "port": 9100,
                      "snmp": {"discover": true, "community": "public"}}}'
```

`snmp.discover` switches the status reading on; `snmp.community` is the printer's SNMP read community (`public` unless you changed it on the printer, at most 64 characters, required when `discover` is `true`). The hub re-wires the printer before it answers; the overview shows its state after the first reading, within about 30 seconds. The full request body is in the interactive reference at `/docs` on a running hub (`PUT /api/v1/admin/printers/{slug}`).

A tape printer cannot report the tape colour over the network. When the roll changes, the hub asks you once which colour is loaded.

## 3. Print your first label

In the web UI, open the print dialog for an item (search for an item of Snipe-IT, Grocy or Spoolman, or scan a code), choose the printer, the layout and the number of copies, check the preview and press **Print**. The job appears under **Jobs** and changes state as the queue works through it.

The same from a script, with an API key of scope `print`:

```bash
curl -X POST http://localhost:8000/api/v1/print \
  -H "X-Label-Hub-Key: $LABEL_HUB_KEY" \
  -H "Content-Type: application/json" \
  -d '{
        "content_type": "qr_two_lines",
        "data": {"title": "Asset 123", "primary_id": "ASSET-123",
                 "qr_payload": "https://assets.example.com/hardware/123"},
        "options": {"copies": 1}
      }'
```

The answer is `202` with a `job_id`; `GET /api/v1/jobs/<job_id>` shows the state. Instead of `data` you can send `"lookup": {"app": "snipeit", "identifier": "123"}` and the hub fetches the label content from the app. The full request body and the error codes are in the [README](../README.md#rest-api-surface); the interactive reference is `/docs` on a running hub.

To connect Snipe-IT, Grocy or Spoolman for lookups, open **Settings > Integrations** and enter the address and the key of the app. Changes apply on the next request, without a restart.

## 4. Install the web app on a phone

The hub is a progressive web app: it can be added to the home screen and opens like an app, and the camera can scan barcodes.

Browsers allow installing and camera access only on a secure origin: serve the hub over `https://` (the reverse-proxy examples do) or open it on `localhost`.

- **Android (Chrome):** open the hub, menu > *Install app* (or *Add to Home screen*).
- **iPhone and iPad (Safari):** open the hub, Share > *Add to Home Screen*.
- **Desktop (Chrome, Edge):** the install icon in the address bar.

The app has a **Scan** shortcut on the home-screen icon. Set `PRINTER_HUB_PUBLIC_URL` to the address people open; with an `https` value the session cookies are `Secure`, so a browser will not send them to a plain-`http` name of the same hub.

## 5. Webhooks: print when something happens

The hub accepts events from Spoolman and Grocy and prints the label of the item the event names.

| Method and path | Payload fields |
|---|---|
| `POST /api/v1/webhook/spoolman` | `spool_id` (string), `type` (string), optional `quantity` |
| `POST /api/v1/webhook/grocy` | `product_id` (string), `type` (string), optional `quantity` |

Unknown extra fields are ignored; a missing or mistyped required field answers `422`.

1. Generate a key of at least 32 characters, for example `openssl rand -hex 32`, and set it as `PRINTER_HUB_WEBHOOK_API_KEY` in the hub's `.env`. Restart the hub.
2. Send it as the `X-API-Key` header with every call. Without a configured key the webhooks answer `503`; with a wrong key `401`.
3. More than `PRINTER_HUB_WEBHOOK_LIMIT_PER_MINUTE` calls per minute (default 120, both routes together) answer `429` with `Retry-After`.

```bash
curl -X POST http://localhost:8000/api/v1/webhook/spoolman \
  -H "X-API-Key: $PRINTER_HUB_WEBHOOK_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"spool_id": "42", "type": "updated"}'
```

What happens on a valid call:

- The hub prints **one** `qr_two_lines` label on the **first enabled tape printer** (a page printer is never used for webhooks). `quantity` is accepted but does not change the number of labels.
- The label content comes from the integration (Spoolman or Grocy), so that integration must be configured; otherwise the call answers `503` with `integration_not_configured`. An unknown spool or product answers `404` with `app-lookup-not-found`.
- Printer problems (no tape, printer offline or disabled) answer like `POST /api/v1/print`: `409`, `422`, `502` or `503`. Nothing is queued in these cases.
- On success the answer is `202` with the job id. The webhook key cannot read the job; an admin or a single-sign-on user sees it under **Jobs**.

Behind Pangolin, give the webhook path `/api/v1/webhook/` its own resource that bypasses single sign-on, since the sender cannot log in; the key protects it ([`examples/compose.pangolin.yml`](../examples/compose.pangolin.yml)).

## Where to go next

- [Architecture](architecture.md) and the [decisions](decisions/) behind it
- [Plugin development](plugin-development.md): add a printer model or a lookup plugin
- [`examples/README.md`](../examples/README.md): reverse-proxy variants, using the hub from other containers
- Troubleshooting for the usual first-run problems is at the end of [`examples/README.md`](../examples/README.md)
