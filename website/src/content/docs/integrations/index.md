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

## Calling Labelyard from another container

Other containers on the same Docker network call the hub directly at `http://<service>:8000` (for example `http://labelyard:8000`) and authenticate with an API key in the `X-Label-Hub-Key` header. No reverse proxy and no SSO are involved.

- **Keys.** Create one per client under Settings > Access and keys, with its scope and, if you want, its printers (see [API keys](/admin/api-keys/)). Calls authenticated by a key header are not subject to the CSRF check; that check only guards browser sessions.
- **`LABELYARD_PUBLIC_URL` is still required, but any `http(s)` address is accepted**, including internal ones such as `http://labelyard:8000`, `http://localhost:8000` or an address on your LAN. It decides cookie security (`Secure` and the `__Host-` prefix when it is `https`) and the allowed `Origin` for state-changing requests authenticated by proxy headers or the Basic bypass. For API-only use inside a stack, a local address is fine.
- **Browsers: set it to the address people open.** If people use the web UI, set the variable to the address they type in. With an `https` value the session cookies are `Secure` and carry the `__Host-` prefix, so a browser does not send them to a plain-`http` internal name; a value that does not match also breaks the sign-in cookies and the `Origin` check.
- **Proxy headers.** `Remote-User` and similar headers count only together with `LABELYARD_SSO_TRUST_TOKEN`, so a neighbouring container cannot pose as an SSO user. Leave the trust token unset if you use no SSO proxy (see [users and SSO](/admin/users-and-sso/)).
- **No published port is needed** for internal use; leave out `ports:`. `examples/compose.backend-only.yml` is an API-only variant.

```yaml
services:
  hub:
    image: ghcr.io/strausmann/labelyard:${HUB_VERSION:-1.6.0}
    user: "1000:1000"
    environment:
      - "LABELYARD_SECRET_KEY=${LABELYARD_SECRET_KEY:?set LABELYARD_SECRET_KEY}"
      - "LABELYARD_PUBLIC_URL=${LABELYARD_PUBLIC_URL:?set LABELYARD_PUBLIC_URL}"
    volumes:
      - ./data:/data
    networks: [stack]

  client:
    image: example/client:latest
    environment:
      - LABELYARD_URL=http://hub:8000
      - LABELYARD_KEY=CHANGE_ME   # sent as the X-Label-Hub-Key header
    networks: [stack]

networks:
  stack:
```

Another app you would like to see as a plugin? Plugins are Python packages; see [contributing](/developers/contributing/).
