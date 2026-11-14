---
title: Webhooks
description: Let Spoolman and Grocy print a label when something changes, with a shared webhook key.
---

Two endpoints accept events and print a label in response.

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

## Behind a proxy with SSO

The apps that send webhooks cannot sign in to an SSO proxy. Route `/api/v1/webhook/` around it: the Traefik example has a separate router for the path, and the Pangolin example a second resource with authentication bypassed (see [reverse proxy](/install/reverse-proxy/)). The webhook key still protects the endpoints.
