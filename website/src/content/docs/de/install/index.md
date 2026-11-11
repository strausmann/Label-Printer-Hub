---
title: Mit Docker Compose installieren
description: Labelyard als einen Container starten, die zwei Pflichtwerte setzen und dich zum ersten Mal anmelden.
sidebar:
  label: Docker Compose
---

Labelyard kommt als ein Image, `ghcr.io/strausmann/labelyard` (auch auf Docker Hub als `docker.io/strausmann/labelyard`), für `linux/amd64` und `linux/arm64`. Ein Prozess liefert die REST-API, den Live-Ereignisstrom und die Weboberfläche aus.

## Was du brauchst

- Docker Engine 24 oder neuer (oder Docker Desktop, oder Podman mit dem Compose-Plugin).
- Deine Drucker im selben Netz wie der Host, mit ihren Adressen notiert. Siehe [Drucker anschließen](/de/install/printers/).
- Für den Zugriff von außerhalb deines LANs: einen Reverse Proxy und einen Domainnamen. Siehe [Reverse Proxy](/de/install/reverse-proxy/).

## Die Compose-Datei

Das ist die eigenständige Variante ohne Reverse Proxy, für ein vertrauenswürdiges LAN. Im Repository liegen dieselbe Datei und die Proxy-Varianten unter `examples/`.

```yaml
services:
  labelyard:
    image: ghcr.io/strausmann/labelyard:${HUB_VERSION:-1.6.0}
    container_name: labelyard
    user: "1000:1000"
    ports:
      - "${HUB_PORT:-8000}:8000"
    environment:
      - "LABELYARD_SECRET_KEY=${LABELYARD_SECRET_KEY:?set LABELYARD_SECRET_KEY}"
      - "LABELYARD_PUBLIC_URL=${LABELYARD_PUBLIC_URL:?set LABELYARD_PUBLIC_URL}"
      - LABELYARD_WEBHOOK_API_KEY=${LABELYARD_WEBHOOK_API_KEY:-}
    volumes:
      - ./data:/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8000/healthz"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s
```

## Die zwei Pflichtwerte

Leg sie in eine Datei `.env` neben der Compose-Datei:

```bash
# base64url aus 32 Zufallsbytes; bewahre ihn auf, ohne ihn lassen sich gespeicherte Geheimnisse nicht lesen
LABELYARD_SECRET_KEY=   # openssl rand -base64 32 | tr '+/' '-_'
# die Adresse, unter der du den Hub öffnest; eine lokale wie http://localhost:8000 reicht
LABELYARD_PUBLIC_URL=http://localhost:8000
```

Leg zuerst das Datenverzeichnis an und gib es dem Benutzer, unter dem der Container läuft; ein Verzeichnis, das Docker selbst anlegt, gehört root, und der Hub kann nicht hineinschreiben:

```bash
mkdir -p data && sudo chown 1000:1000 data
```

Dann startest du ihn und prüfst, ob er antwortet:

```bash
docker compose up -d
curl http://localhost:8000/healthz
```

Alle anderen Einstellungen sind optional und stehen in der [Konfigurationsreferenz](/de/reference/configuration/).

## Erste Anmeldung

Eine frische Installation hat noch keinen API-Schlüssel, und die Weboberfläche meldet sich mit einem an. Du hast zwei Wege:

- **Im Browser.** Setz `LABELYARD_BOOTSTRAP_ADMIN_KEY` auf einen Einmalschlüssel mit mindestens 32 Zeichen (`openssl rand -hex 32`) und starte neu. Melde dich damit an; die Bootstrap-Sitzung kann nur den ersten echten Admin-Schlüssel anlegen. Danach meldest du dich mit dem neuen Schlüssel an und entfernst die Variable.
- **Im Container.** Leg den Schlüssel auf der Kommandozeile an; er wird einmal ausgegeben:

  ```bash
  docker compose exec labelyard labelyard admin create-key --scope admin --name first-admin
  ```

Danach fügst du deine Drucker unter **Einstellungen > Drucker** hinzu. Ein Neustart ist nicht nötig.

## Daten und Aktualisierungen

Der gesamte Zustand liegt im Volume `./data`: die Datenbank, die Bögen und die Einstellungen. Sichere es zusammen mit `LABELYARD_SECRET_KEY` (siehe [Sicherungen](/de/admin/backups/)). Zum Aktualisieren änderst du den Image-Tag und führst `docker compose pull && docker compose up -d` aus. Die Tags erklärt [Aktualisieren](/de/admin/upgrades/).
