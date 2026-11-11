---
title: Integrationen
description: Wie Labelyard mit den Apps spricht, aus denen deine Etiketten kommen, über Plugins, Webhooks und seine API.
sidebar:
  label: Überblick
---

Eine App und Labelyard arbeiten auf drei Wegen zusammen:

| Weg | Wer ihn anstößt | Apps |
|---|---|---|
| **Plugin** | Du, in Labelyard: Du scannst oder tippst eine ID, das Plugin schlägt den Eintrag in seiner App nach, und der Hub druckt das Etikett | [Snipe-IT](/de/integrations/snipe-it/), [Grocy](/de/integrations/grocy/), [Spoolman](/de/integrations/spoolman/) |
| **Webhook** | Die App: Ein Ereignis darin schickt eine Anfrage, und der Hub druckt | [Spoolman und Grocy](/de/integrations/webhooks/) |
| **API** | Die App: Sie ruft die REST-API des Hubs mit einem eigenen Schlüssel auf | [Paperless](/de/integrations/paperless/), [Kept](/de/integrations/kept/), deine eigenen Skripte |

## Eine App verbinden

Öffne mit einem Admin-Schlüssel **Einstellungen > Integrationen**. Trag für jede App ihre Adresse ein und, wo nötig, ihren API-Schlüssel oder ihr Token, und prüf die Verbindung mit dem Test-Knopf. Die Änderung gilt ab der nächsten Anfrage; ein Neustart ist nicht nötig.

Dieselben Werte lassen sich als Umgebungsvariablen setzen, zum Beispiel `LABELYARD_SNIPEIT_URL` und `LABELYARD_SNIPEIT_API_KEY` (alle stehen in der [Konfigurationsreferenz](/de/reference/configuration/)). Eine Variable gewinnt und sperrt das Feld in der Oberfläche.

Ein Geheimnis gehört zu der Adresse, mit der es gespeichert wurde: Änderst du die Adresse einer App, gib ihr Geheimnis neu ein.

## Einträge aus Skripten nachschlagen

`GET /api/v1/lookup/{app}/{id}` liefert, was ein Plugin zu einer ID gefunden hat, ohne zu drucken; `POST /api/v1/print` mit einem Objekt `lookup` druckt in einem Schritt. Siehe die [API-Referenz](/de/developers/api/).

Du hättest gern eine weitere App als Plugin? Plugins sind Python-Pakete; siehe [Mitmachen](/de/developers/contributing/).
