---
title: API keys
description: Create a key per caller, choose its scope and printers, and recover when every admin key is lost.
---

Everything that is not a browser behind an SSO proxy signs in with an API key: the web UI, scripts, other apps. Send it in the `X-Label-Hub-Key` header. The header name and the `lh_` prefix of the keys are kept from the former project name, so existing clients keep working.

## Scopes

| Scope | Allows | Use for |
|---|---|---|
| `read` | Reading only | Monitoring, status pages |
| `print` | Reading and printing | Apps and scripts that print |
| `admin` | Everything, including settings and keys | People who manage the hub |

Each scope includes the ones above it. A `read` or `print` key can also be limited to some printers; an empty list allows all of them. A key with the `admin` scope always acts on every printer, so it cannot be limited: a printer list on an admin key is refused with `422` and `admin_key_not_restrictable`.

## Creating a key

1. Sign in with an admin key and open **Settings > Access and keys**.
2. Create a key with a name that says who uses it and its scope. The form sets no printer list or rate limit; set `allowed_printer_ids` (not for `admin`) and `rate_limit_per_minute` through the API, with `POST /api/v1/admin/api-keys` or `PATCH /api/v1/admin/api-keys/{id}`.
3. Copy the key. It is shown **once**; the hub stores only a bcrypt hash of it.

Create one key per caller, so you can revoke one without touching the others.

## Using a key

```bash
curl -H "X-Label-Hub-Key: lh_..." https://labelyard.example.com/api/v1/printers

curl -X POST https://labelyard.example.com/api/v1/print \
  -H "X-Label-Hub-Key: lh_..." -H "Content-Type: application/json" \
  -d '{"content_type": "qr_two_lines",
       "data": {"title": "Asset 123", "primary_id": "ASSET-123",
                "qr_payload": "https://snipe.example.com/hardware/123"}}'
```

Requests authenticated by a key header are not subject to the CSRF check; that check only guards browser sessions.

## Rate limits

The default is 60 requests per minute and key, adjustable from 1 to 10,000. Above it the hub answers `429` with a `Retry-After` header and the error code `rate_limit_exceeded`.

## First key and recovery

A fresh install has no key; the [installation](/install/) shows the two ways to get the first one. If every admin key is lost, create a new one inside the container. It is printed once:

```bash
docker compose exec labelyard labelyard admin create-key --scope admin --name recovery
```

Whoever can run commands in the container controls the hub anyway, so this adds no new way in. Revoke the lost keys afterwards. Revoking a key also ends every browser session that signed in with it.
