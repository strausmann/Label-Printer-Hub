---
title: Configuration
description: Every LABELYARD_ environment variable, its default and what it does.
---

<!-- This page is generated from the backend settings by `website/scripts/gen-config-reference.py`; edit the descriptions in `website/src/config-descriptions.yml`, not here. -->

Every setting is an environment variable with the `LABELYARD_` prefix. The names of earlier releases are still read until at least 2.0.0, and a `LABELYARD_` variable always wins; an empty value counts as not set on both prefixes. See [upgrades](/admin/upgrades/) for the details.

Printers have no variables: you add them in the web UI under Settings > Printers.

## Required

### `LABELYARD_SECRET_KEY`

**Required**

Master key for the secrets stored in the database: base64url text of exactly 32 bytes. Generate it with `openssl rand -base64 32 | tr '+/' '-_'` and keep it, without it stored secrets cannot be read.

Secret: never logged or shown.

### `LABELYARD_PUBLIC_URL`

**Required**

Any `http(s)` address, local ones included. Set it to the address people open the web UI at. With `https` the session cookies are `Secure` and `__Host-` prefixed; it is also the allowed `Origin` of state-changing requests.

Shown read-only in the web UI; it always comes from the environment.

## Optional

### `LABELYARD_DATABASE_URL`

Default: `sqlite+aiosqlite:////data/printer-hub.db`

Database connection. The default keeps the SQLite file in the `/data` volume; existing installs keep finding their data under this name.

### `LABELYARD_BOOTSTRAP_ADMIN_KEY`

Default: empty

One-time key (32 characters or more) that signs you in while no admin key exists, so you can create the first one. Empty disables it; it is rejected as soon as an enabled admin key exists.

Secret: never logged or shown.

### `LABELYARD_WEB_DIST_DIR`

Default: `/opt/app/web`

Directory of the built web UI that the backend serves. The image sets it; change it only for a custom build.

### `LABELYARD_PAPERLESS_URL`

Default: empty

Paperless-ngx base address for the connection test under Settings > Integrations.

Also set in the web UI; a value set here wins and locks the field there.

### `LABELYARD_PAPERLESS_TOKEN`

Default: empty

Paperless-ngx API token.

Secret: never logged or shown.

Also set in the web UI; a value set here wins and locks the field there.

### `LABELYARD_PAPERLESS_TIMEOUT`

Default: `5.0`

Seconds to wait for Paperless-ngx.

Also set in the web UI; a value set here wins and locks the field there.

### `LABELYARD_WEBHOOK_API_KEY`

Default: empty

Shared key for the inbound Spoolman and Grocy webhooks, sent as the `X-API-Key` header. At least 32 characters (`openssl rand -hex 32`). Empty answers every webhook call with 503.

Secret: never logged or shown.

Also set in the web UI; a value set here wins and locks the field there.

### `LABELYARD_SNIPEIT_URL`

Default: empty

Snipe-IT base address.

Also set in the web UI; a value set here wins and locks the field there.

### `LABELYARD_SNIPEIT_API_KEY`

Default: empty

Snipe-IT API token (bearer).

Secret: never logged or shown.

Also set in the web UI; a value set here wins and locks the field there.

### `LABELYARD_SNIPEIT_TIMEOUT`

Default: `5.0`

Seconds to wait for Snipe-IT.

Also set in the web UI; a value set here wins and locks the field there.

### `LABELYARD_GROCY_URL`

Default: empty

Grocy base address.

Also set in the web UI; a value set here wins and locks the field there.

### `LABELYARD_GROCY_API_KEY`

Default: empty

Grocy API key.

Secret: never logged or shown.

Also set in the web UI; a value set here wins and locks the field there.

### `LABELYARD_GROCY_TIMEOUT`

Default: `5.0`

Seconds to wait for Grocy.

Also set in the web UI; a value set here wins and locks the field there.

### `LABELYARD_SPOOLMAN_URL`

Default: empty

Spoolman base address. Spoolman needs no key.

Also set in the web UI; a value set here wins and locks the field there.

### `LABELYARD_SPOOLMAN_TIMEOUT`

Default: `5.0`

Seconds to wait for Spoolman.

Also set in the web UI; a value set here wins and locks the field there.

### `LABELYARD_SERVER_PORT`

Default: `8090`

Port of the process when it runs outside the image. The image listens on `PORT` (8000) instead.

### `LABELYARD_LOG_LEVEL`

Default: `INFO`

One of `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. Any other value stops the start with an error.

### `LABELYARD_SIGN_IN_LIMIT_PER_MINUTE`

Default: `10`

Browser sign-in attempts per minute and client address. Behind a proxy all clients share the proxy's address unless the proxy is trusted (`FORWARDED_ALLOW_IPS`).

### `LABELYARD_SSE_QUEUE_SIZE`

Default: `32`

Events buffered per live-update subscriber; the oldest is dropped when it is full.

### `LABELYARD_SSE_IDLE_TIMEOUT_S`

Default: `300.0`

Seconds without activity before the server closes a live-update connection.

### `LABELYARD_SSE_MAX_SUBSCRIBERS`

Default: `100`

Concurrent live-update connections per printer; more are answered with 429.

### `LABELYARD_SSE_HEARTBEAT_S`

Default: `30.0`

Seconds between keep-alive frames when no events flow.

### `LABELYARD_SSE_PROBE_INTERVAL_S`

Default: `30.0`

Seconds between two status queries (SNMP) of each printer.

### `LABELYARD_TRUST_LEGACY_PANGOLIN_USER`

Default: `False`

Opt in to the legacy `X-Pangolin-User` header without a trust token. Off by default; it never creates a browser session.

### `LABELYARD_TRUST_PANGOLIN_BASIC_BYPASS`

Default: `False`

Opt in to the Pangolin `Authorization: Basic` bypass credential. Off by default; its state-changing requests need an `Origin` equal to the public address.

### `LABELYARD_PANGOLIN_BYPASS_SCOPE_DOWNGRADE`

Default: `False`

Limits the Basic bypass, if it is enabled at all, to `read` scope.

### `LABELYARD_SSO_USER_HEADER`

Default: `Remote-User`

Header that carries the signed-in user from the SSO proxy.

### `LABELYARD_SSO_TRUST_HEADER`

Default: `X-Pangolin-Token`

Header that carries the trust token from the SSO proxy.

### `LABELYARD_SSO_TRUST_TOKEN`

Default: empty

Shared secret the proxy sends in the trust header. Only with it does the user header count, so a neighbouring container cannot pose as a user. Empty disables sign-in through the proxy.

### `LABELYARD_JOB_RETENTION_DAYS`

Default: `30`

Days after which finished jobs (done, failed, cancelled) are deleted.

Also set in the web UI; a value set here wins and locks the field there.
