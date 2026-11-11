---
title: Troubleshooting
description: The common problems after installing, with their cause and the fix.
---

## The hub does not start

- **`LABELYARD_SECRET_KEY must decode to exactly 32 bytes`.** Generate the key again with `openssl rand -base64 32 | tr '+/' '-_'`.
- **A validation error about the log level.** `LABELYARD_LOG_LEVEL` takes `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL`, in capitals.
- **An unknown key in `.env`.** A `.env` key with the hub's prefix that matches no setting stops the start. Remove or rename it; the [configuration reference](/reference/configuration/) lists every valid name.

## I cannot sign in

- **"Sign in with an API key that has print or admin scope."** A `read` key cannot sign in.
- **The bootstrap key no longer works.** It is rejected as soon as an admin key exists; sign in with that key, or create one in the container (see [API keys](/admin/api-keys/)).
- **Sign-in works but the session is lost at once.** The browser address differs from `LABELYARD_PUBLIC_URL`, or the address is `http` while the public address is `https`. Open exactly the configured address.

## Printers

- **No printers on the overview.** Add them under Settings > Printers; printers are not configured through variables.
- **The printer shows offline.** Check from the Docker host: `nc -zv <printer-address> 9100`, and SNMP as described under [connecting printers](/install/printers/).
- **A job stays in printing.** The printer never reported the end of the job. Look at the printer: a cover may be open, or the tape ran out.
- **Prints on a page printer are off by a few millimetres.** Calibrate the tray (see [connecting printers](/install/printers/)).

## Live updates and webhooks

- **The status does not update without a reload.** The proxy buffers the event stream; see the flush settings under [reverse proxy](/install/reverse-proxy/).
- **Webhooks answer 401.** The `X-API-Key` header does not match `LABELYARD_WEBHOOK_API_KEY`.
- **Webhooks answer 503.** `LABELYARD_WEBHOOK_API_KEY` is not set.

## Still stuck

Search the [existing issues](https://github.com/strausmann/labelyard/issues) or open a [discussion](https://github.com/strausmann/labelyard/discussions). Include the version from the About page and the log lines around the problem; remove addresses and keys before posting.
