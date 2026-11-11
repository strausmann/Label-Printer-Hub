---
title: Von Label Printer Hub zu Labelyard
description: Labelyard ist der neue Name von Label Printer Hub. Was sich ändert, was bleibt und wie du in drei Schritten aktualisierst.
sidebar:
  order: 2
---

Label Printer Hub heißt jetzt **Labelyard** (Version 1.6.0). Das ist eine Umbenennung, kein Neubau: Deine Daten, deine API-Schlüssel und deine API-Clients ziehen mit um. Die Gründe und die vollständige Kompatibilitätstabelle stehen in der [Entscheidung zur Umbenennung](https://github.com/strausmann/labelyard/blob/main/docs/decisions/0025-rename-to-labelyard.md).

## Was sich ändert

| Vorher | Nachher |
|---|---|
| Image `ghcr.io/strausmann/label-printer-hub-backend` | `ghcr.io/strausmann/labelyard` |
| Image `docker.io/<user>/label-printer-hub-backend` | `docker.io/<user>/labelyard` |
| Befehl `printer-hub` | `labelyard` (der alte Befehl bleibt als Alias) |
| Umgebungspräfix `PRINTER_HUB_` | `LABELYARD_` (das alte Präfix wird weiter gelesen, siehe [Umgebungsvariablen](#umgebungsvariablen)) |
| PDF-Schriftart `PRINTHUB_PDF_FONT` | `LABELYARD_PDF_FONT` (der alte Name wird weiter gelesen) |
| Repository `strausmann/Label-Printer-Hub` | `strausmann/labelyard` (GitHub leitet die alte Adresse weiter) |
| Beispielvariablen `PRINTERHUB_HOST`, `LABEL_HUB_URL`, `LABEL_HUB_KEY` | `LABELYARD_HOST`, `LABELYARD_URL`, `LABELYARD_KEY` |

## In drei Schritten aktualisieren

1. Ändere `image:` in deiner Compose-Datei auf `ghcr.io/strausmann/labelyard:1.6.0` (oder `docker.io/<user>/labelyard:1.6.0`).
2. Hol das Image: `docker compose pull`.
3. Starte neu: `docker compose up -d`.

Dein Daten-Volume, die Datenbankdatei, API-Schlüssel, Sitzungen und der Header `X-Label-Hub-Key` funktionieren weiter. Wenn deine Compose-Datei den Container oder den Dienst benennt, kannst du diese Namen behalten; im Image hängt nichts davon ab.

Du kommst von 1.4.x? Bring deine API-Clients zuerst auf 1.5.0 (`/api/v1`-Pfade, ohne Kompatibilitätsrouten); siehe die [Versionshinweise zu 1.5.0](https://github.com/strausmann/labelyard/releases/tag/v1.5.0). Die Umbenennung selbst ändert keinen API-Pfad.

## Was gleich bleibt

- Das Datenverzeichnis und der Name der Datenbankdatei (standardmäßig `printer-hub.db`): Bestehende Installationen finden ihre Daten dort, wo sie sie gelassen haben.
- API-Schlüssel, Sitzungen und der Bootstrap-Ablauf.
- Der Anfrage-Header `X-Label-Hub-Key` und das Schlüsselpräfix `lh_`.
- Alle `/api/v1`-Pfade und der Ereignisstrom.
- Der registrierte Name des Exportformats für Bogentypen (`.sheet-type`).

## Umgebungsvariablen

Umbenennen musst du vorerst nicht. Der Hub liest `LABELYARD_*`; die früheren Namen `PRINTER_HUB_*` werden als veralteter Rückfall weiter gelesen.

- Eine `LABELYARD_`-Variable gewinnt immer gegen ihren `PRINTER_HUB_`-Zwilling.
- Leere Werte werden bei beiden Präfixen ignoriert, eine Compose-Zeile wie `PRINTER_HUB_X=${PRINTER_HUB_X:-}` überschreibt also nie etwas.
- Beim Start schreibt der Hub eine Warnzeile, die die alten Namen auflistet, die noch wirken, damit du weißt, was du umbenennen solltest. Wird ein alter Name von einem `LABELYARD_`-Zwilling überstimmt, listet eine zweite Zeile diese ignorierten Namen. Beide Zeilen enthalten nur **Namen**, nie Werte.
- Die alten Namen werden mindestens bis 2.0.0 gelesen.
- Die PDF-Schriftart folgt demselben Muster: `LABELYARD_PDF_FONT` wird zuerst gelesen, das alte `PRINTHUB_PDF_FONT`, wenn das neue nicht gesetzt oder leer ist, mit einer Warnung, die die Variable nennt.

Um die Umbenennung in einer Datei `.env` abzuschließen, ersetzt du das Präfix und startest neu:

```bash
sed -i 's/^PRINTER_HUB_/LABELYARD_/' .env
```

Das ändert nur die Datei `.env`. Compose-Dateien, die die Variablen selbst nennen (zum Beispiel `PRINTER_HUB_SECRET_KEY=${PRINTER_HUB_SECRET_KEY:?...}`), musst du von Hand anpassen, auf beiden Seiten jeder Zeile, sonst fragt Compose weiter nach dem alten Namen.

## Reverse Proxy und Pangolin

Behalte deinen bisherigen Ressourcenschlüssel (Traefik-Routername, Pangolin `public-resources.<key>`, Caddy-Label). Ein neuer Schlüssel legt eine neue Ressource neben der alten an, mit neuem Zertifikat und neuen Zugriffsregeln. Die Beispiele nutzen jetzt den Schlüssel `labelyard`; das betrifft nur neue Installationen.

Die Hostname-Variable der Beispiele heißt `LABELYARD_HOST`; deine eigene Proxy-Konfiguration darf jeden Namen nutzen.

## Alte Images

Die alten Images (`label-printer-hub-backend` in beiden Registries) bekommen keine Aktualisierungen mehr. Regeln von Watchtower, Renovate oder Dependabot, die darauf festgelegt sind, bieten 1.6.0 nie an: Ändere den Image-Namen einmal von Hand, wie in den drei Schritten oben.
