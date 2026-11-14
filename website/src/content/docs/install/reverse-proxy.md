---
title: Behind a reverse proxy
description: Put Labelyard behind Caddy, Traefik or Pangolin, trust exactly one proxy and keep the live updates flowing.
sidebar:
  label: Reverse proxy
---

The repository has a ready compose file for each of these proxies under `examples/`: `compose.caddy.yml`, `compose.traefik.yml` and `compose.pangolin.yml`. Each runs the same image; only the network and the labels differ. For anything else (nginx, HAProxy) start from the standalone file and add your own front.

## Three things every proxy setup needs

1. **Trust exactly one peer.** Labelyard reads `X-Forwarded-For` only from the address in `FORWARDED_ALLOW_IPS`. Give your proxy a fixed address on the shared network and set `PROXY_IP` in `.env` to it; the examples pass it on. Without it every client looks like the proxy, and the per-address sign-in limit becomes one bucket for everybody. Do not use `*` or a subnet.
2. **Set the public address.** `LABELYARD_PUBLIC_URL` is the `https` address people open, for example `https://labelyard.example.com`, and `LABELYARD_HOST` the host name the examples route.
3. **Do not buffer the event stream.** Live updates arrive as Server-Sent Events on `/api/v1/events`. The Caddy example sets `flush_interval -1`, the Traefik example `responseforwarding.flushinterval=100ms`. Settings for other proxies and how to check the stream: [event stream and reverse proxies](/developers/architecture/sse/).

Pin the proxy's address in its own stack (`ipv4_address`). An unpinned address can go to another container after a restart, and that container would then be trusted to set `X-Forwarded-For`. The sign-in limit counts IPv6 clients per /64 network (a unique-local or link-local address counts on its own), and an IPv4-mapped IPv6 address counts as its IPv4 address. If a trusted proxy forwards a value that is not an IP address, or the request arrives over a unix socket, all such sign-ins share one bucket.

## Caddy

The example uses the labels of caddy-docker-proxy:

```yaml
labels:
  caddy: ${LABELYARD_HOST}
  caddy.reverse_proxy: "{{upstreams 8000}}"
  caddy.reverse_proxy.flush_interval: "-1"
```

## Traefik

Two routers point at one service. The second one serves the webhook paths with a higher priority, so you can give it its own middlewares (or none, if the main router has an SSO middleware):

```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.labelyard.rule=Host(`${LABELYARD_HOST}`)"
  - "traefik.http.routers.labelyard.entrypoints=websecure"
  - "traefik.http.routers.labelyard.tls.certresolver=letsencrypt"
  - "traefik.http.routers.labelyard-webhooks.rule=Host(`${LABELYARD_HOST}`) && PathPrefix(`/api/v1/webhook/`)"
  - "traefik.http.routers.labelyard-webhooks.priority=20"
  - "traefik.http.services.labelyard.loadbalancer.server.port=8000"
  - "traefik.http.services.labelyard.loadbalancer.responseforwarding.flushinterval=100ms"
```

## Pangolin

The Pangolin example declares two public resources with blueprint labels: the hub behind Pangolin's SSO, and the webhook path with authentication bypassed, because Spoolman and Grocy cannot sign in. The SSO resource injects the trust token as a request header:

```yaml
labels:
  - "pangolin.public-resources.labelyard.auth.sso-enabled=true"
  - "pangolin.public-resources.labelyard.request-headers[0].name=X-Pangolin-Token"
  - "pangolin.public-resources.labelyard.request-headers[0].value=${LABELYARD_SSO_TRUST_TOKEN}"
  - "pangolin.public-resources.labelyard-webhooks.targets[0].path=/api/v1/webhook/"
  - "pangolin.public-resources.labelyard-webhooks.auth.bypass=true"
```

Set `LABELYARD_SSO_TRUST_TOKEN` to the same value (`openssl rand -hex 32`). How sign-in through the proxy works is described under [users and SSO](/admin/users-and-sso/).

Already running behind a proxy? Keep your existing router or resource name. A new name creates a new resource with a new certificate and new access rules.
