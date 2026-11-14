---
title: Webhooks
description: Let Spoolman and Grocy print a label when something changes, with a shared webhook key.
---

Two endpoints accept events and print a label in response. A third one prints [Grocy's own labels](#grocys-label-printer).

`POST /api/v1/webhook/spoolman` prints the spool's label. `quantity` is the remaining filament in grams and optional:

```json
{ "spool_id": "17", "type": "updated", "quantity": 640 }
```

`POST /api/v1/webhook/grocy` prints the product's label. `quantity` is optional:

```json
{ "product_id": "42", "type": "stock_added", "quantity": 2 }
```

## The quantity on the label

A `quantity` in range prints as the label's third line, in the language set under **Settings > General**, not the language of the sender. Without a `quantity`, or with one out of range, the label keeps its two lines. It is never a number of copies: one label prints per event.

| Source | `quantity` | English | German |
|---|---|---|---|
| Spoolman | 0 to 1000000, rounded half up to whole grams | `851g remaining` | `851 g übrig` |
| Grocy | -1000000 to 1000000, rounded half up to two decimals, with a sign | `Stock change: +2` | `Bestandsänderung: +2` (a decimal comma: `-1,5`) |

A third language falls back to English.

Each call answers `202` with the ID of the new job, which goes to the first enabled tape printer. The label data comes from the [Spoolman](/integrations/spoolman/) or [Grocy](/integrations/grocy/) plugin, so the integration must be connected.

## The webhook key

Webhooks do not use API keys. They share one secret, sent in the `X-API-Key` header:

```bash
openssl rand -hex 32   # at least 32 characters
```

Set it as `LABELYARD_WEBHOOK_API_KEY` (or in Settings > Access and keys) and configure the same value in the sending app.

| Answer | Meaning |
|---|---|
| `202` | Accepted; the job is queued |
| `401` | The `X-API-Key` header is missing or wrong |
| `422` | A required field of the body is missing |
| `502` | The plugin could not look the item up in its app |
| `503` | No webhook key is set, or no tape printer is enabled |

## Grocy's label printer

`POST /api/v1/webhook/grocy/label` is the address Grocy's own label printer feature calls (`LABEL_PRINTER_WEBHOOK`); set it up as described under [printing Grocy's own labels](/integrations/grocy/#printing-grocys-own-labels). Unlike the two endpoints above it does not use the webhook key. Grocy sends no headers, so an API key with the `print` scope travels in the `token` parameter of the address (see [keys in a URL](/admin/api-keys/#keys-in-a-url)). The `X-Label-Hub-Key` header works too and wins when both are sent.

The printer and the layout come from the mapping of the label's type in **Settings > Integrations**. The hub answers before it prints, within two seconds, because Grocy waits no longer and shows its user the address, key included, when the answer is an error or late.

| Answer | Meaning |
|---|---|
| `202` | Accepted, with the ID of the job. A label the hub cannot read (`grocy_label_invalid`) or whose name field does not match its type (`grocy_label_mismatch`) also answers `202`, with a failed job |
| `401` | `invalid_token`: the key is missing, unknown, disabled or expired |
| `403` | `insufficient_scope` (a `read` key), `token_scope_too_wide` (an `admin` key) or `printer_not_allowed` (the key may not use the label's printer) |
| `413` | `body_too_large`: the body is larger than 1 MiB |
| `415` | `json_required`: set `LABEL_PRINTER_HOOK_JSON` to `true` in Grocy |
| `429` | `rate_limit_exceeded`: the key's limit per minute, with `Retry-After` |
| `503` | `grocy_label_disabled` (switched off in the settings), `grocy_label_printer_unavailable` (the mapped printer is unknown, disabled or a page printer), or no tape printer is enabled |

A printer failure after the answer (offline, no tape) sets the job to failed with the same code `POST /api/v1/print` would answer. No answer names a printer.

## Behind a proxy with SSO

The apps that send webhooks cannot sign in to an SSO proxy. Route `/api/v1/webhook/` around it: the Traefik example has a separate router for the path, and the Pangolin example a second resource with authentication bypassed (see [reverse proxy](/install/reverse-proxy/)). The webhook key still protects the endpoints.
