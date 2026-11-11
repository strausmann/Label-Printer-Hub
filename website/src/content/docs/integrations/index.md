---
title: Integrations
description: How Labelyard talks to the apps your labels come from, through plugins, webhooks and its API.
sidebar:
  label: Overview
---

There are three ways an app and Labelyard work together:

| Way | Who starts it | Apps |
|---|---|---|
| **Plugin** | You, in Labelyard: you scan or type an ID, the plugin looks the item up in its app and the hub prints its label | [Snipe-IT](/integrations/snipe-it/), [Grocy](/integrations/grocy/), [Spoolman](/integrations/spoolman/) |
| **Webhook** | The app: an event in it sends a request, and the hub prints | [Spoolman and Grocy](/integrations/webhooks/) |
| **API** | The app: it calls the hub's REST API with its own key | [Paperless](/integrations/paperless/), [Kept](/integrations/kept/), your own scripts |

## Connecting an app

Open **Settings > Integrations** with an admin key. For each app enter its address and, where it needs one, its API key or token, and use the test button to check the connection. The change applies at the next request; no restart.

The same values can be set as environment variables, for example `LABELYARD_SNIPEIT_URL` and `LABELYARD_SNIPEIT_API_KEY` (all of them are in the [configuration reference](/reference/configuration/)). A variable wins and locks the field in the UI.

A secret belongs to the address it was saved with: when you change an app's address, enter its secret again.

## Looking items up from scripts

`GET /api/v1/lookup/{app}/{id}` returns what a plugin found for an ID, without printing; `POST /api/v1/print` with a `lookup` object prints it in one step. See the [API reference](/developers/api/).

Another app you would like to see as a plugin? Plugins are Python packages; see [contributing](/developers/contributing/).
