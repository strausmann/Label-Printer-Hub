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

## Printing Grocy's own labels

Grocy has a label printer feature of its own: a print button for products, stock entries, chores, batteries and recipes. Labelyard can be the printer behind that button.

1. Open **Settings > Integrations**. The **Grocy labels** panel sits below the integrations.
2. Switch on **Print Grocy's labels**. Until then, the hub refuses Grocy's labels with `503`.
3. Choose the **default printer**. **First enabled tape printer** picks the first tape printer that is enabled.
4. For each label type, choose a layout and a printer. A type left at **Same as default** goes to the default printer. The layout with a detail line needs a second line from Grocy, which Grocy sends only for a stock entry with a due date. Any other label with that layout prints without the detail line, and the job records the layout it printed.
5. Press **Save**.
6. Create an API key with the `print` scope under **Settings > Access and keys**, limited to the printers of these labels (see [keys in a URL](/admin/api-keys/#keys-in-a-url)).
7. Copy the lines the panel shows into Grocy's `data/config.php` and replace `<print-key>` with that key:

```php
Setting('FEATURE_FLAG_LABEL_PRINTER', true);
Setting('LABEL_PRINTER_WEBHOOK', 'https://hub.example.invalid/api/v1/webhook/grocy/label?token=<print-key>');
Setting('LABEL_PRINTER_RUN_SERVER', true);
Setting('LABEL_PRINTER_HOOK_JSON', true);
```

The panel fills in the address from `LABELYARD_PUBLIC_URL`. `LABEL_PRINTER_RUN_SERVER` must be `true`: Grocy then calls the hub from its server, not from the browser. `LABEL_PRINTER_HOOK_JSON` makes Grocy send the label as JSON, which the hub requires.

Use a key with the print scope, restricted to the label printer. Grocy writes the address with the key to its own log. It also shows the address to the Grocy user when the hub refuses a label or does not answer within 2 seconds.

The hub answers within two seconds with `202` and the ID of a new job; printing happens after that answer. So Grocy reports success even when the label cannot print. A printer that is offline or out of tape, or a label the hub cannot read, ends as a **failed** job. Failed labels show on the **Jobs** page with the reason, and can be retried there.

A proxy with single sign-on must let `/api/v1/webhook/` through, as for the other [webhooks](/integrations/webhooks/#behind-a-proxy-with-sso).
