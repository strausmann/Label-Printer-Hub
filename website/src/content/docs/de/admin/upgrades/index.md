---
title: Aktualisieren
description: Image-Tags, wie du aktualisierst und was du vor einem größeren Schritt lesen solltest.
sidebar:
  order: 1
  label: Tags und Aktualisieren
---

## Image-Tags

Jede stabile Version erscheint in der GitHub Container Registry und auf Docker Hub, für `linux/amd64` und `linux/arm64`, mit diesen Tags:

| Tag | Beispiel für 1.6.0 | Nimm ihn, wenn |
|---|---|---|
| `1.6.0` | genau diese Version | du alles reproduzierbar haben willst |
| `1.6` | neuester Patch von 1.6 | du Fehlerbehebungen automatisch willst |
| `1` | neueste Version von 1.x | du bei der Hauptversion bleibst und neue Funktionen willst |
| `latest` | neueste stabile Version | dir alles Neue recht ist |

Vorabversionen wie `1.6.0-rc.1` bekommen nur ihren vollen Versions-Tag, nie `latest`, `1` oder `1.6`.

## Aktualisieren

1. Lies die [Versionshinweise](https://github.com/strausmann/labelyard/releases) aller Versionen zwischen deiner und der neuen.
2. Mach eine [Sicherung](/de/admin/backups/).
3. Ändere den Tag in deiner Compose-Datei, dann:

   ```bash
   docker compose pull
   docker compose up -d
   ```

Datenbankmigrationen laufen beim Start. Dein Daten-Volume, deine Schlüssel und Einstellungen bleiben erhalten.

## Größere Schritte

- [Du kommst von Label Printer Hub](/de/admin/upgrades/from-label-printer-hub/): Labelyard 1.6.0 ist das umbenannte Projekt. Images, Befehl und Umgebungspräfix sind neu; Daten und API bleiben.
- Von 1.4.x: Version 1.5.0 hat alle API-Routen ohne Aliase unter `/api/v1/` verschoben. Passe zuerst Skripte, Proxy-Regeln und Lesezeichen an; die [Versionshinweise zu 1.5.0](https://github.com/strausmann/labelyard/releases/tag/v1.5.0) listen die verschobenen Pfade.
- [Aktualisieren auf 1.7.0](/de/admin/upgrades/to-1-7-0/): Drucker-Antworten melden `connection.snmp.community_set` statt der SNMP-Community, und ein Admin-Schlüssel lässt sich nicht mehr auf Drucker beschränken (`422` `admin_key_not_restrictable`).
