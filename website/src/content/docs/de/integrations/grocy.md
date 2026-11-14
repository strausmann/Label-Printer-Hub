---
title: Grocy
description: Produktetiketten aus Grocy drucken, auf Abruf oder wenn sich der Bestand ändert.
---

Das Grocy-Plugin schlägt Produkte in deinem Grocy nach und druckt ihre Etiketten, mit einem QR-Code, der zurück zum Produkt führt.

## Einrichtung

1. Leg in Grocy über das Benutzermenü einen API-Schlüssel an.
2. Öffne in Labelyard **Einstellungen > Integrationen > Grocy**, trag die Adresse von Grocy und den Schlüssel ein und teste die Verbindung. Oder setz `LABELYARD_GROCY_URL` und `LABELYARD_GROCY_API_KEY`.

## Drucken

Scanne oder tippe auf der Suchseite eine Produkt-ID oder einen Produkt-Barcode, oder einen Etikettenlink, den der Hub früher gedruckt hat (`/product/…`). Aus einem Skript nimmst du `{"lookup": {"app": "grocy", "identifier": "<produkt-id>"}}` mit `POST /api/v1/print`.

## Drucken, wenn sich der Bestand ändert

Grocy kann den Hub aufrufen, wenn Bestand hinzukommt oder entnommen wird, und der Hub druckt ein Etikett für das Produkt, mit der Bestandsänderung als dritter Zeile (zum Beispiel `Bestandsänderung: +2`), wenn das Ereignis eine mitbringt. Siehe [Webhooks](/de/integrations/webhooks/).
