---
title: HTTPS
description: Why the hub should be reached over HTTPS, and what changes when it is.
---

Labelyard itself speaks plain HTTP on port 8000. HTTPS comes from the reverse proxy in front of it, which also gets the certificate (Let's Encrypt in the Traefik and Caddy examples, Pangolin's own for Pangolin).

## Why it matters

- **The camera needs it.** Browsers only allow the camera on a secure page or on `localhost`. Scanning on a phone therefore needs the `https` address; without it, the scan page lets you pick a photo of the code instead.
- **The cookies depend on it.** When `LABELYARD_PUBLIC_URL` starts with `https`, the session cookies are `Secure` and carry the `__Host-` prefix. A browser will then not send them over plain `http`, so open the hub at exactly the address you configured.
- **Installing the app needs it.** Phones install a progressive web app only from a secure origin.

## Checklist

1. The proxy terminates TLS for your host name and forwards to `labelyard:8000`.
2. `LABELYARD_PUBLIC_URL` is the `https` address, without a path.
3. `PROXY_IP` (and so `FORWARDED_ALLOW_IPS`) is the proxy's fixed address, so the hub sees the real client addresses.
4. `curl -fsS https://<your-host>/healthz` answers with `"status": "ok"` from outside.

Inside your own stack, other containers may still call `http://labelyard:8000` directly with an API key; the public address only matters for browsers.
