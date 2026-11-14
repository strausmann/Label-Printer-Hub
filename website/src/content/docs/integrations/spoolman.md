---
title: Spoolman
description: Print spool labels for 3D printing filament from Spoolman.
---

The Spoolman plugin looks up spools in your Spoolman and prints their labels, with a QR code that leads back to the spool. Spoolman needs no API key.

## Setup

Open **Settings > Integrations > Spoolman**, enter the Spoolman address and test the connection. Or set `LABELYARD_SPOOLMAN_URL`.

## Printing

Scan or type a spool ID on the lookup page, or a label link the hub printed earlier (`/spool/…`). From a script, use `{"lookup": {"app": "spoolman", "identifier": "<spool-id>"}}` with `POST /api/v1/print`.

## Printing when a spool changes

Spoolman events can call the hub, which prints the spool's label, with the remaining filament as a third line (for example `851g remaining`) when the event carries it. See [webhooks](/integrations/webhooks/).
