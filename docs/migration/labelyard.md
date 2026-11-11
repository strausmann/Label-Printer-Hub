# Migrating to Labelyard

Label Printer Hub is now **Labelyard** (release 1.6.0). This is a rename, not a rewrite: your data, your API keys and your API clients carry over. The reasons and the full compatibility table are in [ADR 0025](../decisions/0025-rename-to-labelyard.md).

## What changes

| Before | After |
|---|---|
| Image `ghcr.io/strausmann/<old-name>-backend` | `ghcr.io/strausmann/labelyard` |
| Image `docker.io/<user>/<old-name>-backend` | `docker.io/<user>/labelyard` |
| Command `printer-hub` | `labelyard` (the old command stays as an alias) |
| Environment prefix `PRINTER_HUB_` | `LABELYARD_` (the old prefix is still read, see [Environment variables](#environment-variables)) |
| PDF font override `PRINTHUB_PDF_FONT` | `LABELYARD_PDF_FONT` (the old name is still read) |
| Repository `strausmann/<old-name>` | `strausmann/labelyard` (GitHub redirects the old address) |
| Example variables `PRINTERHUB_HOST`, `LABEL_HUB_URL`, `LABEL_HUB_KEY` | `LABELYARD_HOST`, `LABELYARD_URL`, `LABELYARD_KEY` |

`<old-name>` stands for the former project name in lower case with hyphens, followed by nothing (repository) or `-backend` (image): the name your current `image:` line shows.

The website is <https://labelyard.app>.

## Upgrade in three steps

1. Change `image:` in your compose file to `ghcr.io/strausmann/labelyard:1.6.0` (or `docker.io/<user>/labelyard:1.6.0`).
2. Pull the image: `docker compose pull`.
3. Restart: `docker compose up -d`.

Your data volume, the database file, API keys, sessions and the `X-Label-Hub-Key` header keep working. If your compose file names the container or the service, you may keep those names; nothing inside the image depends on them.

Coming from 1.4.x? Upgrade your API clients for 1.5.0 first (`/api/v1` paths, without compatibility routes). See the [1.5.0 release notes](https://github.com/strausmann/labelyard/releases/tag/v1.5.0). The rename itself changes no API path.

## What stays the same

- The data directory and the database file name (`printer-hub.db` by default): existing installs find their data where they left it.
- API keys, sessions and the bootstrap flow.
- The `X-Label-Hub-Key` request header and the `lh_` key prefix.
- All `/api/v1` paths and the event stream.
- The registered name of the exported sheet-type file format (`.sheet-type`).

## Environment variables

Renaming is optional for now. The hub reads `LABELYARD_*`; the former `PRINTER_HUB_*` names are still read as a deprecated fallback.

- A `LABELYARD_` variable always wins over its `PRINTER_HUB_` twin.
- Empty values are ignored on both prefixes, so a compose line such as `PRINTER_HUB_X=${PRINTER_HUB_X:-}` never overrides anything.
- If any `PRINTER_HUB_` variable takes effect, the hub logs one deprecation warning at startup. It lists the variable **names** to rename, never the values.
- The old names are read until at least 2.0.0.
- The PDF font override follows the same pattern: `LABELYARD_PDF_FONT` is read first, the old `PRINTHUB_PDF_FONT` when the new one is unset or empty, with a warning that names the variable.

To finish the rename, replace the prefix in your `.env` and compose files and restart:

```bash
sed -i 's/^PRINTER_HUB_/LABELYARD_/' .env
```

## Reverse proxy and Pangolin

Keep your existing resource key (Traefik router name, Pangolin `public-resources.<key>`, Caddy label). Changing the key creates a new resource next to the old one, with a new certificate and new access rules. The examples in `examples/` now use the key `labelyard`; this matters only for new installs.

The hostname variable of the examples is `LABELYARD_HOST`; your own proxy configuration may use any name.

## Old images

The old images (the `<old-name>-backend` images) receive no updates. Watchtower, Renovate or Dependabot rules pinned to them will never offer 1.6.0: change the image name by hand once, as in the three steps above.
