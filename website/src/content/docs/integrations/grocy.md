---
title: Grocy
description: Print product labels from Grocy, on demand or when stock changes.
---

The Grocy plugin looks up products in your Grocy and prints their labels, with a QR code that leads back to the product.

## Setup

1. In Grocy, create an API key under the user menu.
2. In Labelyard, open **Settings > Integrations > Grocy**, enter the Grocy address and the key, and test the connection. Or set `LABELYARD_GROCY_URL` and `LABELYARD_GROCY_API_KEY`.

## Printing

Scan or type a product ID or a product barcode on the lookup page, or a label link the hub printed earlier (`/product/…`). From a script, use `{"lookup": {"app": "grocy", "identifier": "<product-id>"}}` with `POST /api/v1/print`.

## Printing when stock changes

Grocy can call the hub when stock is added or removed, and the hub prints a label for the product, with the stock change as a third line (for example `Stock change: +2`) when the event carries one. See [webhooks](/integrations/webhooks/).
