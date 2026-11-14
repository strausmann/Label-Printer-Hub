---
title: Hinter einem Reverse Proxy
description: Labelyard hinter Caddy, Traefik oder Pangolin betreiben, genau einem Proxy vertrauen und die Live-Aktualisierung am Laufen halten.
sidebar:
  label: Reverse Proxy
---

Im Repository liegt unter `examples/` für jeden dieser Proxys eine fertige Compose-Datei: `compose.caddy.yml`, `compose.traefik.yml` und `compose.pangolin.yml`. Alle starten dasselbe Image; nur das Netz und die Labels unterscheiden sich. Für alles andere (nginx, HAProxy) nimmst du die eigenständige Datei und setzt deinen eigenen Proxy davor.

## Drei Dinge, die jede Proxy-Einrichtung braucht

1. **Genau einem Gegenüber vertrauen.** Labelyard liest `X-Forwarded-For` nur von der Adresse in `FORWARDED_ALLOW_IPS`. Gib deinem Proxy eine feste Adresse im gemeinsamen Netz und trag sie in `.env` als `PROXY_IP` ein; die Beispiele reichen sie weiter. Ohne sie sieht jeder Client aus wie der Proxy, und die Anmeldegrenze je Adresse wird zu einem Topf für alle. Nimm weder `*` noch ein Subnetz.
2. **Die öffentliche Adresse setzen.** `LABELYARD_PUBLIC_URL` ist die `https`-Adresse, die geöffnet wird, zum Beispiel `https://labelyard.example.com`, und `LABELYARD_HOST` der Hostname, den die Beispiele weiterleiten.
3. **Den Ereignisstrom nicht puffern.** Live-Aktualisierungen kommen als Server-Sent Events über `/api/v1/events`. Das Caddy-Beispiel setzt `flush_interval -1`, das Traefik-Beispiel `responseforwarding.flushinterval=100ms`. Einstellungen für andere Proxys und wie du den Strom prüfst: [Ereignisstrom und Reverse Proxys](/de/developers/architecture/sse/).

Leg die Adresse des Proxys in seinem eigenen Stack fest (`ipv4_address`). Eine nicht festgelegte Adresse kann nach einem Neustart an einen anderen Container gehen, und dem würde der Hub dann `X-Forwarded-For` glauben. Die Anmeldegrenze zählt IPv6-Clients je /64-Netz (eine Unique-Local- oder Link-Local-Adresse zählt für sich), und eine IPv4-gemappte IPv6-Adresse zählt als ihre IPv4-Adresse. Reicht ein vertrauter Proxy einen Wert weiter, der keine IP-Adresse ist, oder kommt die Anfrage über einen Unix-Socket, teilen sich alle solchen Anmeldungen einen Topf.

## Caddy

Das Beispiel nutzt die Labels von caddy-docker-proxy:

```yaml
labels:
  caddy: ${LABELYARD_HOST}
  caddy.reverse_proxy: "{{upstreams 8000}}"
  caddy.reverse_proxy.flush_interval: "-1"
```

## Traefik

Zwei Router zeigen auf einen Dienst. Der zweite bedient die Webhook-Pfade mit höherer Priorität, damit du ihm eigene Middlewares geben kannst (oder keine, wenn der Hauptrouter eine SSO-Middleware hat):

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

Das Pangolin-Beispiel legt mit Blueprint-Labels zwei öffentliche Ressourcen an: den Hub hinter dem SSO von Pangolin und den Webhook-Pfad ohne Anmeldung, weil Spoolman und Grocy sich nicht anmelden können. Die SSO-Ressource schickt das Vertrauens-Token als Anfrage-Header mit:

```yaml
labels:
  - "pangolin.public-resources.labelyard.auth.sso-enabled=true"
  - "pangolin.public-resources.labelyard.request-headers[0].name=X-Pangolin-Token"
  - "pangolin.public-resources.labelyard.request-headers[0].value=${LABELYARD_SSO_TRUST_TOKEN}"
  - "pangolin.public-resources.labelyard-webhooks.targets[0].path=/api/v1/webhook/"
  - "pangolin.public-resources.labelyard-webhooks.auth.bypass=true"
```

Setz `LABELYARD_SSO_TRUST_TOKEN` auf denselben Wert (`openssl rand -hex 32`). Wie die Anmeldung über den Proxy funktioniert, steht unter [Benutzer und SSO](/de/admin/users-and-sso/).

Läuft der Hub schon hinter einem Proxy? Behalte deinen bisherigen Router- oder Ressourcennamen. Ein neuer Name legt eine neue Ressource an, mit neuem Zertifikat und neuen Zugriffsregeln.
