---
title: Spoolman
description: Spulenetiketten für 3D-Druck-Filament aus Spoolman drucken.
---

Das Spoolman-Plugin schlägt Spulen in deinem Spoolman nach und druckt ihre Etiketten, mit einem QR-Code, der zurück zur Spule führt. Spoolman braucht keinen API-Schlüssel.

## Einrichtung

Öffne **Einstellungen > Integrationen > Spoolman**, trag die Adresse von Spoolman ein und teste die Verbindung. Oder setz `LABELYARD_SPOOLMAN_URL`.

## Drucken

Scanne oder tippe auf der Suchseite eine Spulen-ID, oder einen Etikettenlink, den der Hub früher gedruckt hat (`/spool/…`). Aus einem Skript nimmst du `{"lookup": {"app": "spoolman", "identifier": "<spulen-id>"}}` mit `POST /api/v1/print`.

## Drucken, wenn sich eine Spule ändert

Ereignisse aus Spoolman können den Hub aufrufen, der dann das Etikett der Spule druckt, mit dem restlichen Filament als dritter Zeile (zum Beispiel `851 g übrig`), wenn das Ereignis es mitbringt. Siehe [Webhooks](/de/integrations/webhooks/).
