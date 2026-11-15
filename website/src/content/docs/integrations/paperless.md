---
title: Paperless-ngx
description: Print labels for documents in Paperless-ngx through the Labelyard API.
---

Paperless-ngx has no lookup plugin in Labelyard. Labels for documents, such as archive serial number (ASN) labels, are printed by calling the hub's API.

## Setup

1. In Labelyard, create an API key with `print` scope for this purpose (see [API keys](/admin/api-keys/)).
2. Optional: under **Settings > Integrations > Paperless** enter the Paperless address and an API token and test the connection. Or set `LABELYARD_PAPERLESS_URL` and `LABELYARD_PAPERLESS_TOKEN`.

## Printing a label

Send the text and the QR content yourself in `data`:

```bash
curl -X POST https://labelyard.example.com/api/v1/print \
  -H "X-Label-Hub-Key: lh_..." -H "Content-Type: application/json" \
  -d '{"content_type": "qr_one_line",
       "data": {"title": "ASN 000123", "primary_id": "ASN000123",
                "qr_payload": "ASN000123"}}'
```

The response carries the job ID; the [print queue](/using/queue/) shows how to follow it. For many labels at once onto a sheet, see the sheet endpoints in the [API reference](/developers/api/).
