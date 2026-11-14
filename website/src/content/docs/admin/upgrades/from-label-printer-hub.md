---
title: From Label Printer Hub to Labelyard
description: Labelyard is the new name of Label Printer Hub. What changes, what stays and how to upgrade in three steps.
sidebar:
  order: 2
---

Label Printer Hub is now **Labelyard** (release 1.6.0). This is a rename, not a rewrite: your data, your API keys and your API clients carry over. The reasons and the full compatibility table are in the [rename decision](https://github.com/strausmann/labelyard/blob/main/docs/decisions/0026-rename-to-labelyard.md).

## What changes

| Before | After |
|---|---|
| Image `ghcr.io/strausmann/label-printer-hub-backend` | `ghcr.io/strausmann/labelyard` |
| Image `docker.io/<user>/label-printer-hub-backend` | `docker.io/<user>/labelyard` |
| Command `printer-hub` | `labelyard` (the old command stays as an alias) |
| Environment prefix `PRINTER_HUB_` | `LABELYARD_` (the old prefix is still read, see [environment variables](#environment-variables)) |
| PDF font override `PRINTHUB_PDF_FONT` | `LABELYARD_PDF_FONT` (the old name is still read) |
| Repository `strausmann/Label-Printer-Hub` | `strausmann/labelyard` (GitHub redirects the old address) |
| Example variables `PRINTERHUB_HOST`, `LABEL_HUB_URL`, `LABEL_HUB_KEY` | `LABELYARD_HOST`, `LABELYARD_URL`, `LABELYARD_KEY` |
| User name of the print jobs sent to page printers (IPP) `label-printer-hub` | `labelyard`: update user allow lists and per-user accounting on the print server |

## Upgrade in three steps

Using a page printer? Let its queue drain first. 1.6.0 still knows the print jobs 1.5.x sent as its own, but it asks about them under the new user name. A print server that lets only a job's owner cancel it (the CUPS default) may then refuse to cancel a running 1.5.x job.

1. Change `image:` in your compose file to `ghcr.io/strausmann/labelyard:1.6.0` (or `docker.io/<user>/labelyard:1.6.0`).
2. Pull the image: `docker compose pull`.
3. Restart: `docker compose up -d`.

Your data volume, the database file, API keys, sessions and the `X-Label-Hub-Key` header keep working. If your compose file names the container or the service, you may keep those names; nothing inside the image depends on them.

Coming from 1.4.x? Upgrade your API clients for 1.5.0 first (`/api/v1` paths, without compatibility routes); see the [1.5.0 release notes](https://github.com/strausmann/labelyard/releases/tag/v1.5.0). The rename itself changes no API path.

## What stays the same

- The data directory and the database file name (`printer-hub.db` by default): existing installs find their data where they left it.
- API keys, sessions and the bootstrap flow.
- The `X-Label-Hub-Key` request header and the `lh_` key prefix.
- All `/api/v1` paths and the event stream.
- The registered name of the exported sheet-type file format (`.sheet-type`).

## Behaviour changes

- **The server port variable now takes effect.** `LABELYARD_SERVER_PORT` (and the old `PRINTER_HUB_SERVER_PORT`) was documented but ignored. The container now listens on the port it names and falls back to `PORT`, then `8000`. A `.env` file copied from an older `.env.example` may still contain `LABELYARD_SERVER_PORT=8090`: delete that line, or set it to the port your compose file maps (`8000` by default). Afterwards `/healthz` on the mapped port must answer. If the port is not `8000`, the hub logs one warning at startup that names the variable, in the container output (`docker logs`) and in the hub's log view.
- **Installed web apps keep the old icon for a while.** A home-screen app installed before 1.6.0 shows the old name and icon until the browser refreshes its manifest. On iOS that never happens by itself: remove the app from the home screen and add it again.

## Environment variables

Renaming is optional for now. The hub reads `LABELYARD_*`; the former `PRINTER_HUB_*` names are still read as a deprecated fallback.

- A `LABELYARD_` variable always wins over its `PRINTER_HUB_` twin.
- Empty values are ignored on both prefixes, so a compose line such as `PRINTER_HUB_X=${PRINTER_HUB_X:-}` never overrides anything.
- At startup the hub logs one warning line listing the old names that take effect, so you know what to rename. You find it in the container output (`docker logs`) and in the hub's log view on the System page. If an old name is overridden by a `LABELYARD_` twin, a second line lists those ignored names. Both lines carry **names** only, never values.
- The old names are read until at least 2.0.0.
- The PDF font override follows the same pattern: `LABELYARD_PDF_FONT` is read first, the old `PRINTHUB_PDF_FONT` when the new one is unset or empty, with a warning that names the variable.

To finish the rename in a `.env` file, replace the prefix and restart:

```bash
sed -i 's/^PRINTER_HUB_/LABELYARD_/' .env
```

This only touches the `.env` file. Compose files that name the variables themselves (for example `PRINTER_HUB_SECRET_KEY=${PRINTER_HUB_SECRET_KEY:?...}`) must be changed by hand, on both sides of each line, or compose still asks for the old name.

## Reverse proxy and Pangolin

Keep your existing resource key (Traefik router name, Pangolin `public-resources.<key>`, Caddy label). Changing the key creates a new resource next to the old one, with a new certificate and new access rules. The examples now use the key `labelyard`; this matters only for new installs.

The hostname variable of the examples is `LABELYARD_HOST`; your own proxy configuration may use any name.

## Old images

The old images (`label-printer-hub-backend` on both registries) receive no updates. Watchtower, Renovate or Dependabot rules pinned to them will never offer 1.6.0: change the image name by hand once, as in the three steps above.
