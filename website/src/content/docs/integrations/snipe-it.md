---
title: Snipe-IT
description: Print asset and location labels from Snipe-IT.
---

The Snipe-IT plugin looks up assets and locations in your Snipe-IT and prints their labels, with a QR code that leads back to the item.

## Setup

1. In Snipe-IT, create a personal API token for a user that may read assets and locations.
2. In Labelyard, open **Settings > Integrations > Snipe-IT**, enter the Snipe-IT address and the token, and test the connection. Or set `LABELYARD_SNIPEIT_URL` and `LABELYARD_SNIPEIT_API_KEY`.

## Printing

Scan or type one of these on the lookup page:

- an asset tag, for example `AT-0042`,
- a numeric asset ID, for example `42`,
- a location with the `loc:` prefix, for example `loc:17`,
- or a label link the hub printed earlier (`/asset/…`, `/loc/…`).

From a script, the same lookup in one step:

```bash
curl -X POST https://labelyard.example.com/api/v1/print \
  -H "X-Label-Hub-Key: lh_..." -H "Content-Type: application/json" \
  -d '{"content_type": "qr_two_lines", "lookup": {"app": "snipeit", "identifier": "42"}}'
```
