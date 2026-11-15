---
title: Snipe-IT
description: Etiketten für Assets und Standorte aus Snipe-IT drucken.
---

Das Snipe-IT-Plugin schlägt Assets und Standorte in deinem Snipe-IT nach und druckt ihre Etiketten, mit einem QR-Code, der zurück zum Eintrag führt.

## Einrichtung

1. Leg in Snipe-IT ein persönliches API-Token für einen Benutzer an, der Assets und Standorte lesen darf.
2. Öffne in Labelyard **Einstellungen > Integrationen > Snipe-IT**, trag die Adresse von Snipe-IT und das Token ein und teste die Verbindung. Oder setz `LABELYARD_SNIPEIT_URL` und `LABELYARD_SNIPEIT_API_KEY`.

## Drucken

Scanne oder tippe auf der Suchseite eines davon:

- eine Inventarnummer, zum Beispiel `AT-0042`,
- eine numerische Asset-ID, zum Beispiel `42`,
- einen Standort mit dem Präfix `loc:`, zum Beispiel `loc:17`,
- oder einen Etikettenlink, den der Hub früher gedruckt hat (`/asset/…`, `/loc/…`).

Aus einem Skript dieselbe Abfrage in einem Schritt:

```bash
curl -X POST https://labelyard.example.com/api/v1/print \
  -H "X-Label-Hub-Key: lh_..." -H "Content-Type: application/json" \
  -d '{"content_type": "qr_two_lines", "lookup": {"app": "snipeit", "identifier": "42"}}'
```
